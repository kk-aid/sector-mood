"""신고가 알림: 역대 신고가(ATH)·52주 신고가 종목을 섹터별로 묶어 텔레그램으로 보냄.

  python -m pipeline.newhigh --market kr                        # 조회 → 기록 → 전송
  python -m pipeline.newhigh --market us --dry-run              # 전송·기록 없이 메시지만 출력
  python -m pipeline.newhigh --market jp --synthetic --dry-run  # 네트워크 없이 합성 데이터로 확인

판정 (config.NEWHIGH)
  1. 그날 상승률 상위 top_n 안 (우선주·스팩 등 제외 후 순위)
  2. 양봉·상승 마감: 종가 > 시가, 등락률 > 0
  3. 장중 신고가: 당일 고가 ≥ 역대 최고가(High.All) / 52주 최고가(price_52_week_high)
     TradingView 고가는 분할·무상증자 반영 기준이라 증자 후 신고가가 빠지지 않음.

섹터 라벨 우선순위: data/newhigh/labels.csv → 소형주 묶음 → FactSet 산업 한국어 → 미분류
휴장일에는 직전 거래일 데이터가 그대로 오므로, 직전 실행과 결과가 같으면 전송·기록을 건너뜀.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import config
from .universe import HEADERS, SUBTYPE_BLOCK

WD = "월화수목금토일"
COLUMNS = ["name", "description", "close", "open", "high", "change", "market_cap_basic",
           "Value.Traded", "High.All", "price_52_week_high", "industry", "exchange", "type", "subtype"]


# ── 수집 ────────────────────────────────────────────────
def scan(mkt: str) -> list[dict]:
    """상승 종목을 등락률 내림차순으로 받음 (상위 top_n 의 4배, 걸러낼 여유분 포함)."""
    m, c = config.market(mkt), config.NEWHIGH[mkt]
    flt = [
        {"left": "type", "operation": "in_range", "right": list(config.SEC_TYPES)},
        {"left": "change", "operation": "greater", "right": 0},
    ]
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
            "range": [0, c["top_n"] * 4], "options": {"lang": c["lang"]},
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


def pick(rows: list[dict], top_n: int) -> tuple[list[dict], list[dict], list[dict]]:
    """(상위 top_n 기준 종목, 역대 신고가, 52주 신고가[역대 제외]) 반환. 각 종목에 rank 부여."""
    base = [r for r in rows if _eligible(r) and (r.get("change") or 0) > 0]
    base.sort(key=lambda r: -(r.get("change") or 0))
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
    code = str(r.get("name") or "")
    if (mkt, code) in labels:
        return labels[(mkt, code)]
    c = config.NEWHIGH[mkt]
    mcap = r.get("market_cap_basic")
    if c["small_cap"] and mcap is not None and mcap < c["small_cap"]:
        return c["small_label"]
    ind = r.get("industry") or ""
    return config.INDUSTRY_KO.get(ind, ind) or "미분류"


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
def _section(title: str, items: list[dict], mkt: str, labels: dict, note: str = "") -> list[str]:
    e = html.escape
    groups: dict[str, list[dict]] = {}
    for r in items:
        groups.setdefault(label_of(r, mkt, labels), []).append(r)
    order = sorted(groups, key=lambda k: -max(x["change"] for x in groups[k]))
    out = [f"<b>{title} {len(items)}</b>{note}"]
    for k in order:
        names = ", ".join(f"{e(display_name(x, mkt))} {x['change']:+.1f}%"
                          for x in sorted(groups[k], key=lambda x: -x["change"]))
        out.append(f"({e(k)}) {names}")
    return out


def build_message(mkt: str, day, ath: list[dict], w52: list[dict], labels: dict) -> str:
    m, c = config.market(mkt), config.NEWHIGH[mkt]
    lines = [f"{m['flag']} <b>{m['label']} 신고가 · {day:%Y.%m.%d}({WD[day.weekday()]})</b>",
             f"상승률 상위 {c['top_n']} · 양봉 마감 · 장중 신고가"]
    if not ath and not w52:
        lines += ["", "조건을 충족한 종목 없음"]
    if ath:
        lines += [""] + _section("🏆 역대 신고가", ath, mkt, labels)
    if w52:
        lines += [""] + _section("📈 52주 신고가", w52, mkt, labels, " (역대 제외)")
    text = "\n".join(lines)
    while len(text) > 4000 and len(lines) > 3:            # 텔레그램 한도 4096자
        lines.pop()
        text = "\n".join(lines + ["…"])
    return text


# ── 기록 ────────────────────────────────────────────────
def signature(base: list[dict]) -> str:
    key = "|".join(f"{r.get('name')}:{r.get('close')}:{r.get('change')}" for r in base)
    return hashlib.sha1(key.encode()).hexdigest()


def record(mkt: str, day, ath: list[dict], w52: list[dict], labels: dict, sig: str):
    """data/newhigh/<시장>/YYYY-MM.csv 에 누적 (같은 날 재실행 시 그날 행을 교체)."""
    d = config.NEWHIGH_ROOT / mkt
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{day:%Y-%m}.csv"
    cols = ["date", "kind", "rank", "code", "name", "label", "change", "close", "mcap"]
    old = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            old = [r for r in csv.DictReader(f) if r["date"] != day.isoformat()]
    new = [{"date": day.isoformat(), "kind": kind, "rank": r["rank"], "code": r.get("name"),
            "name": display_name(r, mkt), "label": label_of(r, mkt, labels),
            "change": round(r["change"], 2), "close": r.get("close"), "mcap": r.get("market_cap_basic")}
           for kind, rows in (("ATH", ath), ("52W", w52)) for r in rows]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(old + new)
    (d / "last.json").write_text(json.dumps({"day": day.isoformat(), "sig": sig}))


def last_sig(mkt: str) -> str | None:
    p = config.NEWHIGH_ROOT / mkt / "last.json"
    return json.loads(p.read_text()).get("sig") if p.exists() else None


# ── 실행 ────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="kr", choices=list(config.MARKETS))
    ap.add_argument("--dry-run", action="store_true", help="전송·기록 없이 메시지만 출력")
    ap.add_argument("--force", action="store_true", help="직전과 결과가 같아도 전송")
    ap.add_argument("--synthetic", action="store_true", help="네트워크 없이 합성 데이터 사용")
    a = ap.parse_args()
    mkt = a.market
    day = datetime.now(ZoneInfo(config.market(mkt)["tz"])).date()

    if a.synthetic:
        from .synthetic import newhigh_rows
        rows = newhigh_rows(mkt)
    else:
        rows = scan(mkt)
    base, ath, w52 = pick(rows, config.NEWHIGH[mkt]["top_n"])
    labels = load_labels()
    text = build_message(mkt, day, ath, w52, labels)
    print(f"[newhigh:{mkt}] 기준 {len(base)}종목 · 역대 {len(ath)} · 52주 {len(w52)}")

    if a.dry_run:
        print(text)
        return
    sig = signature(base)
    if sig == last_sig(mkt) and not a.force:
        print(f"[newhigh:{mkt}] 직전 실행과 결과 동일 (휴장일 추정) → 전송·기록 생략")
        return
    record(mkt, day, ath, w52, labels, sig)
    from .notify import send
    send(text)


if __name__ == "__main__":
    main()
