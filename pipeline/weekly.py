"""숫자로 본 한 주: 미국·한국·일본 주간 요약 → docs/data/weekly/<월요일>.json

  python -m pipeline.weekly              # 최근 WEEKLY_REBUILD 주 다시 만들기 (없으면 전체 이력 백필)
  python -m pipeline.weekly --all        # 모든 주 다시 만들기
  python -m pipeline.weekly --synthetic  # 지수·ETF 가격을 합성으로 (네트워크 없이 테스트)

입력: 각 시장 docs/data/<시장>/weeks/<월요일>.json (업종 심리 지도 계산 결과) + 실제 지수·ETF 일봉(yfinance)
문장(notes·headline)은 숫자에서 규칙으로 만든 것이며 해석·전망은 넣지 않음.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import zlib
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config

OUT = config.DATA_ROOT / "weekly"
SHORT = {"us": "미", "jp": "일", "kr": "한"}
ORDER = ["kr", "jp", "us"]            # 화면·문장 순서 (원본 화면과 같게 한국 먼저)


def _r(x, nd=2):
    try:
        return None if x is None or not np.isfinite(x) else round(float(x), nd)
    except TypeError:
        return None


# ── 실제 지수·ETF 가격 ─────────────────────────────────
def fetch_closes(symbols: list[str], period: str = "1y") -> dict[str, pd.Series]:
    import yfinance as yf
    out = {}
    for i in range(0, len(symbols), 60):
        part = symbols[i:i + 60]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(part, period=period, interval="1d", auto_adjust=True,
                                 group_by="column", threads=True, progress=False)
                if df is not None and not df.empty:
                    break
            except Exception as e:  # noqa: BLE001
                print(f"[weekly] 가격 재시도 {attempt + 1}: {e}")
            time.sleep(3 * (attempt + 1))
        if df is None or df.empty:
            continue
        close = df["Close"]
        if isinstance(close, pd.Series):
            close = close.to_frame(part[0])
        for s in part:
            if s in close and close[s].notna().sum() > 5:
                c = close[s].dropna()
                c.index = pd.to_datetime(c.index).tz_localize(None).normalize()
                out[s] = c
    print(f"[weekly] 지수·ETF {len(out)}/{len(symbols)}개")
    return out


def synthetic_closes(symbols: list[str], end: str) -> dict[str, pd.Series]:
    idx = pd.bdate_range(end=end, periods=260)
    out = {}
    for s in symbols:
        rng = np.random.default_rng(zlib.crc32(s.encode()))
        out[s] = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.012, len(idx))), index=idx)
    return out


def week_perf(c: pd.Series | None, days: list[str]) -> dict | None:
    """주간 수익률과 요일별 수익률 (%). 전주 마지막 종가 기준."""
    if c is None or not days:
        return None
    d0, d1 = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    prev = c[c.index < d0]
    cur = c[(c.index >= d0) & (c.index <= d1)]
    if prev.empty or cur.empty:
        return None
    base = float(prev.iloc[-1])
    daily, last = {}, base
    for d in days:
        v = cur.get(pd.Timestamp(d))
        if v is not None and np.isfinite(v):
            daily[d] = _r((v / last - 1) * 100)
            last = float(v)
    return {"week": _r((float(cur.iloc[-1]) / base - 1) * 100), "days": daily}


# ── 시장별 요약 ─────────────────────────────────────────
def _load_week(mkt: str, week: str) -> dict | None:
    p = config.DATA_ROOT / mkt / "weeks" / f"{week}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _ind_name(g: dict) -> str:
    return config.INDUSTRY_KO.get(g["key"], g.get("name") or g["key"])


QUAD = {"lead": "선도", "weak": "약화", "lag": "소외", "imp": "개선"}


def _quad(x, y):
    if x is None or y is None:
        return None
    return "lead" if x >= 100 and y >= 100 else "weak" if x >= 100 else "imp" if y >= 100 else "lag"


def _json(p):
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except (OSError, ValueError):
        return None


def contributions(W: dict, mkt: str) -> dict:
    """주간 시총가중 등락의 종목·섹터별 기여(%p). 가중치 = 주 시작 시총 비중 (보유 기준 근사)."""
    cols = {c: i for i, c in enumerate(W["stocks"]["cols"])}
    secs = W["stocks"]["sectors"]
    items = []
    for r in W["stocks"]["rows"]:
        mc, dm, wk = r[cols["mcap"]], r[cols["dmcap"]], r[cols["week"]]
        if mc is None or dm is None or wk is None or mc - dm <= 0:
            continue
        items.append((r, mc - dm, wk))
    tot = sum(x[1] for x in items)
    if not tot:
        return {}
    ko = getattr(config, "INDUSTRY_KO", {})
    rows, by_sec = [], {}
    for r, start, wk in items:
        c = start / tot * wk
        name = str(r[cols["name"]]).removesuffix("보통주").strip() if mkt == "kr" else r[cols["name"]]
        ind = r[cols["industry"]]
        rows.append({"code": r[cols["ticker"]], "name": name, "ind": ko.get(ind, ind), "week": wk,
                     "w": round(start / tot * 100, 2), "c": round(c, 3)})
        sk = secs[r[cols["sector"]]]
        by_sec[sk] = by_sec.get(sk, 0) + c
    total = sum(x["c"] for x in rows)
    rows.sort(key=lambda x: x["c"])
    neg = [x for x in rows if x["c"] < 0][:10]
    pos = [x for x in rows[::-1] if x["c"] > 0][:10]
    sec = sorted(({"name": config.SECTOR_KO.get(k, k), "c": round(v, 2)} for k, v in by_sec.items()), key=lambda x: x["c"])
    return {"total": round(total, 2), "down": neg, "up": pos,
            "top5_down": round(sum(x["c"] for x in neg[:5]), 2), "top5_up": round(sum(x["c"] for x in pos[:5]), 2),
            "sectors": sec}


def breadth(mkt: str, W: dict) -> dict:
    """50·200일선 위 비율(전주 대비), 주간 신고가−신저가, 거래대금 쏠림, 시장 거래대금 배수."""
    out = {"conc": (W.get("size") or {}).get("conc", {}).get("week"), "tv": W["market"]["week"].get("tv")}
    T = _json(config.DATA_ROOT / mkt / "trend.json")
    if T and W["week"] in T["history"]["weeks"]:
        H, i = T["history"], T["history"]["weeks"].index(W["week"])
        m = H["market"]
        out.update({"a50": m["a50"][i], "a50_prev": m["a50"][i - 1] if i else None, "a200": m["a200"][i],
                    "s2": m["s2"][i], "nhl": m["nhl"][i]})
    return out


def persistence(mkt: str, W: dict, prevW: dict | None) -> dict | None:
    """지난주 강·약 산업이 이번 주에 이어졌는지."""
    if not prevW:
        return None
    now = {g["key"]: g for g in W.get("industries", [])}
    pv = [g for g in prevW.get("industries", []) if g["n"] >= config.WEEKLY_INDUSTRY_MIN_N and g["week"]["rc"] is not None]
    pv.sort(key=lambda g: -g["week"]["rc"])
    k = config.WEEKLY_TOP

    def pack(g):
        n = now.get(g["key"])
        return {"name": _ind_name(g), "n": g["n"], "prev": g["week"]["rc"],
                "now": n["week"]["rc"] if n else None}
    st = [pack(g) for g in pv[:k] if g["week"]["rc"] > 0]
    wk = [pack(g) for g in pv[::-1][:k] if g["week"]["rc"] < 0]
    return {"prev_week": prevW["week"], "strong": st, "weak": wk,
            "keep_strong": sum(1 for x in st if x["now"] is not None and x["now"] > 0),
            "keep_weak": sum(1 for x in wk if x["now"] is not None and x["now"] < 0)}


def rotation_and_streak(mkt: str, week: str) -> dict:
    H = _json(config.DATA_ROOT / mkt / "history.json")
    if not H or week not in H["weeks"]:
        return {}
    i = H["weeks"].index(week)
    moves, streaks = {}, []
    for g in H["groups"]["industry"]:
        name = config.INDUSTRY_KO.get(g["key"], g["name"])
        if i > 0:
            q0, q1 = _quad(g["x_cw"][i - 1], g["y_cw"][i - 1]), _quad(g["x_cw"][i], g["y_cw"][i])
            if q0 and q1 and q0 != q1:
                moves.setdefault(f"{q0}>{q1}", []).append({"name": name, "n": g["n"], "rc": g["rc"][i],
                                                          "x": g["x_cw"][i], "y": g["y_cw"][i]})
        rc = g["rc"]
        if rc[i] is None or rc[i] == 0:
            continue
        sgn = 1 if rc[i] > 0 else -1
        k, cum = 0, 0.0
        while i - k >= 0 and rc[i - k] is not None and rc[i - k] * sgn > 0:
            cum += rc[i - k]
            k += 1
        if k >= 3:
            streaks.append({"name": name, "n": g["n"], "weeks": k, "dir": sgn, "cum": round(cum, 2), "now": rc[i]})
    order = ["imp>lead", "lag>imp", "weak>lead", "lead>weak", "weak>lag", "imp>lag", "lag>weak", "lead>imp"]
    mv = [{"from": QUAD[k.split(">")[0]], "to": QUAD[k.split(">")[1]], "key": k,
           "items": sorted(moves[k], key=lambda x: -(x["rc"] or 0))} for k in order if k in moves]
    up = sorted([x for x in streaks if x["dir"] > 0], key=lambda x: (-x["weeks"], -x["cum"]))[:config.WEEKLY_TOP]
    dn = sorted([x for x in streaks if x["dir"] < 0], key=lambda x: (-x["weeks"], x["cum"]))[:config.WEEKLY_TOP]
    return {"moves": mv, "streak_up": up, "streak_down": dn}


def newhigh_week(mkt: str, days: list[str]) -> dict | None:
    root = getattr(config, "NEWHIGH_ROOT", None)
    if not root or not (root / mkt).exists():
        return None
    import csv
    rows = []
    for p in sorted((root / mkt).glob("*.csv"))[-3:]:
        with p.open(encoding="utf-8") as f:
            rows += [r for r in csv.DictReader(f) if r["date"] in days]
    if not rows:
        return {"days": {}, "labels": [], "ath": 0, "w52": 0, "n": 0}
    uniq: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        u = uniq.setdefault(r["code"], {**r, "times": 0})
        u["times"] += 1
        if r["kind"] == "ATH":
            u["kind"] = "ATH"
    by: dict[str, list] = {}
    for u in uniq.values():
        by.setdefault(u["label"], []).append(u)
    labels = sorted(({"label": l, "n": len(v), "names": [x["name"] for x in sorted(v, key=lambda x: -x["times"])[:4]],
                      "repeat": sum(1 for x in v if x["times"] > 1)} for l, v in by.items()),
                    key=lambda x: (-x["n"], -x["repeat"]))
    daily = {d: sum(1 for r in rows if r["date"] == d) for d in days}
    return {"days": daily, "labels": labels[:10], "n": len(uniq),
            "ath": sum(1 for u in uniq.values() if u["kind"] == "ATH"),
            "w52": sum(1 for u in uniq.values() if u["kind"] != "ATH")}


def themes(W_all: dict[str, dict]) -> list[dict]:
    """labels.csv 테마 라벨별 주간 동일가중 수익률 (유니버스에 있는 종목만)."""
    import csv
    p = getattr(config, "NEWHIGH_ROOT", config.ROOT / "data" / "newhigh") / "labels.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        lab = [r for r in csv.DictReader(f) if r.get("label") and r["label"] != "테스트"]
    ret = {}
    for m, W in W_all.items():
        cols = {c: i for i, c in enumerate(W["stocks"]["cols"])}
        for r in W["stocks"]["rows"]:
            if r[cols["week"]] is not None:
                ret[(m, str(r[cols["ticker"]]))] = r[cols["week"]]
    by: dict[str, dict] = {}
    for r in lab:
        t = by.setdefault(r["label"], {"label": r["label"], "by": {}, "vals": [], "listed": 0})
        if r["market"] not in W_all:
            continue
        t["listed"] += 1
        v = ret.get((r["market"], str(r["code"])))
        if v is None:
            continue
        b = t["by"].setdefault(r["market"], [])
        b.append(v)
        t["vals"].append(v)
    out = []
    for t in by.values():
        if len(t["vals"]) < 2:
            continue
        out.append({"label": t["label"], "n": len(t["vals"]), "listed": t["listed"],
                    "avg": _r(sum(t["vals"]) / len(t["vals"])), "med": _r(statistics.median(t["vals"])),
                    "up": _r(sum(v > 0 for v in t["vals"]) / len(t["vals"]) * 100, 0),
                    "by": {m: {"n": len(v), "avg": _r(sum(v) / len(v))} for m, v in t["by"].items()}})
    return sorted(out, key=lambda x: -x["avg"])


def market_block(mkt: str, W: dict, closes: dict, prevW: dict | None = None) -> dict:
    m = config.market(mkt)
    cols = {c: i for i, c in enumerate(W["stocks"]["cols"])}
    rows = W["stocks"]["rows"]
    wk = [r[cols["week"]] for r in rows if r[cols["week"]] is not None]
    ko = getattr(config, "INDUSTRY_KO", {})

    def stock(r):
        ind = r[cols["industry"]]
        name = str(r[cols["name"]]).removesuffix("보통주").strip() if mkt == "kr" else r[cols["name"]]
        return {"code": r[cols["ticker"]], "name": name, "ind": ko.get(ind, ind),
                "week": r[cols["week"]], "mcap": r[cols["mcap"]], "dmcap": r[cols["dmcap"]]}

    mv = [r for r in rows if r[cols["dmcap"]] is not None]
    mv.sort(key=lambda r: r[cols["dmcap"]])
    n = config.WEEKLY_MOVERS
    mkt_cw, mkt_ew = W["market"]["week"]["cw"], W["market"]["week"]["ew"]

    size = []
    for b in (W.get("size") or {}).get("buckets", []):
        size.append({"label": b["label"], "n": b["n"], "cw": b["week"]["cw"], "ew": b["week"]["ew"],
                     "rel": _r(b["week"]["cw"] - mkt_cw) if b["week"]["cw"] is not None and mkt_cw is not None else None,
                     "up": b.get("up")})

    inds = [g for g in W.get("industries", []) if g["n"] >= config.WEEKLY_INDUSTRY_MIN_N and g["week"]["rc"] is not None]
    inds.sort(key=lambda g: -g["week"]["rc"])
    pack = lambda g: {"key": g["key"], "name": _ind_name(g), "n": g["n"],          # noqa: E731
                      "ret": g["ret_cw"], "rel": g["week"]["rc"]}
    k = config.WEEKLY_TOP

    bench = []
    for name, sym in config.WEEKLY_BENCH[mkt]:
        p = week_perf(closes.get(sym), W["days"])
        if p:
            bench.append({"name": name, "sym": sym, **p})
    etfs = []
    for name, sym in config.WEEKLY_ETFS[mkt]:
        p = week_perf(closes.get(sym), W["days"])
        if p and p["week"] is not None:
            etfs.append({"name": name, "sym": sym, "week": p["week"]})
    etfs.sort(key=lambda x: -x["week"])

    out = {
        "label": m["label"], "flag": m["flag"], "currency": m["currency"], "days": W["days"],
        "bench": bench,
        "recon": {"cw": mkt_cw, "ew": mkt_ew,
                  "days": {d: W["market"]["day"][d].get("cw") for d in W["days"] if d in W["market"]["day"]}},
        "median": _r(statistics.median(wk)) if wk else None,
        "up_pct": _r(sum(x > 0 for x in wk) / len(wk) * 100, 0) if wk else None,
        "n": len(rows),
        "size": size,
        "movers": {"down": [stock(r) for r in mv[:n] if r[cols["dmcap"]] < 0],
                   "up": [stock(r) for r in mv[::-1][:n] if r[cols["dmcap"]] > 0]},
        "ind_strong": [pack(g) for g in inds[:k] if g["week"]["rc"] > 0],
        "ind_weak": [pack(g) for g in inds[::-1][:k] if g["week"]["rc"] < 0],
        "etfs": etfs,
    }
    out["contrib"] = contributions(W, mkt)
    out["breadth"] = breadth(mkt, W)
    out["persist"] = persistence(mkt, W, prevW)
    out.update(rotation_and_streak(mkt, W["week"]))
    out["newhigh"] = newhigh_week(mkt, W["days"])
    out["notes"] = notes(out)
    return out


def _pct(x, nd=2):
    return "–" if x is None else f"{x:+.{nd}f}%"


def notes(b: dict) -> list[str]:
    """숫자만으로 만든 사실 문장 2~4개."""
    out = []
    sz = {s["label"]: s for s in b["size"]}
    top, small = b["size"][0] if b["size"] else None, b["size"][-1] if len(b["size"]) > 1 else None
    if top and small and top["cw"] is not None and small["cw"] is not None:
        gap = top["cw"] - small["cw"]
        tail = "대형주가 시장을 끌어내림" if gap <= -3 else "대형주가 시장을 끌어올림" if gap >= 3 else "규모별 차이 크지 않음"
        out.append(f"{top['label']} {_pct(top['cw'])} 대 {small['label']} {_pct(small['cw'])} — {tail}.")
    cw, ew = b["recon"]["cw"], b["recon"]["ew"]
    if cw is not None and ew is not None and abs(ew - cw) >= 1.5:
        out.append(f"시총가중 {_pct(cw)} vs 동일가중 {_pct(ew)} — 종목 대부분은 지수보다 "
                   f"{'선방' if ew > cw else '부진'}함 (주간 오른 종목 {b['up_pct']:.0f}%).")
    if b["ind_strong"] and b["ind_weak"]:
        s, w = b["ind_strong"][0], b["ind_weak"][0]
        out.append(f"가장 강한 산업 {s['name']}(시장 대비 {_pct(s['rel'], 1)}p), 가장 약한 산업 {w['name']}({_pct(w['rel'], 1)}p).")
    c = b.get("contrib") or {}
    tot = c.get("total")
    side = "down" if tot is not None and tot < 0 else "up"
    top5 = c.get(f"top5_{side}")
    if tot and top5 is not None and c.get(side) and top5 / tot >= 0.4:
        names = "·".join(x["name"] for x in c[side][:2])
        out.append(f"재구성 {tot:+.1f}%p 중 상위 5종목({names} 등) 기여 {top5:+.1f}%p, 나머지 합계 {tot - top5:+.1f}%p.")
    elif b["movers"]["down"]:
        d = b["movers"]["down"][0]
        out.append(f"시총 감소 1위 {d['name']} {_pct(d['week'], 1)}.")
    return out


# ── 3국 공통 업종 ───────────────────────────────────────
def common(W: dict[str, dict]) -> dict:
    mk = [m for m in ORDER if m in W]
    if len(mk) < 2:
        return {"markets": mk, "strong": [], "weak": []}
    by: dict[str, dict] = {}
    for m in mk:
        for g in W[m].get("industries", []):
            if g["n"] >= config.WEEKLY_INDUSTRY_MIN_N and g["week"]["rc"] is not None:
                by.setdefault(g["key"], {"key": g["key"], "name": _ind_name(g), "by": {}})["by"][m] = g["week"]["rc"]
    full = [x for x in by.values() if len(x["by"]) == len(mk)]
    for x in full:
        x["avg"] = _r(sum(x["by"].values()) / len(mk))
    full = [x for x in full if abs(x["avg"]) >= 1.0]          # 평균 1%p 미만은 '공통'이라 하기 약함
    k = config.WEEKLY_TOP
    strong = sorted([x for x in full if all(v > 0 for v in x["by"].values())], key=lambda x: -x["avg"])[:k]
    weak = sorted([x for x in full if all(v < 0 for v in x["by"].values())], key=lambda x: x["avg"])[:k]
    return {"markets": mk, "strong": strong, "weak": weak}


def headline(blocks: dict, com: dict) -> str:
    def main(b):
        return b["bench"][0]["week"] if b["bench"] else b["recon"]["cw"]
    vals = {m: main(b) for m, b in blocks.items() if main(b) is not None}
    if not vals:
        return ""
    lo = min(vals, key=vals.get)
    hi = max(vals, key=vals.get)
    parts = [f"{blocks[lo]['label']} {_pct(vals[lo])}로 가장 약했고 {blocks[hi]['label']} {_pct(vals[hi])}로 가장 강했음"
             if hi != lo else f"{blocks[lo]['label']} {_pct(vals[lo])}"]
    if com["weak"] or com["strong"]:
        n = len(com["markets"])
        tail = []
        if com["weak"]:
            tail.append(f"{n}국 공통 약세 {com['weak'][0]['name']}")
        if com["strong"]:
            tail.append(f"공통 강세 {com['strong'][0]['name']}")
        parts.append(" · ".join(tail))
    return " — ".join(parts)


# ── 실행 ────────────────────────────────────────────────
def _prev_week(mkt: str, week: str) -> dict | None:
    ws = sorted(p.stem for p in (config.DATA_ROOT / mkt / "weeks").glob("*.json"))
    ws = [w for w in ws if w < week]
    return _load_week(mkt, ws[-1]) if ws else None


def build(week: str, closes: dict) -> dict | None:
    W = {m: w for m in ORDER if (w := _load_week(m, week))}
    if not W:
        return None
    blocks = {m: market_block(m, W[m], closes, _prev_week(m, week)) for m in W}
    com = common(W)
    return {"week": week, "markets": [m for m in ORDER if m in blocks], "blocks": blocks, "common": com,
            "themes": themes(W),
            "headline": headline(blocks, com),
            "generated": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    weeks = sorted({p.stem for m in ORDER for p in (config.DATA_ROOT / m / "weeks").glob("*.json")})
    if not weeks:
        print("[weekly] 주간 파일 없음 → 건너뜀")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    done = {p.stem for p in OUT.glob("20*.json")}
    todo = weeks if a.all or not done else sorted(set(weeks[-config.WEEKLY_REBUILD:]) | (set(weeks) - done))
    syms = list(dict.fromkeys(s for m in ORDER for _, s in config.WEEKLY_BENCH[m] + config.WEEKLY_ETFS[m]))
    closes = synthetic_closes(syms, pd.Timestamp.today().normalize()) if a.synthetic else fetch_closes(syms, "2y" if len(todo) > 20 else "1y")
    for w in todo:
        d = build(w, closes)
        if d:
            (OUT / f"{w}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    files = sorted(p.stem for p in OUT.glob("20*.json"))
    (OUT / "index.json").write_text(json.dumps({"weeks": files}, ensure_ascii=False))
    print(f"[weekly] {len(todo)}주 작성, 전체 {len(files)}주 — 최근 {files[-1]}")


if __name__ == "__main__":
    main()
