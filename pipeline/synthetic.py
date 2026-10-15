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
