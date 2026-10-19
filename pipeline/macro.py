"""매크로 대시보드: 환율·금리·채권·신용·원자재·크립토·변동성·글로벌 지수 → docs/data/macro.json

  python -m pipeline.macro              # yfinance + FRED(키 불필요 CSV)
  python -m pipeline.macro --synthetic  # 네트워크 없이 합성 데이터

변화 단위: pct = 등락률(%), bp = 금리·스프레드 차이(bp), pt = 지수 포인트 차이 (VIX 등)
주간 값(wk)은 주(월요일 키)마다 마지막 관측치 → 주간 요약 탭이 그 주 변화를 계산함.
"""
from __future__ import annotations

import argparse
import io
import json
import time
import zlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from . import config

OUT = config.DATA_ROOT / "macro.json"

# (이름, 심볼, 단위, 소스)  소스: yf | fred
GROUPS = [
    ("환율", [("원/달러", "KRW=X", "pct", "yf"), ("엔/달러", "JPY=X", "pct", "yf"), ("달러인덱스", "DX-Y.NYB", "pct", "yf"),
              ("유로/달러", "EURUSD=X", "pct", "yf"), ("위안/달러", "CNY=X", "pct", "yf")]),
    ("금리 (미국채)", [("3개월", "^IRX", "bp", "yf"), ("2년", "DGS2", "bp", "fred"), ("5년", "^FVX", "bp", "yf"),
                    ("10년", "^TNX", "bp", "yf"), ("30년", "^TYX", "bp", "yf"), ("10년−2년", "T10Y2Y", "bp", "fred")]),
    ("신용", [("하이일드 스프레드", "BAMLH0A0HYM2", "bp", "fred"), ("투자등급 스프레드", "BAMLC0A0CM", "bp", "fred"),
             ("하이일드 HYG", "HYG", "pct", "yf"), ("투자등급 LQD", "LQD", "pct", "yf")]),
    ("채권 ETF", [("장기채 TLT", "TLT", "pct", "yf"), ("중기채 IEF", "IEF", "pct", "yf"), ("단기채 SHY", "SHY", "pct", "yf"),
                 ("물가채 TIP", "TIP", "pct", "yf")]),
    ("원자재", [("금", "GC=F", "pct", "yf"), ("은", "SI=F", "pct", "yf"), ("구리", "HG=F", "pct", "yf"),
               ("백금", "PL=F", "pct", "yf"), ("WTI", "CL=F", "pct", "yf"), ("브렌트", "BZ=F", "pct", "yf"),
               ("천연가스", "NG=F", "pct", "yf"), ("밀", "ZW=F", "pct", "yf"), ("옥수수", "ZC=F", "pct", "yf")]),
    ("크립토", [("비트코인", "BTC-USD", "pct", "yf"), ("이더리움", "ETH-USD", "pct", "yf"), ("솔라나", "SOL-USD", "pct", "yf")]),
    ("변동성", [("VIX", "^VIX", "pt", "yf"), ("MOVE (채권 변동성)", "^MOVE", "pt", "yf"), ("나스닥 VXN", "^VXN", "pt", "yf")]),
    ("글로벌 지수", [("S&P500", "^GSPC", "pct", "yf"), ("나스닥", "^IXIC", "pct", "yf"), ("러셀2000", "^RUT", "pct", "yf"),
                   ("코스피", "^KS11", "pct", "yf"), ("코스닥", "^KQ11", "pct", "yf"), ("닛케이225", "^N225", "pct", "yf"),
                   ("항셍", "^HSI", "pct", "yf"), ("상해종합", "000001.SS", "pct", "yf"), ("유로스톡스50", "^STOXX50E", "pct", "yf")]),
]
YIELD_YF = {"^IRX", "^FVX", "^TNX", "^TYX"}


def _r(x, nd=4):
    try:
        return None if x is None or not np.isfinite(x) else round(float(x), nd)
    except TypeError:
        return None


def fetch_yf(symbols: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf
    out = {}
    for i in range(0, len(symbols), 40):
        part = symbols[i:i + 40]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(part, period="2y", interval="1d", auto_adjust=True,
                                 group_by="column", threads=True, progress=False)
                if df is not None and not df.empty:
                    break
            except Exception as e:  # noqa: BLE001
                print(f"[macro] yfinance 재시도 {attempt + 1}: {e}")
            time.sleep(3 * (attempt + 1))
        if df is None or df.empty:
            continue
        close = df["Close"]
        if isinstance(close, pd.Series):
            close = close.to_frame(part[0])
        for s in part:
            if s in close and close[s].notna().sum() > 20:
                c = close[s].dropna()
                c.index = pd.to_datetime(c.index).tz_localize(None).normalize()
                out[s] = c
    return out


def fetch_fred(series_id: str) -> pd.Series | None:
    start = (datetime.now() - timedelta(days=760)).strftime("%Y-%m-%d")
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id, "cosd": start},
                     timeout=30, headers={"User-Agent": "Mozilla/5.0 (sector-mood bot)"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "v"]
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    s = df.dropna().set_index(pd.to_datetime(df.dropna()["date"]))["v"]
    return s if len(s) > 20 else None


def synthetic(symbols: list[str]) -> dict[str, pd.Series]:
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=500)
    out = {}
    for s in symbols:
        rng = np.random.default_rng(zlib.crc32(s.encode()))
        base = {"^TNX": 4.2, "^FVX": 3.9, "^TYX": 4.6, "^IRX": 4.0, "DGS2": 3.8, "T10Y2Y": 0.4,
                "BAMLH0A0HYM2": 3.1, "BAMLC0A0CM": 0.9, "^VIX": 16, "^MOVE": 95, "^VXN": 20}.get(s)
        if base is not None:
            v = base + np.cumsum(rng.normal(0, base * 0.01, len(idx)))
        else:
            v = 100 * np.cumprod(1 + rng.normal(0.0002, 0.012, len(idx)))
        out[s] = pd.Series(v, index=idx)
    return out


def _at(c: pd.Series, d: pd.Timestamp):
    x = c[c.index <= d]
    return float(x.iloc[-1]) if len(x) else None


def change(kind: str, now, then):
    if now is None or then is None:
        return None
    if kind == "pct":
        return _r((now / then - 1) * 100, 2) if then else None
    if kind == "bp":
        return _r((now - then) * 100, 1)
    return _r(now - then, 2)


def item(name, sym, kind, c: pd.Series) -> dict:
    last_d = c.index[-1]
    last = float(c.iloc[-1])
    prev = float(c.iloc[-2]) if len(c) > 1 else None
    ago = lambda days: _at(c, last_d - pd.Timedelta(days=days))   # noqa: E731
    ytd = _at(c, pd.Timestamp(last_d.year - 1, 12, 31))
    y = c[c.index > last_d - pd.Timedelta(days=365)]
    wk = c.groupby(c.index - pd.to_timedelta(c.index.weekday, unit="D")).last()
    sp = c.iloc[-130:]
    return {
        "name": name, "sym": sym, "kind": kind, "last": _r(last), "date": last_d.strftime("%Y-%m-%d"),
        "chg": {"d1": change(kind, last, prev), "w1": change(kind, last, ago(7)), "m1": change(kind, last, ago(30)),
                "m3": change(kind, last, ago(91)), "ytd": change(kind, last, ytd), "y1": change(kind, last, ago(365))},
        "hi52": _r(y.max()), "lo52": _r(y.min()),
        "pos52": _r((last - y.min()) / (y.max() - y.min()) * 100, 0) if y.max() > y.min() else None,
        "spark": [_r(v) for v in sp.values],
        "wk": {d.strftime("%Y-%m-%d"): _r(v) for d, v in wk.iloc[-110:].items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    yf_syms = [s for _, items in GROUPS for _, s, _, src in items if src == "yf"]
    fred_syms = [s for _, items in GROUPS for _, s, _, src in items if src == "fred"]
    if a.synthetic:
        data = synthetic(yf_syms + fred_syms)
    else:
        data = fetch_yf(yf_syms)
        for s in fred_syms:
            try:
                x = fetch_fred(s)
                if x is not None:
                    data[s] = x
            except Exception as e:  # noqa: BLE001
                print(f"[macro] FRED {s} 실패: {e}")
    for s in YIELD_YF & set(data):                       # 야후 금리 지수가 ×10 로 올 때 보정
        if data[s].median() > 20:
            data[s] = data[s] / 10
    groups, miss = [], []
    for g, items in GROUPS:
        rows = []
        for name, sym, kind, _ in items:
            if sym in data:
                rows.append(item(name, sym, kind, data[sym]))
            else:
                miss.append(sym)
        if rows:
            groups.append({"name": g, "items": rows})
    doc = {"generated": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
           "groups": groups, "missing": miss}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    n = sum(len(g["items"]) for g in groups)
    print(f"[macro] {n}개 지표 작성" + (f", 실패 {len(miss)}: {', '.join(miss)}" if miss else ""))


if __name__ == "__main__":
    main()
