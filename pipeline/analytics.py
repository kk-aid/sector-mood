"""주 단위 이력·로테이션·신호 검증·추세(이평 배열/Stage/Minervini/breadth) 계산.

출력 (docs/data/<시장>/)
- history.json : 섹터·산업 주간 원지표 시계열 + 로테이션 좌표   → 3국 비교·연속성·로테이션 화면
- signals.json : 판정별 다음 기간 시장 대비 성과 집계            → 신호 검증 화면
- trend.json   : 최신일 종목 추세 상태와 업종 breadth            → 추세·폭 화면
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config
from .compute import Engine, GroupStats, _r

CATS = ["hu", "qu", "ch", "ca", "ou", "hd"]


# ── 공통 ────────────────────────────────────────────────
def _round_list(s, nd=2):
    return [_r(x, nd) for x in s]


def week_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """각 거래일의 그 주 월요일."""
    return idx - pd.to_timedelta(idx.weekday, unit="D")


def classify(rel, sig, turn, rule: str, rthr: float, zthr: float, tthr: float):
    """화면·알림과 같은 6칸 분류 (벡터)."""
    x = rel / sig if rule == "sigma" else rel
    thr = zthr if rule == "sigma" else rthr
    hi = turn >= tthr
    out = np.where(x >= thr, np.where(hi, "hu", "qu"),
                   np.where(x <= -thr, np.where(hi, "hd", "ou"), np.where(hi, "ch", "ca")))
    bad = rel.isna() | turn.isna() | (sig.isna() if rule == "sigma" else False)
    return pd.DataFrame(out, index=rel.index, columns=rel.columns).mask(bad)


class Weekly:
    """그룹 주간 지표 (build_week 와 같은 정의를 전체 기간에 벡터로 적용)."""

    def __init__(self, eng: Engine, G: GroupStats):
        idx = eng.A.index
        wk = week_index(idx)
        self.weeks = wk.unique()
        nd = pd.Series(1, index=idx).groupby(wk).sum()
        first = pd.Series(idx, index=idx).groupby(wk).first()

        def comp(df):
            cnt = df.notna().groupby(wk).sum()
            out = (1 + df.fillna(0)).groupby(wk).prod() - 1
            return out.where(cnt > 0)

        self.g_cw, self.g_ew = comp(G.cw), comp(G.ew)
        self.m_cw, self.m_ew = comp(eng.mkt_cw.to_frame("m"))["m"], comp(eng.mkt_ew.to_frame("m"))["m"]
        self.rc = self.g_cw.sub(self.m_cw, axis=0) * 100
        self.re = self.g_ew.sub(self.m_ew, axis=0) * 100
        sq = np.sqrt(nd)
        self.sc = G.sc.loc[first.values].set_axis(first.index).mul(sq, axis=0)
        self.se = G.se.loc[first.values].set_axis(first.index).mul(sq, axis=0)

        mkt_tv = eng.mkt_val.groupby(wk).sum() / (nd * eng.mkt_gavg.loc[first.values].set_axis(first.index))
        g_tv = G.gval.groupby(wk).sum() / G.gavg.loc[first.values].set_axis(first.index).mul(nd, axis=0)
        self.tv = g_tv.div(mkt_tv, axis=0)
        self.mkt_tv = mkt_tv

        Vw = eng.V.groupby(wk).sum()
        sv_w = (Vw / eng.vavg.loc[first.values].set_axis(first.index).mul(nd, axis=0).replace(0, np.nan)).clip(0, 10)
        g_vr = sv_w.T.groupby(G.keys).mean().T
        self.vr = g_vr.div(sv_w.mean(axis=1), axis=0)
        self.nd = nd

        # 로테이션 좌표: RS = 그룹 지수 / 시장 지수
        self.rrg = {}
        for w, g, m in (("cw", self.g_cw, self.m_cw), ("ew", self.g_ew, self.m_ew)):
            rs = (1 + g.fillna(0)).cumprod().div((1 + m.fillna(0)).cumprod(), axis=0)
            ratio = 100 * rs / rs.rolling(config.RRG_TREND).mean()
            mom = 100 + (ratio - ratio.shift(config.RRG_MOM))
            self.rrg[w] = (ratio, mom)


# ── 1) 주간 이력 ─────────────────────────────────────────
def build_history(eng: Engine) -> dict:
    valid = eng.week_keys()[-config.HISTORY_WEEKS:]
    out = {"weeks": [w.strftime("%Y-%m-%d") for w in valid], "groups": {}}
    WS, WI = Weekly(eng, eng.S), Weekly(eng, eng.I)
    out["market"] = {
        "cw": _round_list(WS.m_cw.loc[valid] * 100), "ew": _round_list(WS.m_ew.loc[valid] * 100),
        "tv": _round_list(WS.mkt_tv.loc[valid], 3), "nd": [int(x) for x in WS.nd.loc[valid]],
    }

    def pack(Wk: Weekly, k):
        d = {f: _round_list(getattr(Wk, f)[k].loc[valid], 3 if f in ("sc", "se", "tv", "vr") else 2)
             for f in ("rc", "re", "sc", "se", "tv", "vr")}
        for w in ("cw", "ew"):
            ratio, mom = Wk.rrg[w]
            d[f"x_{w}"] = _round_list(ratio[k].loc[valid])
            d[f"y_{w}"] = _round_list(mom[k].loc[valid])
        return d

    out["groups"]["sector"] = [
        {"key": s, "name": config.SECTOR_KO.get(s, s), "n": int(len(eng.S.members[s])), **pack(WS, s)}
        for s in eng.sectors]
    out["groups"]["industry"] = [
        {"key": k, "name": str(eng.ind_name[k]), "sector": eng.ind_sector[k],
         "n": int(len(eng.I.members[k])), **pack(WI, k)}
        for k in eng.industries if len(eng.I.members[k]) >= config.HISTORY_INDUSTRY_MIN_N]
    return out


# ── 2) 신호 검증 ─────────────────────────────────────────
def _stats(cat: pd.DataFrame, fwd: pd.DataFrame) -> dict:
    c, f = cat.stack(), fwd.stack()
    df = pd.concat([c.rename("c"), f.rename("f")], axis=1).dropna()
    rows = {}

    def summ(x):
        n = len(x)
        if n == 0:
            return {"n": 0}
        sd = x.std(ddof=1) if n > 1 else np.nan
        return {"n": int(n), "mean": _r(x.mean()), "med": _r(x.median()),
                "hit": _r((x > 0).mean() * 100, 1),
                "t": _r(x.mean() / (sd / np.sqrt(n)) if sd and sd > 0 else np.nan)}

    for k in CATS:
        rows[k] = summ(df.loc[df.c == k, "f"])
    rows["all"] = summ(df["f"])
    return rows


def build_signals(eng: Engine) -> dict:
    t = config.NOTIFY_THR
    valid = eng.week_keys()
    out = {"tables": {}, "weeks": len(valid),
           "from": valid[0].strftime("%Y-%m-%d") if valid else None,
           "to": valid[-1].strftime("%Y-%m-%d") if valid else None}

    for level, G in (("sector", eng.S), ("industry", eng.I)):
        keys = list(eng.sectors) if level == "sector" else \
            [k for k in eng.industries if len(eng.I.members[k]) >= config.SIGNAL_INDUSTRY_MIN_N]
        Wk = Weekly(eng, G)
        # 주간: 다음 1주 / 4주 시장 대비 누적 성과 (%p)
        for w in ("cw", "ew"):
            g = (Wk.g_cw if w == "cw" else Wk.g_ew)[keys].loc[valid]
            m = (Wk.m_cw if w == "cw" else Wk.m_ew).loc[valid]
            Ig, Im = (1 + g.fillna(0)).cumprod(), (1 + m.fillna(0)).cumprod()
            f1 = (Ig.shift(-1) / Ig).sub(Im.shift(-1) / Im, axis=0) * 100
            f4 = (Ig.shift(-4) / Ig).sub(Im.shift(-4) / Im, axis=0) * 100
            rel = (Wk.rc if w == "cw" else Wk.re)[keys].loc[valid]
            sig = (Wk.sc if w == "cw" else Wk.se)[keys].loc[valid]
            for turn in ("tv", "vr"):
                tr = getattr(Wk, turn)[keys].loc[valid]
                for rule in ("fixed", "sigma"):
                    cat = classify(rel, sig, tr, rule, t["wR"], t["zR"], t["wT"])
                    out["tables"][f"{level}|week|{rule}|{w}|{turn}"] = {
                        "h1": _stats(cat, f1), "h2": _stats(cat, f4)}
        # 일간: 다음날 / 다음 5일 시장 대비 누적 성과 (%p)
        days = eng.A.index[eng.A.index >= valid[0]] if valid else eng.A.index[:0]
        for w in ("cw", "ew"):
            g = (G.cw if w == "cw" else G.ew)[keys].loc[days]
            m = (eng.mkt_cw if w == "cw" else eng.mkt_ew).loc[days]
            Ig, Im = (1 + g.fillna(0)).cumprod(), (1 + m.fillna(0)).cumprod()
            f1 = (Ig.shift(-1) / Ig).sub(Im.shift(-1) / Im, axis=0) * 100
            f5 = (Ig.shift(-5) / Ig).sub(Im.shift(-5) / Im, axis=0) * 100
            rel = (G.rc if w == "cw" else G.re)[keys].loc[days]
            sig = (G.sc if w == "cw" else G.se)[keys].loc[days]
            for turn in ("tv", "vr"):
                tr = getattr(G, turn)[keys].loc[days]
                for rule in ("fixed", "sigma"):
                    cat = classify(rel, sig, tr, rule, t["dR"], t["zR"], t["dT"])
                    out["tables"][f"{level}|day|{rule}|{w}|{turn}"] = {
                        "h1": _stats(cat, f1), "h2": _stats(cat, f5)}
    return out


# ── 3) 추세: 이평 배열 · Stage · Minervini · breadth ─────
def _align_state(P, mas: list[pd.DataFrame]) -> pd.DataFrame:
    """2 완전 정배열 / 1 정배열 진행 / 0 혼조 / -1 역배열 진행 / -2 완전 역배열.
    완전: 가격 > 단기 > … > 장기 (모두). 진행: 가운데 세 선(2·3·4번째)만 정렬."""
    seq = [P] + mas
    up_all = pd.DataFrame(True, index=P.index, columns=P.columns)
    dn_all = up_all.copy()
    for a, b in zip(seq[:-1], seq[1:]):
        up_all &= a > b
        dn_all &= a < b
    mid = mas[1:4] if len(mas) >= 4 else mas[:3]
    up_mid = (mid[0] > mid[1]) & (mid[1] > mid[2])
    dn_mid = (mid[0] < mid[1]) & (mid[1] < mid[2])
    st = pd.DataFrame(0, index=P.index, columns=P.columns)
    st = st.mask(up_mid, 1).mask(dn_mid, -1).mask(up_all, 2).mask(dn_all, -2)
    valid = mas[-1].notna() & P.notna()
    return st.where(valid)


def _streak(st: pd.DataFrame) -> pd.Series:
    """마지막 날 상태가 연속된 일수."""
    last = st.iloc[-1]
    same = st.eq(last, axis=1)
    rev = same.iloc[::-1]
    return rev.cumprod().sum().where(last.notna())


def build_trend(eng: Engine) -> dict:
    A = eng.A.ffill(limit=3)
    idx = A.index
    ma = {n: A.rolling(n, min_periods=n).mean() for n in config.DAILY_MAS}
    d_state = _align_state(A, [ma[n] for n in config.DAILY_MAS])

    wk = week_index(idx)
    Aw = A.groupby(wk).last()
    wma = {n: Aw.rolling(n, min_periods=n).mean() for n in config.WEEKLY_MAS}
    w_state = _align_state(Aw, [wma[n] for n in config.WEEKLY_MAS])

    # Weinstein Stage (30주선 기울기·위치, 횡보 시 이전 추세로 1/3 구분)
    m30 = wma[30] if 30 in wma else Aw.rolling(30, min_periods=30).mean()
    slope = m30 / m30.shift(4) - 1
    prior = m30 / m30.shift(26) - 1
    f = config.STAGE_FLAT
    stage = pd.DataFrame(np.where(slope > f, np.where(Aw > m30, 2, 3),
                         np.where(slope < -f, np.where(Aw < m30, 4, 1),
                                  np.where(prior > 0, 3, 1))), index=Aw.index, columns=Aw.columns)
    stage = stage.where(m30.notna() & slope.notna())

    # Minervini 트렌드 템플릿 8조건
    m50, m150, m200 = (A.rolling(n, min_periods=n).mean() for n in (50, 150, 200))
    lo52, hi52 = A.rolling(252, min_periods=200).min(), A.rolling(252, min_periods=200).max()
    perf = sum(w * (A / A.shift(n) - 1) for w, n in ((0.4, 63), (0.2, 126), (0.2, 189), (0.2, 252)))
    rs = perf.rank(axis=1, pct=True) * 99
    conds = [
        (A > m150) & (A > m200),
        m150 > m200,
        m200 > m200.shift(22),
        (m50 > m150) & (m50 > m200),
        A > m50,
        A >= 1.3 * lo52,
        A >= 0.75 * hi52,
        rs >= 70,
    ]
    tt = sum(c.astype(int) for c in conds).where(m200.notna() & lo52.notna())

    last, prev = idx[-1], idx[-2]
    wlast = Aw.index[-1]
    wprev = Aw.index[-2] if len(Aw.index) > 1 else wlast
    # 이번 주 중 신고가·신저가
    nh_day = (A >= hi52) & hi52.notna()
    nl_day = (A <= lo52) & lo52.notna()
    this_week = idx[wk == wlast]
    above50, above200 = (A > m50).where(m50.notna()), (A > m200).where(m200.notna())

    meta, sect = eng.meta, eng.sect
    sidx = {s: i for i, s in enumerate(eng.sectors)}

    def agg(members):
        def pct(s):
            s = s.loc[members].dropna()
            return _r(s.mean() * 100, 1) if len(s) else None
        ds, ws, sg = d_state.loc[last, members].dropna(), w_state.loc[wlast, members].dropna(), \
            stage.loc[wlast, members].dropna()
        ttl = tt.loc[last, members].dropna()
        return {
            "n": int(len(members)),
            "d": {str(k): int((ds == k).sum()) for k in (2, 1, 0, -1, -2)},
            "w": {str(k): int((ws == k).sum()) for k in (2, 1, 0, -1, -2)},
            "stage": {str(k): int((sg == k).sum()) for k in (1, 2, 3, 4)},
            "tt": int((ttl == 8).sum()),
            "a50": pct(above50.loc[last]), "a200": pct(above200.loc[last]),
            "a50_prev": pct(above50.loc[idx[max(0, len(idx) - 6)]]),
            "nh": int(nh_day.loc[last, members].sum()), "nl": int(nl_day.loc[last, members].sum()),
            "nh_w": int(nh_day.loc[this_week, members].any().sum()),
            "nl_w": int(nl_day.loc[this_week, members].any().sum()),
            "stage2_prev": int((stage.loc[wprev, members] == 2).sum()),
        }

    sectors = [{"key": s, "name": config.SECTOR_KO.get(s, s), **agg(eng.S.members[s])} for s in eng.sectors]
    market = agg(meta.index)

    # 주간 breadth 이력 (섹터·시장)
    hist_weeks = [w for w in eng.week_keys()][-config.HISTORY_WEEKS:]
    wl = pd.Series(idx, index=idx).groupby(wk).last()

    def bhist(members):
        dlast = wl.loc[hist_weeks].values
        return {
            "a50": _round_list(above50.loc[dlast, members].mean(axis=1) * 100, 1),
            "a200": _round_list(above200.loc[dlast, members].mean(axis=1) * 100, 1),
            "s2": _round_list(stage.loc[hist_weeks, members].eq(2).where(stage.loc[hist_weeks, members].notna())
                              .mean(axis=1) * 100, 1),
            "nhl": [int(nh_day.loc[idx[wk == w], members].any().sum() - nl_day.loc[idx[wk == w], members].any().sum())
                    for w in hist_weeks],
        }

    history = {"weeks": [w.strftime("%Y-%m-%d") for w in hist_weeks], "market": bhist(meta.index),
               "sectors": {s: bhist(eng.S.members[s]) for s in eng.sectors}}

    # 종목 행
    d_streak = _streak(d_state)
    new_d = (d_state.loc[last] == 2) & (d_state.loc[prev] != 2)
    lost_d = (d_state.loc[last] != 2) & (d_state.loc[prev] == 2)
    pct_hi = (A.loc[last] / hi52.loc[last] - 1) * 100
    mcap = meta["shares"] * eng.C.ffill().loc[last] / 1e8
    iidx = {k: i for i, k in enumerate(eng.industries)}
    rows = []
    for t in meta.index:
        ds = d_state.at[last, t]
        if pd.isna(ds):
            continue
        rows.append([
            t, meta.at[t, "name"], sidx[sect[t]], iidx.get(meta.at[t, "industry_en"], -1),
            int(ds), int(d_streak.get(t, 0) or 0),
            None if pd.isna(w_state.at[wlast, t]) else int(w_state.at[wlast, t]),
            None if pd.isna(stage.at[wlast, t]) else int(stage.at[wlast, t]),
            None if pd.isna(stage.at[wprev, t]) else int(stage.at[wprev, t]),
            None if pd.isna(tt.at[last, t]) else int(tt.at[last, t]),
            _r(rs.at[last, t], 0), _r(pct_hi.get(t), 1),
            1 if new_d.get(t, False) else (-1 if lost_d.get(t, False) else 0),
            _r(mcap.get(t), 0),
            [_r(ma[n].at[last, t] and A.at[last, t] / ma[n].at[last, t] * 100 - 100, 1) for n in config.DAILY_MAS],
        ])
    return {
        "asof": last.strftime("%Y-%m-%d"), "week": wlast.strftime("%Y-%m-%d"),
        "daily_mas": config.DAILY_MAS, "weekly_mas": config.WEEKLY_MAS,
        "market": market, "sectors": sectors, "history": history,
        "stocks": {"cols": ["ticker", "name", "sector", "ind", "d", "d_streak", "w", "stage", "stage_prev",
                            "tt", "rs", "from_high", "d_change", "mcap", "gap"],
                   "sectors": eng.sectors, "industries": [str(eng.ind_name[k]) for k in eng.industries],
                   "rows": rows},
    }


def write_analytics(eng: Engine):
    out = config.DATA_ROOT / eng.mkt
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("history", build_history), ("signals", build_signals), ("trend", build_trend)):
        data = fn(eng)
        (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        print(f"[analytics:{eng.mkt}] {name}.json")
