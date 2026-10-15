"""일봉 수집 (yfinance). 반환: 날짜×종목 DataFrame 3개 (수정종가, 원종가, 거래량). 컬럼은 TradingView 티커."""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import config

CHUNK = 150


def _download(tickers: list[str], period: str) -> pd.DataFrame:
    import yfinance as yf
    for attempt in range(4):
        try:
            df = yf.download(tickers, period=period, interval="1d", auto_adjust=False,
                             group_by="column", threads=True, progress=False)
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            print(f"[prices] 재시도 {attempt + 1}: {e}")
        time.sleep(5 * (attempt + 1))
    return pd.DataFrame()


def _batch(symbols: list[str], period: str):
    adj, close, vol = [], [], []
    for i in range(0, len(symbols), CHUNK):
        part = symbols[i:i + CHUNK]
        df = _download(part, period)
        if df.empty:
            print(f"[prices] 청크 {i // CHUNK} 실패 ({len(part)}종목)")
            continue
        if not isinstance(df.columns, pd.MultiIndex):  # 단일 종목 청크 대비
            df.columns = pd.MultiIndex.from_product([df.columns, part])
        adj.append(df["Adj Close"])
        close.append(df["Close"])
        vol.append(df["Volume"])
        time.sleep(1)
    if not adj:
        return None
    return tuple(pd.concat(x, axis=1) for x in (adj, close, vol))


def fetch_prices(universe: list[dict], mkt: str, period: str = config.PRICE_HISTORY):
    m = config.market(mkt)
    to_tv = {u["yf"]: u["ticker"] for u in universe}
    got = _batch(list(to_tv), period)
    if got is None:
        raise RuntimeError("가격 데이터를 하나도 받지 못함")
    A, C, V = got

    # 1차 심볼로 못 받은 종목은 대체 심볼로 재시도 (한국: .KS → .KQ)
    missing = [u for u in universe if u.get("yf_alt") and
               (u["yf"] not in A.columns or A[u["yf"]].notna().sum() == 0)]
    if missing:
        alt_to_tv = {u["yf_alt"]: u["ticker"] for u in missing}
        got2 = _batch(list(alt_to_tv), period)
        A, C, V = (df.drop(columns=[u["yf"] for u in missing if u["yf"] in df.columns]) for df in (A, C, V))
        if got2 is not None:
            A, C, V = (pd.concat([x, y], axis=1) for x, y in zip((A, C, V), got2))
            to_tv.update(alt_to_tv)
        print(f"[prices:{mkt}] 대체 심볼 재시도 {len(missing)}종목")

    A, C, V = (df.rename(columns=to_tv) for df in (A, C, V))
    A, C, V = (df.loc[:, ~df.columns.duplicated()] for df in (A, C, V))
    for df in (A, C, V):
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()

    # 장중에 실행한 경우 미완성 당일 봉 제거 (시장 현지 시각 기준)
    now = datetime.now(ZoneInfo(m["tz"]))
    if now.weekday() < 5 and (now.hour, now.minute) < m["close"]:
        today = pd.Timestamp(now.date())
        A, C, V = (df[df.index < today] for df in (A, C, V))

    # 휴장일(전 종목 NaN) 제거
    keep = A.notna().sum(axis=1) > len(A.columns) * 0.5
    A, C, V = A[keep], C[keep], V[keep]
    print(f"[prices:{mkt}] {len(A)}거래일 × {A.shape[1]}종목, 최근일 유효 {A.notna().iloc[-1].sum()}종목")
    return A, C, V.fillna(0)
