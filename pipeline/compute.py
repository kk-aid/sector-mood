"""업종 지표 계산 → 주 단위 JSON.

용어
- rc / re : 시장 대비 상대 등락 (%p). rc = 시총가중, re = 동일가중
- sc / se : rc / re 의 직전 60거래일 표준편차 (주 시작 시점 기준, 미래 정보 없음)
- tv      : 상대 거래대금 = (업종 거래대금 / 업종 직전 20일 평균) ÷ (시장 동일 비율)
- vr      : 상대 거래량 배수 = 종목별 (거래량 / 직전 20일 평균) 평균을 시장 평균으로 나눈 값
            → 주가 상승만으로 거래대금이 부푸는 가격 효과를 제거한 버전
분류는 화면(브라우저)에서 기준값을 바꿔가며 하므로 여기서는 원지표만 저장함.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import config

LB = config.TURNOVER_LOOKBACK


def _r(x, nd=2):
    if x is None:
        return None
    try:
        if not np.isfinite(x):
            return None
    except TypeError:
        return None
    return round(float(x), nd)


def _third_friday(y, m):
    d = pd.Timestamp(y, m, 15)
    return d + pd.Timedelta(days=(4 - d.weekday()) % 7)


class Engine:
    def __init__(self, universe: list[dict], A: pd.DataFrame, C: pd.DataFrame, V: pd.DataFrame):
        meta = pd.DataFrame(universe).drop_duplicates("ticker").set_index("ticker")
        cols = [t for t in A.columns if t in meta.index]
        self.meta = meta.loc[cols]
        self.A, self.C, self.V = A[cols], C[cols], V[cols].fillna(0)
        self.sect = self.meta["sector"]
        self.sectors = sorted(self.sect.unique(), key=lambda s: config.SECTOR_KO.get(s, s))
        self._prepare()

    # ── 일간 원지표 ──────────────────────────────────────
    def _gsum(self, df):
        """종목 컬럼 → 업종 컬럼 합계 + MARKET 컬럼."""
        g = df.T.groupby(self.sect).sum(min_count=1).T
        g["MARKET"] = df.sum(axis=1, min_count=1)
        return g

    def _gmean(self, df):
        g = df.T.groupby(self.sect).mean().T
        g["MARKET"] = df.mean(axis=1)
        return g

    def _prepare(self):
        A, C, V = self.A, self.C, self.V
        ret = A.pct_change(fill_method=None)
        ret = ret.where(ret.abs() < 3)                    # 비정상값(데이터 오류) 제거
        self.ret = ret
        self.value = (C * V).where(C.notna())             # 달러 거래대금
        W = (self.meta["shares"] * C.shift(1)).where(ret.notna())   # 전일 시총 가중치

        cw = self._gsum(W * ret) / self._gsum(W)
        ew = self._gmean(ret.clip(-config.RET_CLIP, config.RET_CLIP))
        self.cw, self.ew = cw, ew
        self.rc = cw.sub(cw["MARKET"], axis=0).drop(columns="MARKET") * 100
        self.re = ew.sub(ew["MARKET"], axis=0).drop(columns="MARKET") * 100
        self.sc = self.rc.shift(1).rolling(config.SIGMA_LOOKBACK, min_periods=20).std()
        self.se = self.re.shift(1).rolling(config.SIGMA_LOOKBACK, min_periods=20).std()

        self.gval = self._gsum(self.value)
        self.gavg = self.gval.shift(1).rolling(LB, min_periods=LB).mean()
        tv_raw = self.gval / self.gavg
        self.mkt_tv_raw = tv_raw["MARKET"]
        self.tv = tv_raw.div(tv_raw["MARKET"], axis=0).drop(columns="MARKET")

        self.vavg = V.shift(1).rolling(LB, min_periods=LB).mean()
        sv = (V / self.vavg.replace(0, np.nan)).clip(0, 10)
        vr_raw = self._gmean(sv)
        self.vr = vr_raw.div(vr_raw["MARKET"], axis=0).drop(columns="MARKET")

        self.valavg = self.value.shift(1).rolling(LB, min_periods=LB).mean()
        up = (ret > 0)
        self.breadth = self._gmean(up.where(ret.notna()).astype(float))

    # ── 이벤트일 ─────────────────────────────────────────
    def events(self, d: pd.Timestamp) -> list[str]:
        ev = []
        if d == _third_friday(d.year, d.month):
            ev.append("쿼드러플 위칭·지수 리밸런싱" if d.month in (3, 6, 9, 12) else "월물 옵션 만기")
        m = self.mkt_tv_raw.get(d)
        if m is not None and np.isfinite(m):
            if m >= config.MARKET_SPIKE:
                ev.append(f"시장 거래대금 {m:.2f}배 급증")
            elif m <= 0.65:
                ev.append(f"저거래일 ({m:.2f}배, 반일장 등)")
        return ev

    # ── 주간 묶음 ────────────────────────────────────────
    def week_keys(self) -> list[pd.Timestamp]:
        idx = self.A.index
        mondays = sorted({d - pd.Timedelta(days=d.weekday()) for d in idx})
        valid = []
        for m in mondays:
            days = idx[(idx >= m) & (idx < m + pd.Timedelta(days=7))]
            # z-score 와 20일 평균이 계산 가능한 주만
            if len(days) and self.gavg["MARKET"].get(days[0]) is not None \
                    and np.isfinite(self.gavg["MARKET"].get(days[0])) \
                    and self.sc.loc[days[0]].notna().any():
                valid.append(m)
        return valid

    def build_week(self, monday: pd.Timestamp, universe_label: str) -> dict:
        idx = self.A.index
        days = idx[(idx >= monday) & (idx < monday + pd.Timedelta(days=7))]
        d0, n = days[0], len(days)
        ds = [d.strftime("%Y-%m-%d") for d in days]

        def comp(series):  # 일간 수익률 → 주간 누적
            s = series.loc[days].dropna()
            return (np.prod(1 + s) - 1) if len(s) else np.nan

        mkt_cw_w, mkt_ew_w = comp(self.cw["MARKET"]), comp(self.ew["MARKET"])
        mkt_val_w = self.gval["MARKET"].loc[days].sum()
        mkt_tv_w = mkt_val_w / (n * self.gavg["MARKET"].loc[d0])

        # 종목 단위 주간 거래량 배수 (vr 주간)
        Vw = self.V.loc[days].sum()
        sv_w = (Vw / (n * self.vavg.loc[d0].replace(0, np.nan))).clip(0, 10)
        mkt_vr_w = sv_w.mean()

        retw = self.ret.loc[days]
        stock_week = (1 + retw.fillna(0)).prod() - 1
        stock_week = stock_week.where(retw.notna().any())

        sectors = []
        for s in self.sectors:
            members = self.sect.index[self.sect == s]
            day = {}
            for d, dk in zip(days, ds):
                day[dk] = {
                    "rc": _r(self.rc.at[d, s]), "re": _r(self.re.at[d, s]),
                    "sc": _r(self.sc.at[d0, s], 3), "se": _r(self.se.at[d0, s], 3),
                    "tv": _r(self.tv.at[d, s], 3), "vr": _r(self.vr.at[d, s], 3),
                    "sh": _r(self.gval.at[d, s] / self.gval.at[d, "MARKET"] * 100, 2),
                    "br": _r(self.breadth.at[d, s] * 100, 0),
                }
            sec_val_w = self.gval[s].loc[days].sum()
            rc_w = (comp(self.cw[s]) - mkt_cw_w) * 100
            re_w = (comp(self.ew[s]) - mkt_ew_w) * 100
            sec_tv_w = sec_val_w / (n * self.gavg.at[d0, s])
            sw = stock_week.loc[members].dropna()
            sectors.append({
                "key": s, "name": config.SECTOR_KO.get(s, s), "n": int(len(members)),
                "ret_cw": _r(comp(self.cw[s]) * 100), "ret_ew": _r(comp(self.ew[s]) * 100),
                "day": day,
                "week": {
                    "rc": _r(rc_w), "re": _r(re_w),
                    "sc": _r(self.sc.at[d0, s] * np.sqrt(n), 3),
                    "se": _r(self.se.at[d0, s] * np.sqrt(n), 3),
                    "tv": _r(sec_tv_w / mkt_tv_w, 3),
                    "vr": _r(sv_w.loc[members].mean() / mkt_vr_w, 3),
                    "sh": _r(sec_val_w / mkt_val_w * 100, 2),
                    "br": _r((sw > 0).mean() * 100 if len(sw) else np.nan, 0),
                    "wc": int((self.rc.loc[days, s] > 0).sum()),
                    "we": int((self.re.loc[days, s] > 0).sum()),
                },
            })

        # 종목 테이블 (압축 배열)
        sidx = {s: i for i, s in enumerate(self.sectors)}
        val_w = self.value.loc[days].sum()
        up_val = self.value.loc[days].where(retw > 0).sum()
        last_close = self.C.loc[:days[-1]].ffill().iloc[-1]
        rows = []
        for t in self.meta.index:
            vw = val_w.get(t, 0) or 0
            if not np.isfinite(stock_week.get(t, np.nan)) and vw == 0:
                continue
            avg = self.valavg.at[d0, t]
            rows.append([
                t, self.meta.at[t, "name"], sidx[self.sect[t]], self.meta.at[t, "industry"],
                [_r(retw.at[d, t] * 100) for d in days],
                _r(stock_week.get(t) * 100),
                _r(up_val.get(t, 0) / vw * 100, 0) if vw > 0 else None,
                _r(vw / mkt_val_w * 100, 3),
                _r(vw / (n * avg), 2) if avg and np.isfinite(avg) and avg > 0 else None,
                _r(self.meta.at[t, "shares"] * last_close.get(t, np.nan) / 1e8, 0),   # 억 달러
            ])

        return {
            "week": monday.strftime("%Y-%m-%d"),
            "days": ds,
            "universe": universe_label,
            "market": {
                "day": {dk: {"cw": _r(self.cw.at[d, "MARKET"] * 100), "ew": _r(self.ew.at[d, "MARKET"] * 100),
                             "tv": _r(self.mkt_tv_raw.get(d), 3)} for d, dk in zip(days, ds)},
                "week": {"cw": _r(mkt_cw_w * 100), "ew": _r(mkt_ew_w * 100), "tv": _r(mkt_tv_w, 3)},
            },
            "events": {dk: ev for d, dk in zip(days, ds) if (ev := self.events(d))},
            "sectors": sectors,
            "stocks": {
                "cols": ["ticker", "name", "sector", "industry", "days", "week",
                         "upshare", "share", "valx", "mcap"],
                "sectors": self.sectors,
                "rows": rows,
            },
        }


def write_outputs(engine: Engine, universe_label: str, n_weeks: int):
    out = config.DATA_OUT
    (out / "weeks").mkdir(parents=True, exist_ok=True)
    weeks = engine.week_keys()
    for m in weeks[-n_weeks:]:
        data = engine.build_week(m, universe_label)
        p = out / "weeks" / f"{data['week']}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        print(f"[compute] {p.name}: {len(data['days'])}일, {len(data['stocks']['rows'])}종목")

    files = sorted((out / "weeks").glob("*.json"))
    index = {
        "weeks": [f.stem for f in files],
        "generated": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
        "last_day": engine.A.index[-1].strftime("%Y-%m-%d"),
        "universe": universe_label,
        "n_stocks": int(len(engine.meta)),
        "min_mcap": config.MIN_MCAP_USD,
    }
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    return index
