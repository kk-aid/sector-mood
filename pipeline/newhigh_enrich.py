"""신고가 보강: 1년 차트 · 공시 · 뉴스 헤드라인 · 섹터 군집 · 업종 흐름 · 신고가 이후 성과.

newhigh.py 가 판정한 종목 목록을 받아서
  1) 텔레그램용 덧붙임 정보 (군집 줄, 군집별 재료, 차트 이미지)
  2) 사이트 '신고가' 탭용 JSON (docs/data/<시장>/newhigh/)
을 만든다. 어느 단계가 실패해도 기존 신고가 메시지는 그대로 나가도록 호출부에서 예외를 삼킴.

소스
- 가격: yfinance (한국 .KS → 실패 시 .KQ, 일본 .T)
- 뉴스: Google News RSS (키 불필요, 비공식) — 제목·링크만 사용, 본문 저장 안 함
- 공시: 한국 DART OpenAPI (환경변수 DART_API_KEY 있을 때만), 미국 SEC EDGAR (키 불필요)
"""
from __future__ import annotations

import csv
import email.utils
import io
import json
import math
import os
import re
import statistics
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

from . import config

UA = "Mozilla/5.0 (sector-mood bot)"
QUAD = {"lead": "선도", "weak": "약화", "lag": "소외", "imp": "개선"}
EIGHT_K = {
    "1.01": "주요 계약", "1.02": "계약 종료", "2.01": "인수·처분 완료", "2.02": "실적 발표",
    "2.03": "채무 발생", "2.05": "구조조정", "3.01": "상장 관련", "3.02": "주식 발행",
    "5.02": "임원 변경", "5.03": "정관 변경", "5.07": "주총 결과", "7.01": "IR 자료", "8.01": "기타 주요사항",
}
SEC_FORMS = {"8-K", "6-K", "10-Q", "10-K", "20-F", "S-1", "S-3", "SC 13D", "SC 13G", "424B5"}


# ── 설정 (config 에 없으면 기본값) ───────────────────────
def _cfg(name, default):
    return getattr(config, name, default)


CLUSTER_MIN = _cfg("NEWHIGH_CLUSTER_MIN", 3)        # 같은 라벨 당일 N종목 이상이면 군집
ENRICH_MAX = _cfg("NEWHIGH_ENRICH_MAX", 60)         # 뉴스·공시를 찾을 최대 종목 수 (군집 종목 우선)
CHART_MAX = _cfg("NEWHIGH_CHART_MAX", 3)            # 텔레그램으로 보낼 차트 이미지 수
CHART_PER_IMG = _cfg("NEWHIGH_CHART_PER_IMG", 6)    # 이미지 한 장당 종목 수
FOLLOW_DAYS = _cfg("NEWHIGH_FOLLOW_DAYS", 20)       # 사후 성과를 볼 과거 기록일 수
FOLLOW_MAX = _cfg("NEWHIGH_FOLLOW_MAX", 500)        # 사후 성과용 가격을 받을 최대 종목 수
SITE_KEEP_DAYS = _cfg("NEWHIGH_SITE_KEEP_DAYS", 60)  # 사이트용 일별 파일 보관 일수
NEWS_DAYS = 3


# ── 가격 ────────────────────────────────────────────────
def yf_candidates(mkt: str, code: str) -> list[str]:
    code = str(code)
    if mkt == "us":
        return [code.replace(".", "-").replace("/", "-")]
    if mkt == "kr":
        return [f"{code}.KS", f"{code}.KQ"]
    return [f"{code}.T"]


def _yf_download(symbols: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    import yfinance as yf
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), 100):
        part = symbols[i:i + 100]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(part, period=period, interval="1d", auto_adjust=False,
                                 group_by="column", threads=True, progress=False)
                if df is not None and not df.empty:
                    break
            except Exception as e:  # noqa: BLE001
                print(f"[enrich] 가격 재시도 {attempt + 1}: {e}")
            time.sleep(3 * (attempt + 1))
        if df is None or df.empty:
            continue
        if not isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_product([df.columns, part])
        for s in part:
            try:
                sub = pd.DataFrame({"close": df["Close"][s], "high": df["High"][s],
                                    "volume": df["Volume"][s]}).dropna(subset=["close"])
            except KeyError:
                continue
            if len(sub) >= 20:
                sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize()
                out[s] = sub
    return out


def fetch_history(mkt: str, codes: list[str]) -> dict[str, pd.DataFrame]:
    """종목코드 → 일봉 DataFrame(close, high, volume)."""
    codes = list(dict.fromkeys(str(c) for c in codes))
    first = {yf_candidates(mkt, c)[0]: c for c in codes}
    got = _yf_download(list(first))
    out = {first[s]: df for s, df in got.items()}
    alt = {yf_candidates(mkt, c)[1]: c for c in codes if c not in out and len(yf_candidates(mkt, c)) > 1}
    if alt:
        for s, df in _yf_download(list(alt)).items():
            out[alt[s]] = df
    print(f"[enrich:{mkt}] 가격 {len(out)}/{len(codes)}종목")
    return out


# ── 뉴스 (Google News RSS) ──────────────────────────────
_NEWS_LOCALE = {"kr": ("ko", "KR", "KR:ko"), "us": ("en-US", "US", "US:en"), "jp": ("ja", "JP", "JP:ja")}


def parse_rss(content: bytes, n: int = 3, must: list[str] | None = None) -> list[dict]:
    root = ET.fromstring(content)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src_el = it.find("source")
        src = (src_el.text or "").strip() if src_el is not None else ""
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        if must and not any(m and m.lower() in title.lower() for m in must):
            continue
        try:
            d = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            d = ""
        items.append({"t": title, "u": (it.findtext("link") or "").strip(), "s": src, "d": d})
    items.sort(key=lambda x: x["d"], reverse=True)
    return items[:n]


def google_news(mkt: str, query: str, must: list[str] | None = None, n: int = 3) -> list[dict]:
    hl, gl, ceid = _NEWS_LOCALE[mkt]
    url = "https://news.google.com/rss/search?" + urlencode(
        {"q": f"{query} when:{NEWS_DAYS}d", "hl": hl, "gl": gl, "ceid": ceid})
    r = requests.get(url, timeout=20, headers={"User-Agent": UA})
    r.raise_for_status()
    return parse_rss(r.content, n=n, must=must)


def news_query(mkt: str, code: str, name: str, ja_name: str | None = None) -> tuple[str, list[str]]:
    """(검색어, 제목에 반드시 들어가야 할 단어들) — 동명이인·무관 기사 줄이기."""
    if mkt == "kr":
        return f'"{name}"', [name]
    if mkt == "jp":
        nm = ja_name or name
        return f'"{nm}"', [nm, code]
    short = re.sub(r"[,.]|\b(Inc|Corp|Corporation|Holdings|Ltd|Co|Class [A-C]|plc|N\.?V|S\.?A)\b", "", name).strip()
    short = " ".join(short.split()[:3]) or code
    return f'"{short}" OR "{code}" stock', [code, short.split()[0] if short else code]


# ── 공시: DART ──────────────────────────────────────────
def _cache(name: str):
    return config.NEWHIGH_ROOT / name


def dart_corp_map(key: str) -> dict[str, str]:
    """종목코드 → DART 고유번호. 한 달에 한 번 받아서 캐시."""
    p = _cache("dart_corp.json")
    month = date.today().strftime("%Y-%m")
    if p.exists():
        d = json.loads(p.read_text())
        if d.get("month") == month and d.get("map"):
            return d["map"]
    r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        xml = z.read(z.namelist()[0])
    root = ET.fromstring(xml)
    m = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        if sc:
            m[sc] = (el.findtext("corp_code") or "").strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"month": month, "map": m}))
    return m


def dart_filings(key: str, corp_code: str, day: date, n: int = 4) -> list[dict]:
    r = requests.get("https://opendart.fss.or.kr/api/list.json", timeout=20, params={
        "crtfc_key": key, "corp_code": corp_code, "page_count": 20,
        "bgn_de": (day - timedelta(days=NEWS_DAYS + 2)).strftime("%Y%m%d"), "end_de": day.strftime("%Y%m%d")})
    j = r.json()
    if j.get("status") not in ("000",):
        return []
    out = []
    for it in j.get("list", [])[:n]:
        nm = re.sub(r"\s+", " ", it.get("report_nm", "")).strip()
        d = it.get("rcept_dt", "")
        out.append({"t": nm, "u": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={it.get('rcept_no')}",
                    "d": f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d, "s": "DART"})
    return out


# ── 공시: SEC EDGAR ─────────────────────────────────────
def _sec_headers():
    ua = os.environ.get("SEC_USER_AGENT") or \
        f"sector-mood research bot (github.com/{os.environ.get('GITHUB_REPOSITORY', 'sector-mood')})"
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def sec_cik_map() -> dict[str, int]:
    p = _cache("sec_tickers.json")
    month = date.today().strftime("%Y-%m")
    if p.exists():
        d = json.loads(p.read_text())
        if d.get("month") == month and d.get("map"):
            return d["map"]
    r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=_sec_headers(), timeout=30)
    r.raise_for_status()
    m = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"month": month, "map": m}))
    return m


def sec_label(form: str, items: str) -> str:
    if form == "8-K" and items:
        names = [EIGHT_K[i.strip()] for i in items.split(",") if i.strip() in EIGHT_K]
        if names:
            return f"8-K: {' · '.join(dict.fromkeys(names))}"
    return form


def sec_filings(cik: int, day: date, n: int = 3) -> list[dict]:
    r = requests.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=_sec_headers(), timeout=20)
    r.raise_for_status()
    rec = r.json().get("filings", {}).get("recent", {})
    since = (day - timedelta(days=NEWS_DAYS + 2)).isoformat()
    out = []
    for i, form in enumerate(rec.get("form", [])):
        fd = rec["filingDate"][i]
        if fd < since:
            break
        if form not in SEC_FORMS:
            continue
        acc = rec["accessionNumber"][i].replace("-", "")
        doc = rec.get("primaryDocument", [""] * (i + 1))[i]
        items = rec.get("items", [""] * (i + 1))[i] if rec.get("items") else ""
        out.append({"t": sec_label(form, items), "d": fd, "s": "SEC",
                    "u": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"})
        if len(out) >= n:
            break
    return out


# ── 일본어 종목명 (뉴스 검색용) ─────────────────────────
def jp_names(codes: list[str]) -> dict[str, str]:
    from .universe import HEADERS
    try:
        r = requests.post("https://scanner.tradingview.com/japan/scan", timeout=30, headers=HEADERS, json={
            "markets": ["japan"], "columns": ["name", "description"],
            "filter": [{"left": "name", "operation": "in_range", "right": codes}],
            "range": [0, len(codes) + 10], "options": {"lang": "ja"}})
        r.raise_for_status()
        return {row["d"][0]: row["d"][1] for row in r.json().get("data", [])}
    except Exception as e:  # noqa: BLE001
        print(f"[enrich:jp] 일본어 이름 실패 → 영어 사용 ({e})")
        return {}


# ── 기록 읽기 ───────────────────────────────────────────
def read_records(mkt: str) -> list[dict]:
    d = config.NEWHIGH_ROOT / mkt
    rows = []
    for p in sorted(d.glob("*.csv"))[-3:]:
        with p.open(encoding="utf-8") as f:
            rows += list(csv.DictReader(f))
    return rows


def cumulative(records: list[dict], today: str, windows=(5, 20)) -> dict[int, dict[str, set]]:
    """기록일 기준 최근 N일(오늘 포함) 라벨별 고유 종목 집합."""
    days = sorted({r["date"] for r in records} | {today})
    days = [d for d in days if d <= today]
    out = {}
    for w in windows:
        keep = set(days[-w:])
        m: dict[str, set] = {}
        for r in records:
            if r["date"] in keep:
                labels = r.get('labels') or [r['label']]
                if isinstance(labels,str):
                    try: labels = json.loads(labels)
                    except ValueError: labels = [r['label']]
                for label in set(labels):
                    m.setdefault(label,set()).add(r['code'])
        out[w] = m
    return out


# ── 업종 흐름 (업종 심리 지도 history.json) ───────────────
def industry_context(mkt: str, industries: list[str]) -> dict | None:
    p = config.ROOT / "docs" / "data" / mkt / "history.json"
    if not p.exists() or not industries:
        return None
    H = json.loads(p.read_text())
    look = {}
    for g in H["groups"]["industry"]:
        look[g["key"]] = g
        look.setdefault(g["name"], g)
    top = max(set(industries), key=industries.count)
    g = look.get(top)
    if not g:
        return None
    i = len(H["weeks"]) - 1
    rc, x, y = g["rc"][i], g["x_cw"][i], g["y_cw"][i]
    quad = None
    if x is not None and y is not None:
        quad = QUAD["lead" if x >= 100 and y >= 100 else "weak" if x >= 100 else "imp" if y >= 100 else "lag"]
    up = 0
    for k in range(i, max(-1, i - 12), -1):
        if g["rc"][k] is not None and g["rc"][k] > 0:
            up += 1
        else:
            break
    return {"industry": g["name"], "week": H["weeks"][i], "rc": rc, "quad": quad, "up_weeks": up, "n": g["n"]}


def context_text(c: dict | None) -> str:
    if not c:
        return ""
    parts = [f"{c['industry']} 주간 {c['rc']:+.1f}%p" if c.get("rc") is not None else c["industry"]]
    if c.get("quad"):
        parts.append(f"로테이션 {c['quad']}")
    if c.get("up_weeks", 0) >= 2:
        parts.append(f"{c['up_weeks']}주 연속 시장 상회")
    return " · ".join(parts)


# ── 차트 이미지 ─────────────────────────────────────────
def _font():
    import matplotlib
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    for nm in ("NanumGothic", "Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Sans CJK SC", "Noto Sans KR"):
        if nm in have:
            matplotlib.rcParams["font.family"] = nm
            break
    matplotlib.rcParams["axes.unicode_minus"] = False


def chart_png(path: Path, items: list[dict], title: str):
    """items: [{name, change, df}] → 섹터 묶음 차트 (1년 일봉, 20·50·200일선, 직전 52주 고점선, 거래량)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _font()
    n = len(items)
    cols = 3 if n > 4 else 2 if n > 1 else 1
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(5.0 * cols, 2.9 * rows), squeeze=False)
    for ax in axes.flat:
        ax.set_visible(False)
    for ax, it in zip(axes.flat, items):
        ax.set_visible(True)
        df = it["df"]
        c = df["close"]
        ma = {k: c.rolling(k).mean() for k in (20, 50, 200)}
        prior = df["high"].shift(1).rolling(251, min_periods=120).max()
        s = slice(-252, None)
        x = np.arange(len(c.iloc[s]))
        ax.plot(x, c.iloc[s].values, color="#1d2321", lw=1.3, zorder=3)
        for k, col in ((20, "#d1344a"), (50, "#e0a53b"), (200, "#2f62c4")):
            ax.plot(x, ma[k].iloc[s].values, color=col, lw=0.9, alpha=0.9)
        p52 = prior.iloc[-1]
        if pd.notna(p52):
            ax.axhline(p52, color="#8b9491", lw=0.8, ls="--")
        ax.scatter([x[-1]], [c.iloc[-1]], color="#d1344a", s=22, zorder=4)
        v = df["volume"].iloc[s].values
        ax2 = ax.twinx()
        ax2.bar(x, v, color="#c9ced0", width=1.0, alpha=0.6)
        ax2.set_ylim(0, max(v.max(), 1) * 4)
        ax2.set_yticks([])
        ax.set_zorder(ax2.get_zorder() + 1)
        ax.patch.set_visible(False)
        idx = c.iloc[s].index
        ticks = [i for i in range(0, len(idx), max(1, len(idx) // 4))]
        ax.set_xticks(ticks)
        ax.set_xticklabels([idx[i].strftime("%y.%m") for i in ticks], fontsize=8)
        ax.tick_params(axis="y", labelsize=8)
        ax.grid(alpha=0.25)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.set_title(f"{it['name']}  {it['change']:+.1f}%", fontsize=11, loc="left", fontweight="bold")
    fig.suptitle(title + "   — 종가 · 20/50/200일선(빨강/주황/파랑) · 점선=직전 52주 고점", fontsize=10.5,
                 x=0.01, ha="left", color="#5d6663")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def series_for_site(df: pd.DataFrame) -> dict:
    """사이트 차트용 압축 시계열: 최근 452거래일 종가를 2일 간격, 마지막 종가 대비 ×1000 정수."""
    c = df["close"].iloc[-452:]
    last = float(c.iloc[-1])
    pts = c.iloc[::-1].iloc[::2].iloc[::-1]          # 마지막 날이 반드시 포함되도록 끝에서부터 2일 간격
    prior = df["high"].shift(1).rolling(251, min_periods=120).max().iloc[-1]
    return {"c": [int(round(v / last * 1000)) for v in pts.values], "step": 2, "last": last,
            "p52": None if pd.isna(prior) else int(round(prior / last * 1000)),
            "from": pts.index[0].strftime("%Y-%m-%d")}


# ── 메인 ────────────────────────────────────────────────
def run(mkt: str, day: date, ath: list[dict], w52: list[dict], label_of, display_name,
        synthetic: bool = False, out_png: Path | None = None, write_site: bool = True) -> dict:
    """반환: {"clusters": [...], "notes": {label: [html 줄]}, "charts": [(png, caption)], "url": str|None}"""
    hits = [("ATH", r) for r in ath] + [("52W", r) for r in w52]
    today = day.isoformat()
    lab = {str(r.get("name")): label_of(r) for _, r in hits}
    from .taxonomy import profile, labels_from_profile
    lab_multi = {str(r.get('name')): labels_from_profile(profile(r,mkt)) for _,r in hits}
    rowmap = {str(r.get("name")): r for _, r in hits}
    by_label: dict[str, list[dict]] = {}
    for _, r in hits:
        for label in lab_multi[str(r.get('name'))]:
            by_label.setdefault(label, []).append(r)

    # 군집·누적
    past = [r for r in read_records(mkt) if r["date"] != today]
    now = [{"date": today, "code": c, "label": l, "labels":lab_multi[c]} for c, l in lab.items()]
    cum = cumulative([r for r in past if r.get("classification_version") == "business-v1"] + now, today)
    clusters = []
    for l, rs in by_label.items():
        n5, n20 = len(cum[5].get(l, ())), len(cum[20].get(l, ()))
        if len(rs) >= CLUSTER_MIN or n5 >= CLUSTER_MIN * 2:
            clusters.append({"label": l, "n": len(rs), "n5": n5, "n20": n20,
                             "codes": [str(r.get("name")) for r in sorted(rs, key=lambda x: -x["change"])]})
    clusters.sort(key=lambda c: (-c["n"], -c["n5"]))
    for c in clusters:
        c["context"] = industry_context(mkt, [str(r.get("industry") or "") for r in by_label[c["label"]]])

    # 가격 (오늘 신고가 + 사후 성과용 과거 기록)
    past_days = sorted({r["date"] for r in past})[-FOLLOW_DAYS:]
    follow_recs = [r for r in past if r["date"] in set(past_days)]
    follow_codes = list(dict.fromkeys(r["code"] for r in sorted(follow_recs, key=lambda r: r["date"], reverse=True)))
    codes = list(lab) + [c for c in follow_codes if c not in lab][:FOLLOW_MAX]
    if synthetic:
        prices = _synthetic_prices(codes, day)
        last_rec = {r["code"]: float(r["close"]) for r in sorted(follow_recs, key=lambda r: r["date"])}
        for c, df in prices.items():                         # 합성 가격 수준을 실제 종가 수준에 맞춤
            tgt = rowmap[c].get("close") if c in rowmap else last_rec.get(c, 0) * 1.03
            if tgt:
                df[["close", "high"]] *= tgt / df["close"].iloc[-1]
    else:
        try:
            prices = fetch_history(mkt, codes)
        except Exception as e:  # noqa: BLE001
            print(f"[enrich:{mkt}] 가격 수집 실패 ({e})")
            prices = {}

    # 재료 (공시 우선, 뉴스) — 군집 종목 먼저, 그다음 상승률 순
    order = [c for cl in clusters for c in cl["codes"]]
    order += [str(r.get("name")) for _, r in sorted(hits, key=lambda x: -x[1]["change"]) if str(r.get("name")) not in order]
    order = order[:ENRICH_MAX]
    news, filings = {}, {}
    if synthetic:
        for c in order:
            news[c] = [{"t": f"{display_name(rowmap[c])} 관련 테스트 기사", "u": "https://example.com", "s": "테스트",
                        "d": today}]
            if mkt == "kr" and zlib.crc32(c.encode()) % 3 == 0:
                filings[c] = [{"t": "단일판매ㆍ공급계약체결", "u": "https://dart.fss.or.kr", "d": today, "s": "DART"}]
    else:
        news, filings = _collect_materials(mkt, day, order, rowmap, display_name)

    # 군집별 재료 줄 (텔레그램)
    notes = {}
    for cl in clusters:
        fl = [("공시", display_name(rowmap[c]), f) for c in cl["codes"] for f in filings.get(c, [])[:1]]
        nw = [("뉴스", display_name(rowmap[c]), x) for c in cl["codes"] for x in news.get(c, [])[:1]]
        items = fl[:1] + nw[:1]                                 # 공시 1 + 뉴스 1 우선, 모자라면 채움
        items += [x for x in fl[1:] + nw[1:]][: max(0, 2 - len(items))]
        lines = []
        ctx = context_text(cl.get("context"))
        if ctx:
            lines.append(f"  └ 업종: {_esc(ctx)}")
        for kind, nm, x in items[:2]:
            t = x["t"] if len(x["t"]) <= 42 else x["t"][:41] + "…"
            lines.append(f'  └ {kind} {_esc(nm)}: <a href="{_esc(x["u"])}">{_esc(t)}</a>')
        if not items:
            lines.append("  └ 재료 미확인 (최근 공시·뉴스 없음 → 수급·순환매 가능성)")
        notes[cl["label"]] = lines

    # 차트 이미지 (군집 우선, 없으면 상승률 상위)
    charts = []
    groups = [(cl["label"], cl["codes"]) for cl in clusters][:CHART_MAX]
    if not groups and hits:
        top = [str(r.get("name")) for _, r in sorted(hits, key=lambda x: -x[1]["change"])][:CHART_PER_IMG]
        groups = [("상승률 상위", top)]
    out_png = out_png or (config.NEWHIGH_ROOT / mkt / "_charts")
    m = config.market(mkt)
    for i, (l, cs) in enumerate(groups):
        its = [{"name": display_name(rowmap[c]), "change": rowmap[c]["change"], "df": prices[c]}
               for c in cs if c in prices][:CHART_PER_IMG]
        if not its:
            continue
        p = Path(out_png) / f"{today}_{i}.png"
        try:
            chart_png(p, its, f"{m['label']} · ({l}) {len(cs)}종목 · {today}")
            charts.append((p, f"{m['flag']} {m['label']} 신고가 · ({l}) {len(cs)}종목 · 1년 일봉"))
        except Exception as e:  # noqa: BLE001
            print(f"[enrich:{mkt}] 차트 실패 ({l}): {e}")

    # 사후 성과
    follow = []
    for r in follow_recs:
        df = prices.get(r["code"])
        if df is None:
            continue
        try:
            base = float(r["close"])
            last = float(df["close"].iloc[-1])
        except (TypeError, ValueError):
            continue
        if base > 0:
            nd = int((df.index > pd.Timestamp(r["date"])).sum())
            follow.append({"date": r["date"], "code": r["code"], "name": r["name"], "label": r["label"],
                           "kind": r["kind"], "ret": round((last / base - 1) * 100, 2), "days": nd,
                           "labels": labels_from_profile(profile({"name":r["code"]},mkt))})
    perf = {}
    for r in follow:
        for label in r.get('labels',[r['label']]):
            perf.setdefault(label, []).append(r['ret'])
    perf = {k: {"n": len(v), "med": round(statistics.median(v), 2), "hit": round(sum(x > 0 for x in v) / len(v) * 100)}
            for k, v in perf.items() if len(v) >= 2}

    if write_site:
        _write_site(mkt, day, hits, lab, rowmap, prices, news, filings, clusters, cum, follow, perf, display_name)

    url = None
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        o, n_ = repo.split("/")
        url = f"https://{o}.github.io/{n_}/#{mkt}/newhigh/{today}"
    return {"clusters": clusters, "notes": notes, "charts": charts, "url": url}


def _esc(s):
    import html
    return html.escape(str(s), quote=True)


def _collect_materials(mkt, day, order, rowmap, display_name):
    news, filings = {}, {}
    dart_key = os.environ.get("DART_API_KEY")
    corp = {}
    if mkt == "kr" and dart_key:
        try:
            corp = dart_corp_map(dart_key)
        except Exception as e:  # noqa: BLE001
            print(f"[enrich:kr] DART 고유번호 실패 ({e})")
    cik = {}
    if mkt == "us":
        try:
            cik = sec_cik_map()
        except Exception as e:  # noqa: BLE001
            print(f"[enrich:us] SEC 티커 목록 실패 ({e})")
    ja = jp_names(order) if mkt == "jp" and order else {}
    fails = 0
    for c in order:
        r = rowmap[c]
        try:
            if mkt == "kr" and c in corp:
                filings[c] = dart_filings(dart_key, corp[c], day)
            elif mkt == "us" and c.upper() in cik:
                filings[c] = sec_filings(cik[c.upper()], day)
                time.sleep(0.15)
        except Exception as e:  # noqa: BLE001
            print(f"[enrich:{mkt}] 공시 실패 {c}: {e}")
        try:
            name = display_name(r) if mkt != "us" else str(r.get("description") or c)
            q, must = news_query(mkt, c, name, ja.get(c))
            news[c] = google_news(mkt, q, must)
            time.sleep(0.4)
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"[enrich:{mkt}] 뉴스 실패 {c}: {e}")
            if fails >= 5:
                print(f"[enrich:{mkt}] 뉴스 연속 실패 → 남은 종목 뉴스 생략")
                break
    print(f"[enrich:{mkt}] 뉴스 {sum(1 for v in news.values() if v)} · 공시 {sum(1 for v in filings.values() if v)}종목")
    return news, filings


def _write_site(mkt, day, hits, lab, rowmap, prices, news, filings, clusters, cum, follow, perf, display_name):
    base = config.ROOT / "docs" / "data" / mkt / "newhigh"
    base.mkdir(parents=True, exist_ok=True)
    today = day.isoformat()
    stocks = []
    from .taxonomy import profile, reviewed_rows, labels_from_profile
    from .newhigh import load_labels
    reviewed, legacy = reviewed_rows(), load_labels()
    for kind, r in hits:
        c = str(r.get("name"))
        df = prices.get(c)
        stocks.append({
            "code": c, "name": display_name(r), "full": r.get("description"), "label": lab[c], "kind": kind,
            "change": round(r["change"], 2), "rank": r.get("rank"), "close": r.get("close"),
            "mcap": None if r.get("market_cap_basic") is None else round(r["market_cap_basic"] / 1e8),
            "industry": r.get("industry"), "exchange": r.get("exchange"),
            "classification": profile(r, mkt, legacy, reviewed),
            "labels": labels_from_profile(profile(r, mkt, legacy, reviewed)),
            "chart": series_for_site(df) if df is not None and len(df) >= 30 else None,
            "news": news.get(c, []), "filings": filings.get(c, []),
        })
    day_doc = {"day": today, "market": mkt, "stocks": stocks,
               "clusters": [{k: v for k, v in cl.items()} for cl in clusters],
               "follow": sorted(follow, key=lambda x: -x["ret"])[:300], "perf": perf,
               "cum5": {k: len(v) for k, v in cum[5].items()}, "cum20": {k: len(v) for k, v in cum[20].items()}}
    (base / f"{today}.json").write_text(json.dumps(day_doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False))

    ip = base / "index.json"
    idx = json.loads(ip.read_text()) if ip.exists() else {"days": [], "counts": {}}
    idx["counts"][today] = {}
    for c, l in lab.items():
        for label in labels_from_profile(profile(rowmap[c],mkt,legacy,reviewed)):
            idx['counts'][today][label] = idx['counts'][today].get(label,0) + 1
    files = sorted(p.stem for p in base.glob("20*.json"))
    for old in files[:-SITE_KEEP_DAYS]:
        (base / f"{old}.json").unlink()
    idx["days"] = sorted(p.stem for p in base.glob("20*.json"))
    idx["counts"] = {d: v for d, v in sorted(idx["counts"].items())[-120:]}
    idx["generated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    ip.write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")))
    print(f"[enrich:{mkt}] 사이트 파일 {today}.json ({len(stocks)}종목, 군집 {len(clusters)})")


def _synthetic_prices(codes: list[str], day: date) -> dict[str, pd.DataFrame]:
    out = {}
    idx = pd.bdate_range(end=pd.Timestamp(day), periods=480)
    for i, c in enumerate(codes):
        rng = np.random.default_rng(zlib.crc32(c.encode()))
        r = rng.normal(0.0008, 0.02, len(idx))
        r[-1] = abs(r[-1]) + 0.06
        close = 10000 * np.cumprod(1 + r)
        close[-1] = max(close[-1], close[:-1].max() * 1.01)
        high = close * (1 + np.abs(rng.normal(0, 0.008, len(idx))))
        vol = rng.lognormal(12, 0.5, len(idx))
        vol[-1] *= 3
        out[c] = pd.DataFrame({"close": close, "high": high, "volume": vol}, index=idx)
    return out
