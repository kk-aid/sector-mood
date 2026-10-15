"""일봉 수집 (yfinance). 반환: 날짜×종목 DataFrame 3개 (수정종가, 원종가, 거래량)."""
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


def fetch_prices(universe: list[dict], period: str = config.PRICE_HISTORY):
    yf_to_tv = {u["yf"]: u["ticker"] for u in universe}
    tickers = list(yf_to_tv)
    adj, close, vol = [], [], []
    for i in range(0, len(tickers), CHUNK):
        part = tickers[i:i + CHUNK]
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
        raise RuntimeError("가격 데이터를 하나도 받지 못함")
    A, C, V = (pd.concat(x, axis=1).rename(columns=yf_to_tv) for x in (adj, close, vol))
    for df in (A, C, V):
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()

    # 장중에 수동 실행한 경우 미완성 당일 봉 제거
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() < 5 and (now_et.hour, now_et.minute) < (16, 20):
        today = pd.Timestamp(now_et.date())
        A, C, V = (df[df.index < today] for df in (A, C, V))

    # 시장 휴장일(전 종목 NaN) 제거
    keep = A.notna().sum(axis=1) > len(A.columns) * 0.5
    A, C, V = A[keep], C[keep], V[keep]
    got = A.notna().iloc[-1].sum()
    print(f"[prices] {len(A)}거래일 × {A.shape[1]}종목, 최근일 유효 {got}종목")
    return A, C, V.fillna(0)
