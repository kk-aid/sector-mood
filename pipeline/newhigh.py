"""신고가 알림: 역대 신고가(ATH)·52주 신고가 종목을 섹터별로 묶어 텔레그램으로 보냄.

  python -m pipeline.newhigh --market kr                        # 조회 → 기록 → 전송
  python -m pipeline.newhigh --market us --dry-run              # 전송·기록 없이 메시지만 출력
  python -m pipeline.newhigh --market jp --synthetic --dry-run  # 네트워크 없이 합성 데이터로 확인
  python -m pipeline.newhigh --market kr --check "KT&G,코웨이"   # 특정 종목이 왜 포함·제외됐는지 출력

판정 (config.NEWHIGH)
  1. (top_n 을 숫자로 둔 경우만) 그날 상승률 상위 top_n 안. 기본값 None = 제한 없음
  2. 양봉·상승 마감: 종가 > 시가, 등락률 > 0
  3. 장중 신고가: 당일 고가 ≥ 역대 최고가(High.All) / 52주 최고가(price_52_week_high)
     TradingView 고가는 분할·무상증자 반영 기준이라 증자 후 신고가가 빠지지 않음.

섹터 라벨 우선순위: 근거·확인일이 있는 taxonomy.csv 승인 업종 → 토스 업종 → FactSet 산업 한국어 → 미분류 (규모·기존 테마 별도)
휴장일에는 직전 거래일 데이터가 그대로 오므로, 직전 실행과 결과가 같으면 전송·기록을 건너뜀.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import config
from .universe import HEADERS, SUBTYPE_BLOCK

WD = "월화수목금토일"
COLUMNS = ["name", "description", "close", "open", "high", "change", "market_cap_basic",
           "Value.Traded", "High.All", "price_52_week_high", "industry", "exchange", "type", "subtype", "sector"]


# ── 수집 ────────────────────────────────────────────────
SCAN_MAX = 8000                         # 순위 제한이 없을 때 받아올 최대 행 수 (시장 전체 상승 종목)


def scan(mkt: str, rising_only: bool = True) -> list[dict]:
    """종목을 등락률 내림차순으로 받음. top_n 이 있으면 그 4배, 없으면 상승 종목 전체."""
    m, c = config.market(mkt), config.NEWHIGH[mkt]
    flt = [{"left": "type", "operation": "in_range", "right": list(config.SEC_TYPES)}]
    if rising_only:
        flt.append({"left": "change", "operation": "greater", "right": 0})
    if c["min_mcap"]:
        flt.append({"left": "market_cap_basic", "operation": "egreater", "right": c["min_mcap"]})
    if c["min_value"]:
        flt.append({"left": "Value.Traded", "operation": "egreater", "right": c["min_value"]})
    if m["exchanges"]:
        flt.append({"left": "exchange", "operation": "in_range", "right": list(m["exchanges"])})
    cols = list(COLUMNS)
    for attempt in range(4):
        payload = {
            "markets": [m["tv"]], "columns": cols, "filter": flt,
            "sort": {"sortBy": "change", "sortOrder": "desc"},
            "range": [0, c["top_n"] * 4 if c.get("top_n") and rising_only else SCAN_MAX],
            "options": {"lang": c["lang"]},
        }
        try:
            r = requests.post(f"https://scanner.tradingview.com/{m['tv']}/scan", json=payload,
                              timeout=60, headers=HEADERS)
            if r.status_code == 400 and "High.All" in cols and "High.All" in r.text:
                # 역대 고가 필드를 거부하면 52주 판정만이라도 진행
                print(f"[newhigh:{mkt}] High.All 필드 거부 → 역대 신고가 판정 생략: {r.text[:200]}")
                cols.remove("High.All")
                continue
            r.raise_for_status()
            return [dict(zip(cols, row["d"])) for row in r.json().get("data", [])]
        except Exception as e:  # noqa: BLE001
            print(f"[newhigh:{mkt}] 재시도 {attempt + 1}: {e}")
    raise RuntimeError(f"[{mkt}] TradingView 스크리너 응답 없음")


# ── 판정 ────────────────────────────────────────────────
def _hit(high, ref) -> bool:
    return high is not None and ref is not None and ref > 0 and high >= ref * (1 - config.NEWHIGH_TOL)


def _eligible(r: dict) -> bool:
    if (r.get("subtype") or "").lower() in SUBTYPE_BLOCK:
        return False
    text = f"{r.get('name') or ''} {r.get('description') or ''}"
    return not any(x in text for x in config.NEWHIGH_EXCLUDE)


def pick(rows: list[dict], top_n: int | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """(기준 종목, 역대 신고가, 52주 신고가[역대 제외]) 반환. 각 종목에 상승률 순위 rank 부여.
    top_n=None 이면 상승 종목 전체가 기준."""
    base = [r for r in rows if _eligible(r) and (r.get("change") or 0) > 0]
    base.sort(key=lambda r: -(r.get("change") or 0))
    if top_n:
        base = base[:top_n]
    ath, w52 = [], []
    for i, r in enumerate(base, 1):
        r["rank"] = i
        if not (r.get("close") and r.get("open") and r["close"] > r["open"]):
            continue                                      # 음봉·보합 제외
        if _hit(r.get("high"), r.get("High.All")):
            ath.append(r)
        elif _hit(r.get("high"), r.get("price_52_week_high")):
            w52.append(r)
    return base, ath, w52


# ── 라벨·이름 ───────────────────────────────────────────
def load_labels() -> dict[tuple[str, str], str]:
    p = config.NEWHIGH_ROOT / "labels.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return {(r["market"], r["code"]): r["label"] for r in csv.DictReader(f) if r.get("label")}


def label_of(r: dict, mkt: str, labels: dict) -> str:
    from .taxonomy import profile
    return profile(r, mkt, labels)['industry']



_SUFFIX = ("보통주", " Co., Ltd.", ",Ltd.", " Corporation", " Holdings", " Inc.", " Corp.", " Ltd.")


def display_name(r: dict, mkt: str) -> str:
    if mkt == "us":
        return str(r.get("name"))
    nm = str(r.get("description") or r.get("name"))
    for s in _SUFFIX:
        nm = nm.replace(s, "")
    nm = nm.strip()
    return nm if len(nm) <= 14 else nm[:13] + "…"


# ── 메시지 ──────────────────────────────────────────────
def size_tag(r, mkt):
    cap, limit = r.get('market_cap_basic'), config.NEWHIGH[mkt]['small_cap']
    return ' [소형주]' if limit and cap is not None and cap < limit else ''


def _section(title: str, items: list[dict], mkt: str, labels: dict, note: str = "",
             notes: dict | None = None, used: set | None = None) -> list[str]:
    e = html.escape
    groups: dict[str, list[dict]] = {}
    for r in items:
        groups.setdefault(label_of(r, mkt, labels), []).append(r)
    order = sorted(groups, key=lambda k: -max(x["change"] for x in groups[k]))
    out = [f"<b>{title} {len(items)}</b>{note}"]
    for k in order:
        names = ", ".join(f"{e(display_name(x, mkt))} {x['change']:+.1f}%{size_tag(x, mkt)}"
                          for x in sorted(groups[k], key=lambda x: -x["change"]))
        out.append(f"({e(k)}) {names}")
        if notes and k in notes and used is not None and k not in used:   # 군집 재료는 처음 나올 때 한 번만
            out += notes[k]
            used.add(k)
    return out


def build_message(mkt: str, day, ath: list[dict], w52: list[dict], labels: dict,
                  extra: dict | None = None) -> str:
    """기존 형식(라벨·기업명·등락률) 그대로. extra(보강 결과)가 있으면 군집 요약·재료 줄·링크를 덧붙임."""
    m, c = config.market(mkt), config.NEWHIGH[mkt]
    e = html.escape
    cond = f"상승률 상위 {c['top_n']} · " if c.get("top_n") else ""
    lines = [f"{m['flag']} <b>{m['label']} 신고가 · {day:%Y.%m.%d}({WD[day.weekday()]})</b>",
             f"{cond}상승·양봉 마감 · 장중 신고가",
             "업종 기준 묶음 · [소형주]는 규모 태그"]
    clusters = (extra or {}).get("clusters") or []
    today_cl = [cl for cl in clusters if cl["n"] >= 2]
    if today_cl:
        lines.append("🔥 군집: " + " · ".join(f"{e(cl['label'])} {cl['n']}" for cl in today_cl[:6]))
        acc = sorted(clusters, key=lambda cl: -cl["n5"])[:4]
        if any(cl["n5"] > cl["n"] for cl in acc):
            lines.append("   5일 누적: " + " · ".join(f"{e(cl['label'])} {cl['n5']}" for cl in acc))
    notes, used = (extra or {}).get("notes"), set()
    if not ath and not w52:
        lines += ["", "조건을 충족한 종목 없음"]
    if ath:
        lines += [""] + _section("🏆 역대 신고가", ath, mkt, labels, notes=notes, used=used)
    if w52:
        lines += [""] + _section("📈 52주 신고가", w52, mkt, labels, " (역대 제외)", notes=notes, used=used)
    if (extra or {}).get("url") and (ath or w52):
        lines += ["", f'<a href="{e(extra["url"])}">🔗 차트·재료 전체 보기</a>']
    return "\n".join(lines)


def split_message(text: str, limit: int = 3900) -> list[str]:
    """텔레그램 한도(4096자)를 넘으면 줄 단위로 나눔. 이어지는 메시지에는 (2/3) 표시."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:                           # 한 줄이 한도보다 긴 경우 (종목이 아주 많은 그룹)
            cut = line.rfind(", ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                parts.append(cur); cur = ""
            parts.append(line[:cut]); line = line[cut + 2:] if line[cut:cut + 2] == ", " else line[cut:]
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur); cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    if len(parts) > 1:
        parts = [p if i == 0 else f"({i + 1}/{len(parts)})\n{p}" for i, p in enumerate(parts)]
    return parts


# ── 기록 ────────────────────────────────────────────────
def signature(base: list[dict]) -> str:
    key = "|".join(f"{r.get('name')}:{r.get('close')}:{r.get('change')}" for r in base)
    return hashlib.sha1(key.encode()).hexdigest()


def record(mkt: str, day, ath: list[dict], w52: list[dict], labels: dict, sig: str):
    """data/newhigh/<시장>/YYYY-MM.csv 에 누적 (같은 날 재실행 시 그날 행을 교체)."""
    d = config.NEWHIGH_ROOT / mkt
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{day:%Y-%m}.csv"
    cols = ["date", "kind", "rank", "code", "name", "label", "change", "close", "mcap", "classification_version"]
    old = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            old = [r for r in csv.DictReader(f) if r["date"] != day.isoformat()]
    new = [{"date": day.isoformat(), "kind": kind, "rank": r["rank"], "code": r.get("name"),
            "name": display_name(r, mkt), "label": label_of(r, mkt, labels),
            "change": round(r["change"], 2), "close": r.get("close"), "mcap": r.get("market_cap_basic"),
            "classification_version": "business-v1"}
           for kind, rows in (("ATH", ath), ("52W", w52)) for r in rows]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(old + new)
    (d / "last.json").write_text(json.dumps({"day": day.isoformat(), "sig": sig}))


def last_sig(mkt: str) -> str | None:
    p = config.NEWHIGH_ROOT / mkt / "last.json"
    return json.loads(p.read_text()).get("sig") if p.exists() else None


# ── 진단 ────────────────────────────────────────────────
def explain(r: dict, base_codes: set, top_n: int | None) -> str:
    """종목 하나가 포함·제외된 이유."""
    chg, o, cl, hi = r.get("change"), r.get("open"), r.get("close"), r.get("high")
    ath, w52 = r.get("High.All"), r.get("price_52_week_high")
    f = lambda x: "–" if x is None else f"{x:,.2f}"           # noqa: E731
    info = (f"등락 {f(chg)}% · 시가 {f(o)} · 종가 {f(cl)} · 고가 {f(hi)} · "
            f"52주 고가 {f(w52)} · 역대 고가 {f(ath)} · 시총 "
            f"{'–' if r.get('market_cap_basic') is None else format(r['market_cap_basic'] / 1e8, ',.0f') + '억'}")
    if not _eligible(r):
        why = "제외: 우선주·스팩 등"
    elif not chg or chg <= 0:
        why = "제외: 상승 마감 아님"
    elif top_n and r.get("name") not in base_codes:
        why = f"제외: 상승률 상위 {top_n} 밖"
    elif not (cl and o and cl > o):
        why = "제외: 양봉 아님 (종가 ≤ 시가)"
    elif _hit(hi, ath):
        why = "포함: 역대 신고가"
    elif _hit(hi, w52):
        why = "포함: 52주 신고가"
    else:
        gap = (hi / w52 - 1) * 100 if hi and w52 else None
        why = f"제외: 장중 고가가 52주 고가 미달 ({'–' if gap is None else f'{gap:+.2f}%'})"
    return f"{why}\n    {info}"


def check(mkt: str, names: list[str]):
    rows = scan(mkt, rising_only=False)
    c = config.NEWHIGH[mkt]
    base, _, _ = pick(rows, c.get("top_n"))
    codes = {r.get("name") for r in base}
    for q in names:
        q = q.strip()
        hits = [r for r in rows if q == str(r.get("name")) or q in str(r.get("description") or "")]
        if not hits:
            print(f"[{q}] 스크리너 결과에 없음 (시총·거래대금 하한, 종목 유형, 이름 표기 확인)")
            continue
        for r in hits[:3]:
            print(f"[{q}] {r.get('description')} ({r.get('name')}) → {explain(r, codes, c.get('top_n'))}")


# ── 실행 ────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="kr", choices=list(config.MARKETS))
    ap.add_argument("--dry-run", action="store_true", help="전송·기록 없이 메시지만 출력")
    ap.add_argument("--force", action="store_true", help="직전과 결과가 같아도 전송")
    ap.add_argument("--synthetic", action="store_true", help="네트워크 없이 합성 데이터 사용")
    ap.add_argument("--check", metavar="이름,코드", help="쉼표로 구분한 종목의 포함·제외 이유만 출력")
    ap.add_argument("--no-enrich", action="store_true", help="차트·공시·뉴스·군집 보강 없이 기존 메시지만")
    a = ap.parse_args()
    mkt = a.market
    if a.check:
        check(mkt, a.check.split(","))
        return
    day = datetime.now(ZoneInfo(config.market(mkt)["tz"])).date()

    if a.synthetic:
        from .synthetic import newhigh_rows
        rows = newhigh_rows(mkt)
    else:
        rows = scan(mkt)
    base, ath, w52 = pick(rows, config.NEWHIGH[mkt].get("top_n"))
    labels = load_labels()
    print(f"[newhigh:{mkt}] 기준 {len(base)}종목 · 역대 {len(ath)} · 52주 {len(w52)}")

    if not a.dry_run:
        sig = signature(base)
        if sig == last_sig(mkt) and not a.force:
            print(f"[newhigh:{mkt}] 직전 실행과 결과 동일 (휴장일 추정) → 전송·기록 생략")
            return
        record(mkt, day, ath, w52, labels, sig)

    extra = None
    if not a.no_enrich and (ath or w52):
        import tempfile
        from . import newhigh_enrich
        try:
            extra = newhigh_enrich.run(
                mkt, day, ath, w52, lambda r: label_of(r, mkt, labels), lambda r: display_name(r, mkt),
                synthetic=a.synthetic, out_png=Path(tempfile.mkdtemp(prefix="newhigh_")),
                write_site=not a.dry_run)
        except Exception as ex:  # noqa: BLE001  보강이 실패해도 기존 메시지는 보냄
            print(f"[newhigh:{mkt}] 보강 실패 → 기존 메시지만 전송: {ex!r}")
    text = build_message(mkt, day, ath, w52, labels, extra)
    charts = (extra or {}).get("charts", [])

    if a.dry_run:
        print("\n\n".join(split_message(text)))
        for pth, cap in charts:
            print(f"[차트] {pth} — {cap}")
        return
    from .notify import send
    for part in split_message(text):
        send(part)
    for pth, cap in charts:
        try:
            send_photo(pth, cap)
        except Exception as ex:  # noqa: BLE001
            print(f"[newhigh:{mkt}] 차트 전송 실패: {ex}")


def send_photo(path, caption: str):
    import os
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print(f"[newhigh] 텔레그램 설정 없음 → 차트 전송 생략 ({path})")
        return
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", timeout=60,
                          data={"chat_id": chat, "caption": caption[:1000]}, files={"photo": f})
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")


if __name__ == "__main__":
    main()
