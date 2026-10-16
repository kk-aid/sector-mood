"""합성 데이터: 네트워크 없이 계산 로직과 화면을 검증하기 위한 가짜 시장.
실제 배포에서는 쓰이지 않음 (python -m pipeline.run --synthetic 일 때만)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def make(n_days: int = 180, seed: int = 7, end: str | None = None):
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    dates = pd.bdate_range(end=end, periods=n_days)
    sectors = list(config.SECTOR_KO)
    sizes = rng.integers(5, 160, len(sectors))
    universe, k = [], 0
    for s, n in zip(sectors, sizes):
        for j in range(n):
            mcap = float(np.exp(rng.normal(23, 1.4)))       # 시총 로그정규
            px = float(np.exp(rng.normal(3.8, 0.8)))
            universe.append({"ticker": f"T{k:04d}", "yf": f"T{k:04d}", "name": f"{s} Co {j}",
                             "sector": s, "industry": f"{s} sub{j % 4}", "industry_en": f"{s} sub{j % 4}",
                             "shares": mcap / px, "mcap": mcap, "_px": px})
            k += 1
    T = [u["ticker"] for u in universe]
    sec_of = np.array([sectors.index(u["sector"]) for u in universe])

    mkt = rng.normal(0.0004, 0.010, n_days)
    sec_f = rng.normal(0, 0.008, (n_days, len(sectors)))
    sec_f[-8:, 0] += 0.012          # 상업 서비스: 최근 강세 (테스트용 패턴)
    sec_f[-8:, sectors.index("Electronic Technology")] -= 0.012
    idio = rng.normal(0, 0.015, (n_days, len(T)))
    r = mkt[:, None] + sec_f[:, sec_of] + idio
    px0 = np.array([u["_px"] for u in universe])
    close = px0 * np.cumprod(1 + r, axis=0)

    base_vol = np.array([u["mcap"] * 0.006 / u["_px"] for u in universe])
    vol_sec = np.exp(rng.normal(0, 0.15, (n_days, len(sectors))))
    vol_sec[-8:, 0] *= 1.5            # 상업 서비스 거래 증가
    vol = base_vol * vol_sec[:, sec_of] * np.exp(rng.normal(0, 0.3, (n_days, len(T)))) * (1 + 8 * np.abs(r))
    for u in universe:
        u.pop("_px")

    C = pd.DataFrame(close, index=dates, columns=T)
    V = pd.DataFrame(vol.round(), index=dates, columns=T)
    return universe, C.copy(), C, V


def newhigh_rows(mkt: str = "kr", seed: int = 5) -> list[dict]:
    """신고가 알림 테스트용 TradingView 스크리너 응답 흉내 (등락률 내림차순 아님 — pick 이 정렬함)."""
    rng = np.random.default_rng(seed)
    codes = {
        "kr": [("042700", "한미반도체"), ("011200", "HMM"), ("277810", "레인보우로보틱스"),
               ("352820", "하이브"), ("012450", "한화에어로스페이스"), ("999001", "테스트소형주"),
               ("999002", "가나다스팩1호"), ("999003", "음봉전자")],
        "us": [("NVDA", "NVIDIA"), ("CRWD", "CrowdStrike"), ("RKLB", "Rocket Lab"), ("ZZZZ", "Zeta Co")],
        "jp": [("6857", "Advantest Corporation"), ("7832", "Bandai Namco Holdings Inc."),
               ("9999", "Example Co., Ltd.")],
    }[mkt]
    inds = ["Semiconductors", "Marine Shipping", "Industrial Machinery", "Movies/Entertainment",
            "Aerospace & Defense", "Packaged Software"]
    rows = []
    for i in range(80):
        code, name = codes[i] if i < len(codes) else (f"{mkt}{i:04d}", f"종목{i}")
        chg = float(rng.uniform(0.5, 29.0))
        close = float(rng.uniform(1_000, 100_000))
        open_ = close / (1 + chg / 100) * float(rng.uniform(0.98, 1.0))
        high = close * float(rng.uniform(1.0, 1.03))
        kind = i % 4                       # 0: 역대 신고가, 1: 52주만, 2: 신고가 아님, 3: 랜덤
        ath = high if kind == 0 else high * 1.5
        w52 = high if kind in (0, 1) else high * 1.2
        row = {"name": code, "description": name, "close": close, "open": open_, "high": high,
               "change": chg, "market_cap_basic": float(rng.uniform(1e10, 5e13)), "Value.Traded": 1e10,
               "High.All": ath, "price_52_week_high": w52, "industry": inds[i % len(inds)],
               "exchange": "KRX", "type": "stock", "subtype": "common"}
        if code == "999001":
            row["market_cap_basic"] = 3e10
        if code == "999003":
            row["open"] = close * 1.05     # 음봉
        rows.append(row)
    rows.append({**rows[0], "name": "005935", "description": "삼성전자우", "subtype": "preferred"})
    return rows
