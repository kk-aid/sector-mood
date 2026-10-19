"""Daily supplemental screens. Custom RS, not an official IBD/Kkangto rating.

Benchmarks: KOSPI/KOSDAQ by successfully resolved Yahoo listing; US S&P500;
Japan TOPIX ETF 1306 proxy (explicitly labelled). No forward fill of prices.
"""
from __future__ import annotations

import html
import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config

BENCH = {"kospi": ("KOSPI", "^KS11"), "kosdaq": ("KOSDAQ", "^KQ11"),
         "us": ("S&P500", "^GSPC"), "jp": ("TOPIX ETF 대용", "1306.T")}


def download(rows, mkt):
    """Resolve KR listing via actual data; never assume every KRX stock is KOSPI."""
    import yfinance as yf
    frames = {}
    resolved = {}
    def batch(mapping):
        for start in range(0, len(mapping), 100):
            symbols = list(mapping)[start:start + 100]
            try:
                raw = yf.download(symbols, period="2y", interval="1d", auto_adjust=False,
                                  group_by="column", threads=True, progress=False, timeout=20)
            except Exception as ex:
                print(f"[strength:{mkt}] 가격 청크 실패 ({len(symbols)}종목): {type(ex).__name__}")
                continue
            if raw is None or raw.empty:
                continue
            if not isinstance(raw.columns, pd.MultiIndex):
                raw.columns = pd.MultiIndex.from_product([raw.columns, symbols])
            for sym in symbols:
                try:
                    f = pd.DataFrame({k: raw[v][sym] for k, v in
                        {"adj": "Adj Close", "open": "Open", "close": "Close", "high": "High", "low": "Low", "volume": "Volume"}.items()})
                except KeyError:
                    continue
                f.index = pd.to_datetime(f.index).tz_localize(None).normalize()
                f = f[~f.index.duplicated(keep="last")].sort_index()
                now = datetime.now(ZoneInfo(config.market(mkt)["tz"]))
                if (now.hour, now.minute) < config.market(mkt)["close"]:
                    f = f[f.index < pd.Timestamp(now.date())]
                f = f.dropna(subset=["adj", "close"])
                if not f.empty:
                    key = mapping[sym]
                    frames[key], resolved[key] = f, sym
    mapping = {}
    for r in rows:
        code = str(r["name"])
        sym = r.get("yf") or (code + ".KS" if mkt == "kr" else code + ".T" if mkt == "jp" else code.replace(".", "-").replace("/", "-"))
        mapping[sym] = code
    batch(mapping)
    if mkt == "kr":
        batch({str(r["name"]) + ".KQ": str(r["name"]) for r in rows if str(r["name"]) not in frames and not r.get("yf")})
    keys = ("kospi", "kosdaq") if mkt == "kr" else (mkt,)
    batch({BENCH[k][1]: "@" + k for k in keys})
    return frames, resolved


def percentile(values):
    """Tie-aware 1..99; tied equal population scores are neutral (50)."""
    if len(values) < 2:
        return {k: None for k in values}
    s = pd.Series(values, dtype=float)
    ranks = (s.rank(method="average") - 1) / (len(s) - 1)
    return {k: int(math.floor(v * 98 + 1 + 0.5)) for k, v in ranks.items()}


def metrics(f, benchmark):
    # Benchmark calendar is authoritative; missing stock sessions stay missing.
    b = benchmark["adj"].where(benchmark["adj"] > 0)
    p = f["adj"].where(f["adj"] > 0).reindex(b.index)
    if len(b) < 2 or pd.isna(p.iloc[-1]) or pd.isna(b.iloc[-1]):
        return None
    ratio = p / b
    out = {}
    for label, n in (("1m", 21), ("3m", 63), ("6m", 126)):
        window = ratio.iloc[-n-1:]
        out["excess_" + label] = float((window.iloc[-1] / window.iloc[0] - 1) * 100) if len(window) == n+1 and pd.notna(window.iloc[0]) and pd.notna(window.iloc[-1]) else None
    window = ratio.iloc[-253:]
    out["score"] = (sum(w * (window.iloc[-1-a] / window.iloc[-1-z] - 1)
        for w, a, z in ((.4, 0, 63), (.2, 63, 126), (.2, 126, 189), (.2, 189, 252)))
        if len(window) == 253 and window.iloc[[0, 63, 126, 189, 252]].notna().all() else None)
    out["line_nh"] = bool(len(ratio) >= 63 and ratio.iloc[-63:].notna().all() and ratio.iloc[-1] >= ratio.iloc[-63:].max())
    # MTT uses consistently adjusted OHLC (incl. split adjustment).
    adj = f["adj"].reindex(b.index)
    factor = (f["adj"] / f["close"]).reindex(b.index)
    hi, lo = (f[k].reindex(b.index) * factor for k in ("high", "low"))
    ma50, ma150, ma200 = (adj.rolling(n).mean() for n in (50, 150, 200))
    p0 = adj.iloc[-1]
    out["mtt_price"] = None
    if len(adj) >= 253 and adj.iloc[-253:].notna().all() and hi.iloc[-252:].notna().all() and lo.iloc[-252:].notna().all():
        out["mtt_price"] = sum(map(bool, (p0 > ma150.iloc[-1] and p0 > ma200.iloc[-1],
            ma150.iloc[-1] > ma200.iloc[-1], ma200.iloc[-1] > ma200.iloc[-23],
            ma50.iloc[-1] > ma150.iloc[-1] and ma50.iloc[-1] > ma200.iloc[-1],
            p0 > ma50.iloc[-1], p0 >= lo.iloc[-252:].min() * 1.3, p0 >= hi.iloc[-252:].max() * .75)))
    # Turnover proxy = unadjusted close * volume; today's value excluded from reference.
    tv = (f["close"] * f["volume"]).reindex(b.index)
    past = tv.iloc[-21:-1]
    valid = len(past) == 20 and past.notna().all() and (past > 0).all() and pd.notna(tv.iloc[-1])
    out["turnover_multiple"] = float(tv.iloc[-1] / past.mean()) if valid else None
    out["turnover_peak"] = bool(valid and tv.iloc[-1] > past.max())
    out["high52"] = bool(len(hi) >= 253 and hi.iloc[-253:].notna().all() and hi.iloc[-1] >= hi.iloc[-253:-1].max())
    out["flip"] = support_flip(adj, hi, lo)
    return out


def support_flip(close, high, low):
    """Confirmed historical pivot, subsequent breakout, today's first retest hold.

    5 bars each side confirm pivot; age 20..126 sessions. Breakout must occur
    after confirmation, before today. Today touches +/-3%, closes above pivot;
    all intervening closes hold it. No use of future bars or breakout-day alert.
    """
    if len(close) < 40 or close.iloc[-40:].isna().any():
        return None
    end = len(close) - 1
    for i in range(end - 20, max(4, end - 126), -1):
        level = high.iloc[i]
        around = high.iloc[i-5:i+6]
        if pd.isna(level) or len(around) != 11 or around.isna().any() or level <= 0 or level != around.max():
            continue
        later = close.iloc[i+6:end]
        crossings = later[(later > level * 1.005) & (close.shift(1).reindex(later.index) <= level * 1.005)]
        if crossings.empty:
            continue
        bi = close.index.get_loc(crossings.index[-1])
        if end - bi > 20 or close.iloc[bi:end].isna().any() or (close.iloc[bi:end] < level).any():
            continue
        if not (level * .97 <= low.iloc[-1] <= level * 1.03 and close.iloc[-1] >= level and close.iloc[-1] > close.iloc[-2]):
            continue
        if (low.iloc[bi+1:end] <= level * 1.03).any():
            continue
        return {"level": float(level), "gap": float((close.iloc[-1] / level - 1) * 100)}
    return None


def calculate(rows, mkt, frames, resolved, etf=False):
    results = {}
    for r in rows:
        code = str(r["name"])
        key = ("kosdaq" if resolved.get(code, "").endswith(".KQ") else "kospi") if mkt == "kr" else mkt
        if code not in frames or "@" + key not in frames:
            continue
        f, b = frames[code], frames["@" + key]
        x = metrics(f, b)
        if x is not None:
            x.update(benchmark=BENCH[key][0], group=key, asset="ETF" if etf else "주식", day=b.index[-1].date().isoformat())
            results[code] = x
    for group in {v["group"] for v in results.values()}:
        members = {k: v for k, v in results.items() if v["group"] == group}
        for field, name in (("score", "rs"), ("excess_1m", "rs1"), ("excess_3m", "rs3"), ("excess_6m", "rs6")):
            scores = {k: v[field] for k, v in members.items() if v[field] is not None and np.isfinite(v[field])}
            ranks = percentile(scores)
            for k, v in members.items():
                v[name], v[name + "_n"] = ranks.get(k), len(scores)
        for v in members.values():
            v["mtt"] = v["mtt_price"] + int(v["rs"] >= 70) if v["mtt_price"] is not None and v["rs"] is not None else None
            v["flow"] = "가속 ▲" if v["rs1"] is not None and v["rs"] is not None and v["rs1"] > v["rs"] else "둔화 ▼" if v["rs1"] is not None and v["rs"] is not None and v["rs1"] < v["rs"] else "동일" if v["rs1"] is not None and v["rs"] is not None else "산출 불가"
    return results


def brief(x):
    score = "–" if x["rs"] is None else str(x["rs"])
    parts = [f"RS {score}"]
    parts.append("1/3/6M " + "/".join("–" if x[k] is None else str(x[k]) for k in ("rs1", "rs3", "rs6")))
    if x["excess_1m"] is not None:
        parts.append(f"1M 시장비 +{x['excess_1m']:.1f}%" if x["excess_1m"] >= 0 else f"1M 시장비 {x['excess_1m']:.1f}%")
    if x["turnover_multiple"] is not None:
        parts.append(f"대금 {x['turnover_multiple']:.1f}배")
    if x["mtt"] is not None:
        parts.append(f"MTT {x['mtt']}/8")
    if x["line_nh"]:
        parts.append("RS선 63일 신고가")
    parts += [x["flow"], x["benchmark"]]
    return " · ".join(parts)


def message(rows, results, display_name, mkt, etf=False):
    valid = [(r, results[str(r["name"])]) for r in rows if str(r["name"]) in results]
    lines = ["", "<b>📊 " + ("주요 ETF" if etf else "주식") + " 추가 스크리닝</b>",
             "자체 RS · " + ("등록 ETF" if etf else "필터 통과·수집 성공 종목") + " 내 시장별 순위 (IBD 공식 아님)",
             f"대상 {len(rows)} · 가격/지수 정렬 성공 {len(results)} · 신규상장은 가능한 단기 점수만 표시"]
    if etf:
        lines.append("ETF는 주식과 별도 순위 · 상장국 지수 대비 (해외자산/채권/금도 동일 기준)")
    for group in sorted({v["group"] for v in results.values()}):
        x = next(v for v in results.values() if v["group"] == group)
        lines.append(f"{x['benchmark']}: 종합 {x['rs_n']}종목 · 기준 {x['day']}")
    sections = [
        ("💪 상대강도 상위", sorted([(r, x) for r, x in valid if x["rs"] is not None and x["rs"] >= 90 and (x["excess_1m"] or 0) > 0], key=lambda z: (-z[1]["rs"], -(z[1]["excess_1m"] or 0)))),
        ("💰 거래대금 급증", sorted([(r, x) for r, x in valid if x["turnover_multiple"] is not None and (x["turnover_multiple"] >= 2 or x["turnover_peak"])], key=lambda z: -z[1]["turnover_multiple"])),
        ("🔄 R/S Flip · 저항→지지 재시험", [(r, x) for r, x in valid if x["flip"]])]
    if etf:
        sections.insert(0, ("📈 ETF 52주 신고가", [(r, x) for r, x in valid if x["high52"] and (r.get("change") or 0) > 0 and (r.get("close") or 0) > (r.get("open") or float("inf"))]))
    if not etf:
        from .newhigh import _hit
        hits = [(r, x) for r, x in valid if (r.get("change") or 0) > 0
                and (r.get("close") or 0) > (r.get("open") or float("inf"))
                and (_hit(r.get("high"), r.get("High.All")) or _hit(r.get("high"), r.get("price_52_week_high")))]
        sections.insert(0, ("🏆 신고가 종목 RS 보강", sorted(hits, key=lambda z: -(z[1]["rs"] or 0))))
    for title, selected in sections:
        lines += ["", f"<b>{title} {len(selected)}종목</b>"]
        if not selected:
            lines.append("조건 충족 없음")
        for r, x in selected[:config.STRENGTH_TOP]:
            lines.append(f"{html.escape(display_name(r, mkt))} {(r.get('change') or 0):+.1f}%")
            lines.append("  └ " + brief(x))
            if x["flip"]:
                lines.append(f"  └ 이전 저항(수정가격) {x['flip']['level']:,.2f} · 대비 {x['flip']['gap']:+.1f}%")
        if len(selected) > config.STRENGTH_TOP:
            lines.append(f"상위 {config.STRENGTH_TOP}종목 표시")
    lines += ["", "대금=종가×거래량 추정 · 직전 20일 평균비 2배↑ 또는 최고치 경신"]
    return "\n".join(lines)


def run(rows, mkt, display_name, write=True, etf=False):
    frames, resolved = download(rows, mkt)
    if etf:
        for r in rows:
            f = frames.get(str(r["name"]))
            if f is not None and len(f) > 1:
                r.update(change=float((f["adj"].iloc[-1] / f["adj"].iloc[-2] - 1) * 100),
                         close=float(f["close"].iloc[-1]), open=float(f["open"].iloc[-1]))
    results = calculate(rows, mkt, frames, resolved, etf=etf)
    if not results:
        raise RuntimeError("유효 가격·벤치마크 없음")
    if write:
        p = config.DATA_ROOT / mkt / ("strength_etf.json" if etf else "strength.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"method": "quarter-relative-40-20-20-20-v1", "scanned": len(rows),
            "scope": "filtered scanner universe, successful price coverage; rankings by benchmark", "stocks": results}, ensure_ascii=False, allow_nan=False))
    return results, message(rows, results, display_name, mkt, etf=etf)


def main():
    import argparse
    import hashlib
    import os
    from .newhigh import scan, _eligible, display_name, split_message
    from .notify import send
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", choices=list(config.MARKETS), required=True)
    ap.add_argument("--dry-run", action="store_true", help="전송·기록 없음")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not a.dry_run and not all(os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")):
        raise RuntimeError("추가 알림에 필요한 텔레그램 설정 없음")
    rows = [r for r in scan(a.market, rising_only=False) if _eligible(r)]
    if not rows:
        raise RuntimeError("RS 비교 종목 없음")
    # Stable scan snapshot enables holiday dedup without downloading thousands again.
    snapshot = sorted((str(r["name"]), r.get("close"), r.get("change")) for r in rows)
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    state = config.NEWHIGH_ROOT / a.market / "strength_last.json"
    # ETFs are also checked on stock holidays (e.g. ETFs tracking overseas assets).
    all_results, texts = {}, []
    last = json.loads(state.read_text()) if state.exists() else {}
    if a.force or a.dry_run or last.get("stocks") != fingerprint:
        results, text = run(rows, a.market, display_name, write=not a.dry_run)
        all_results["stocks"] = fingerprint
        texts.append(text)
    else:
        all_results["stocks"] = fingerprint
        print("[strength] 주식 직전 결과 동일 → 전송 생략")
    etfs = [{"name": sym, "description": name, "yf": sym} for name, sym in config.STRENGTH_ETFS[a.market]]
    results, text = run(etfs, a.market, lambda r, m: r["description"], write=not a.dry_run, etf=True)
    # Include actual last closes, dates and full metrics to detect ETF-only changes.
    etf_sig = hashlib.sha256(json.dumps({"metrics": results, "quotes": etfs}, sort_keys=True).encode()).hexdigest()
    all_results["etfs"] = etf_sig
    if a.force or a.dry_run or last.get("etfs") != etf_sig:
        texts.append(text)
    else:
        print("[strength] ETF 직전 결과 동일 → 전송 생략")
    for text in texts:
        for part in split_message(text):
            print(part) if a.dry_run else send(part)
    if not a.dry_run:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(all_results))


if __name__ == "__main__":
    main()
