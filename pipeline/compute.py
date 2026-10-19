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


def _nth_weekday(y, m, weekday, n):
    """y년 m월의 n번째 weekday (월=0)."""
    d = pd.Timestamp(y, m, 1)
    d += pd.Timedelta(days=(weekday - d.weekday()) % 7)
    return d + pd.Timedelta(weeks=n - 1)


QUARTER = (3, 6, 9, 12)


def derivative_events(mkt: str, d: pd.Timestamp) -> list[str]:
    """시장별 파생상품 만기일 표시."""
    if mkt == "us" and d == _nth_weekday(d.year, d.month, 4, 3):
        return ["쿼드러플 위칭·지수 리밸런싱" if d.month in QUARTER else "월물 옵션 만기"]
    if mkt == "kr" and d == _nth_weekday(d.year, d.month, 3, 2):
        return ["선물·옵션 동시만기" if d.month in QUARTER else "옵션 만기"]
    if mkt == "jp" and d == _nth_weekday(d.year, d.month, 4, 2):
        return ["메이저 SQ" if d.month in QUARTER else "SQ (옵션 정산)"]
    return []


class GroupStats:
    """종목 → 그룹(섹터 또는 산업) 단위 일간 원지표."""

    def __init__(self, eng: "Engine", keys: pd.Series):
        self.keys = keys
        g = lambda df: df.T.groupby(keys).sum(min_count=1).T   # noqa: E731
        m = lambda df: df.T.groupby(keys).mean().T              # noqa: E731
        self.cw = g(eng.W * eng.ret) / g(eng.W)
        self.ew = m(eng.ret_clip)
        self.rc = self.cw.sub(eng.mkt_cw, axis=0) * 100
        self.re = self.ew.sub(eng.mkt_ew, axis=0) * 100
        self.sc = self.rc.shift(1).rolling(config.SIGMA_LOOKBACK, min_periods=20).std()
        self.se = self.re.shift(1).rolling(config.SIGMA_LOOKBACK, min_periods=20).std()
        self.gval = g(eng.value)
        self.gavg = self.gval.shift(1).rolling(LB, min_periods=LB).mean()
        self.tv = (self.gval / self.gavg).div(eng.mkt_tv_raw, axis=0)
        self.vr = m(eng.sv).div(eng.mkt_vr_raw, axis=0)
        self.breadth = m(eng.up)
        self.members = {k: keys.index[keys == k] for k in keys.unique()}


class Engine:
    def __init__(self, universe: list[dict], A: pd.DataFrame, C: pd.DataFrame, V: pd.DataFrame,
                 mkt: str = "us"):
        self.mkt = mkt
        meta = pd.DataFrame(universe).drop_duplicates("ticker").set_index("ticker")
        cols = [t for t in A.columns if t in meta.index]
        self.meta = meta.loc[cols]
        if "industry_en" not in self.meta:
            self.meta["industry_en"] = self.meta["industry"]
        self.meta["industry_en"] = self.meta["industry_en"].fillna(self.meta["industry"]).replace("", "Unclassified")
        # 화면 표시용 산업명: FactSet 영문 → 한국어 (config.INDUSTRY_KO, 없으면 원래 값)
        ko = getattr(config, "INDUSTRY_KO", {})
        self.meta["industry"] = [ko.get(en, ind) for en, ind in zip(self.meta["industry_en"], self.meta["industry"])]
        if mkt == "kr":                                   # '유한양행보통주' → '유한양행'
            self.meta["name"] = self.meta["name"].astype(str).str.replace(r"\s*보통주$", "", regex=True)
        self.A, self.C, self.V = A[cols], C[cols], V[cols].fillna(0)
        self.sect = self.meta["sector"]
        self.sectors = sorted(self.sect.unique(), key=lambda s: config.SECTOR_KO.get(s, s))
        self._prepare()

    def _prepare(self):
        A, C, V = self.A, self.C, self.V
        ret = A.pct_change(fill_method=None)
        ret = ret.where(ret.abs() < 3)                    # 비정상값(데이터 오류) 제거
        self.ret = ret
        self.ret_clip = ret.clip(-config.RET_CLIP, config.RET_CLIP)
        self.value = (C * V).where(C.notna())             # 현지 통화 거래대금
        self.W = (self.meta["shares"] * C.shift(1)).where(ret.notna())   # 전일 시총 가중치
        self.vavg = V.shift(1).rolling(LB, min_periods=LB).mean()
        self.sv = (V / self.vavg.replace(0, np.nan)).clip(0, 10)
        self.up = (ret > 0).where(ret.notna()).astype(float)
        self.valavg = self.value.shift(1).rolling(LB, min_periods=LB).mean()

        # 시장 전체
        self.mkt_cw = (self.W * ret).sum(axis=1, min_count=1) / self.W.sum(axis=1, min_count=1)
        self.mkt_ew = self.ret_clip.mean(axis=1)
        self.mkt_val = self.value.sum(axis=1, min_count=1)
        self.mkt_gavg = self.mkt_val.shift(1).rolling(LB, min_periods=LB).mean()
        self.mkt_tv_raw = self.mkt_val / self.mkt_gavg
        self.mkt_vr_raw = self.sv.mean(axis=1)

        # 섹터 / 산업
        self.S = GroupStats(self, self.sect)
        self.I = GroupStats(self, self.meta["industry_en"])
        ind_sector = self.meta.groupby("industry_en")["sector"].agg(lambda x: x.mode().iloc[0])
        ind_name = self.meta.groupby("industry_en")["industry"].agg(lambda x: x.mode().iloc[0])
        sizes = self.meta["industry_en"].value_counts()
        keep = [k for k in sizes.index if sizes[k] >= config.INDUSTRY_MIN_N]
        sidx = {s: i for i, s in enumerate(self.sectors)}
        self.industries = sorted(keep, key=lambda k: (sidx[ind_sector[k]], str(ind_name[k])))
        self.ind_sector, self.ind_name = ind_sector, ind_name

    # 테스트·하위호환용 별칭 (섹터 단위)
    rc = property(lambda self: self.S.rc)
    re = property(lambda self: self.S.re)
    tv = property(lambda self: self.S.tv)
    sc = property(lambda self: self.S.sc)

    # ── 이벤트일 ─────────────────────────────────────────
    def events(self, d: pd.Timestamp) -> list[str]:
        ev = derivative_events(self.mkt, d)
        m = self.mkt_tv_raw.get(d)
        if m is not None and np.isfinite(m):
            if m >= config.MARKET_SPIKE:
                ev.append(f"시장 거래대금 {m:.2f}배 급증")
            elif m <= 0.65:
                ev.append(f"저거래일 ({m:.2f}배, 반일장 등)")
        return ev

    # ── 규모와 쏠림 ──────────────────────────────────────
    def _year_rank(self, year: int):
        """연초 첫 거래일 시총 순위 (데이터가 연초 이후부터면 첫 거래일 기준)."""
        idx = self.A.index
        cand = idx[idx >= pd.Timestamp(year, 1, 1)]
        if not len(cand):
            return None, None
        d = cand[0]
        mc = self.meta["shares"] * self.C.loc[d]
        return d, mc.dropna().rank(ascending=False, method="first")

    def size_block(self, days, ds) -> dict:
        ref, rank = self._year_rank(days[0].year)
        if rank is None:
            return {}
        buckets = []
        for lo, hi, label in config.SIZE_BUCKETS:
            mem = rank.index[(rank >= lo) & ((rank <= hi) if hi else True)]
            if not len(mem):
                continue
            r, w = self.ret.loc[days, mem], self.W.loc[days, mem]
            cw = (w * r).sum(axis=1, min_count=1) / w.sum(axis=1, min_count=1)
            ew = r.clip(-config.RET_CLIP, config.RET_CLIP).mean(axis=1)
            wk = ((1 + r.fillna(0)).prod() - 1).where(r.notna().any())
            buckets.append({
                "label": label, "n": int(len(mem)),
                "up": _r((wk.dropna() > 0).mean() * 100, 0) if wk.notna().any() else None,   # 주간 오른 종목 %
                "day": {dk: {"cw": _r(cw[d] * 100), "ew": _r(ew[d] * 100)} for d, dk in zip(days, ds)},
                "week": {"cw": _r((np.prod(1 + cw.dropna()) - 1) * 100),
                         "ew": _r((np.prod(1 + ew.dropna()) - 1) * 100)},
            })
        k = config.CONCENTRATION_TOP
        val = self.value.loc[days]
        conc_day = {dk: _r(val.loc[d].nlargest(k).sum() / val.loc[d].sum() * 100, 1) for d, dk in zip(days, ds)}
        vw = val.sum()
        tops = vw.nlargest(k)
        return {
            "ref": ref.strftime("%Y-%m-%d"),
            "buckets": buckets,
            "conc": {"day": conc_day, "week": _r(tops.sum() / vw.sum() * 100, 1),
                     "top": [str(t) for t in tops.index]},
        }

    # ── 주간 묶음 ────────────────────────────────────────
    def week_keys(self) -> list[pd.Timestamp]:
        idx = self.A.index
        mondays = sorted({d - pd.Timedelta(days=d.weekday()) for d in idx})
        valid = []
        for m in mondays:
            days = idx[(idx >= m) & (idx < m + pd.Timedelta(days=7))]
            # z-score 와 20일 평균이 계산 가능한 주만
            g0 = self.mkt_gavg.get(days[0]) if len(days) else None
            if g0 is not None and np.isfinite(g0) and self.S.sc.loc[days[0]].notna().any():
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

        mkt_cw_w, mkt_ew_w = comp(self.mkt_cw), comp(self.mkt_ew)
        mkt_val_w = self.mkt_val.loc[days].sum()
        mkt_tv_w = mkt_val_w / (n * self.mkt_gavg.loc[d0])

        # 종목 단위 주간 거래량 배수 (vr 주간)
        Vw = self.V.loc[days].sum()
        sv_w = (Vw / (n * self.vavg.loc[d0].replace(0, np.nan))).clip(0, 10)
        mkt_vr_w = sv_w.mean()

        retw = self.ret.loc[days]
        stock_week = (1 + retw.fillna(0)).prod() - 1
        stock_week = stock_week.where(retw.notna().any())

        def block(G: GroupStats, k):
            members = G.members[k]
            day = {}
            for d, dk in zip(days, ds):
                day[dk] = {
                    "rc": _r(G.rc.at[d, k]), "re": _r(G.re.at[d, k]),
                    "sc": _r(G.sc.at[d0, k], 3), "se": _r(G.se.at[d0, k], 3),
                    "tv": _r(G.tv.at[d, k], 3), "vr": _r(G.vr.at[d, k], 3),
                    "sh": _r(G.gval.at[d, k] / self.mkt_val[d] * 100, 2),
                    "br": _r(G.breadth.at[d, k] * 100, 0),
                }
            g_val_w = G.gval[k].loc[days].sum()
            sw = stock_week.loc[members].dropna()
            return {
                "n": int(len(members)),
                "ret_cw": _r(comp(G.cw[k]) * 100), "ret_ew": _r(comp(G.ew[k]) * 100),
                "day": day,
                "week": {
                    "rc": _r((comp(G.cw[k]) - mkt_cw_w) * 100), "re": _r((comp(G.ew[k]) - mkt_ew_w) * 100),
                    "sc": _r(G.sc.at[d0, k] * np.sqrt(n), 3),
                    "se": _r(G.se.at[d0, k] * np.sqrt(n), 3),
                    "tv": _r(g_val_w / (n * G.gavg.at[d0, k]) / mkt_tv_w, 3),
                    "vr": _r(sv_w.loc[members].mean() / mkt_vr_w, 3),
                    "sh": _r(g_val_w / mkt_val_w * 100, 2),
                    "br": _r((sw > 0).mean() * 100 if len(sw) else np.nan, 0),
                    "wc": int((G.rc.loc[days, k] > 0).sum()),
                    "we": int((G.re.loc[days, k] > 0).sum()),
                },
            }

        sectors = [{"key": s, "name": config.SECTOR_KO.get(s, s), **block(self.S, s)} for s in self.sectors]
        industries = [{"key": k, "name": str(self.ind_name[k]), "sector": self.ind_sector[k],
                       **block(self.I, k)} for k in self.industries]

        # 종목 테이블 (압축 배열)
        sidx = {s: i for i, s in enumerate(self.sectors)}
        val_w = self.value.loc[days].sum()
        up_val = self.value.loc[days].where(retw > 0).sum()
        last_close = self.C.loc[:days[-1]].ffill().iloc[-1]
        pos0 = idx.get_loc(d0)
        prev_close = self.C.iloc[:pos0].ffill().iloc[-1] if pos0 > 0 else pd.Series(dtype=float)
        dmcap = self.meta["shares"] * (last_close - prev_close.reindex(last_close.index))
        iidx = {k: i for i, k in enumerate(self.industries)}
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
                _r(self.meta.at[t, "shares"] * last_close.get(t, np.nan) / 1e8, 0),   # 억 (현지 통화)
                _r(dmcap.get(t, np.nan) / 1e8, 0),                                    # 주간 시총 증감, 억
                iidx.get(self.meta.at[t, "industry_en"], -1),                          # 산업 번호 (-1: 표시 안 함)
            ])

        return {
            "week": monday.strftime("%Y-%m-%d"),
            "days": ds,
            "universe": universe_label,
            "mkt": self.mkt,
            "market": {
                "day": {dk: {"cw": _r(self.mkt_cw[d] * 100), "ew": _r(self.mkt_ew[d] * 100),
                             "tv": _r(self.mkt_tv_raw.get(d), 3)} for d, dk in zip(days, ds)},
                "week": {"cw": _r(mkt_cw_w * 100), "ew": _r(mkt_ew_w * 100), "tv": _r(mkt_tv_w, 3)},
            },
            "events": {dk: ev for d, dk in zip(days, ds) if (ev := self.events(d))},
            "size": self.size_block(days, ds),
            "sectors": sectors,
            "industries": industries,
            "stocks": {
                "cols": ["ticker", "name", "sector", "industry", "days", "week",
                         "upshare", "share", "valx", "mcap", "dmcap", "ind"],
                "sectors": self.sectors,
                "rows": rows,
            },
        }


def _cleanup_legacy():
    """구버전(미국 단일 시장) 출력 docs/data/index.json, docs/data/weeks 제거."""
    old = config.DATA_ROOT / "index.json"
    if old.exists():
        old.unlink()
    oldw = config.DATA_ROOT / "weeks"
    if oldw.exists():
        for f in oldw.glob("*.json"):
            f.unlink()
        oldw.rmdir()


def write_markets_index():
    """docs/data/markets.json: 화면 탭 목록."""
    items = []
    for k, m in config.MARKETS.items():
        p = config.DATA_ROOT / k / "index.json"
        if p.exists():
            items.append({"key": k, "label": m["label"], "flag": m["flag"]})
    (config.DATA_ROOT / "markets.json").write_text(json.dumps(items, ensure_ascii=False))


def write_outputs(engine: Engine, universe_label: str, n_weeks: int):
    mk = config.market(engine.mkt)
    out = config.DATA_ROOT / engine.mkt
    (out / "weeks").mkdir(parents=True, exist_ok=True)
    weeks = engine.week_keys()
    for m in weeks[-n_weeks:]:
        data = engine.build_week(m, universe_label)
        p = out / "weeks" / f"{data['week']}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        print(f"[compute] {p.name}: {len(data['days'])}일, 산업 {len(data['industries'])}개, {len(data['stocks']['rows'])}종목")

    files = sorted((out / "weeks").glob("*.json"))
    index = {
        "weeks": [f.stem for f in files],
        "generated": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
        "last_day": engine.A.index[-1].strftime("%Y-%m-%d"),
        "universe": universe_label,
        "n_stocks": int(len(engine.meta)),
        "min_mcap": mk["min_mcap"],
        "currency": mk["currency"],
        "market": engine.mkt, "label": mk["label"], "flag": mk["flag"],
    }
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    if engine.mkt == "us":
        _cleanup_legacy()
    write_markets_index()
    return index
