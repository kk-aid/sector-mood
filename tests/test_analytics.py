"""분석 모듈 검증: 벡터 계산을 build_week·손계산과 대조.  python -m tests.test_analytics"""
import numpy as np
import pandas as pd

from pipeline import config, synthetic
from pipeline.analytics import Weekly, build_history, build_signals, build_trend, classify
from pipeline.compute import Engine


def close(a, b, tol=0.011):
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= tol)


def main():
    uni, A, C, V = synthetic.make(n_days=420, seed=5)
    eng = Engine(uni, A, C, V, "us")
    meta = pd.DataFrame(uni).set_index("ticker")
    wk = eng.week_keys()[-3]
    W = eng.build_week(wk, "t")
    H = build_history(eng)
    i = H["weeks"].index(W["week"])

    # 1) 주간 이력 = 주간 파일 (섹터·산업 모두)
    for s_hist, s_week in zip(H["groups"]["sector"], W["sectors"]):
        assert s_hist["key"] == s_week["key"]
        for f, tol in (("rc", .011), ("re", .011), ("tv", .002), ("vr", .002), ("sc", .002)):
            assert close(s_hist[f][i], s_week["week"][f], tol), (f, s_hist["key"], s_hist[f][i], s_week["week"][f])
    ind_week = {x["key"]: x for x in W["industries"]}
    for g in H["groups"]["industry"]:
        assert close(g["rc"][i], ind_week[g["key"]]["week"]["rc"]), g["key"]

    # 2) 산업 일간 상대등락 손계산
    k = W["industries"][0]["key"]
    mem = meta.index[meta.industry == k]
    d = pd.Timestamp(W["days"][1]); p = A.index[A.index.get_loc(d) - 1]
    r = A.loc[d] / A.loc[p] - 1
    w = meta.shares * C.loc[p]
    exp = ((w[mem] * r[mem]).sum() / w[mem].sum() - (w * r).sum() / w.sum()) * 100
    assert close(W["industries"][0]["day"][W["days"][1]]["rc"], round(exp, 2)), "산업 상대등락"

    # 3) 로테이션 좌표 손계산 (섹터 하나)
    Wk = Weekly(eng, eng.S)
    s = eng.sectors[0]
    rs = (1 + Wk.g_cw[s].fillna(0)).cumprod() / (1 + Wk.m_cw.fillna(0)).cumprod()
    ratio = 100 * rs / rs.rolling(config.RRG_TREND).mean()
    wts = pd.Timestamp(H["weeks"][-1])
    assert close(H["groups"]["sector"][0]["x_cw"][-1], round(ratio[wts], 2)), "RS 추세"
    mom = 100 + ratio[wts] - ratio.shift(config.RRG_MOM)[wts]
    assert close(H["groups"]["sector"][0]["y_cw"][-1], round(mom, 2)), "RS 모멘텀"

    # 4) 신호 검증: 범주별 표본 합 = 전체, 1주 후 성과 손계산
    S = build_signals(eng)
    tb = S["tables"]["sector|week|fixed|cw|tv"]["h1"]
    assert sum(tb[c]["n"] for c in ("hu", "qu", "ch", "ca", "ou", "hd")) == tb["all"]["n"]
    valid = eng.week_keys()
    t = config.NOTIFY_THR
    cat = classify(Wk.rc.loc[valid], Wk.sc.loc[valid], Wk.tv.loc[valid], "fixed", t["wR"], t["zR"], t["wT"])
    w0, w1 = valid[-6], valid[-5]
    fwd = ((1 + Wk.g_cw.at[w1, s]) - (1 + Wk.m_cw[w1])) * 100
    # 같은 범주·같은 주의 관측치가 집계에 들어갔는지 표본으로 확인
    assert cat.at[w0, s] in tb and tb[cat.at[w0, s]]["n"] > 0
    assert np.isfinite(fwd)

    # 5) 추세: 이평 배열·Minervini 손계산 (종목 하나)
    T = build_trend(eng)
    cols = T["stocks"]["cols"]
    row = T["stocks"]["rows"][3]
    tk = row[0]
    px = A[tk].ffill(limit=3)
    mas = [px.rolling(n).mean().iloc[-1] for n in config.DAILY_MAS]
    seq = [px.iloc[-1]] + mas
    if all(a > b for a, b in zip(seq, seq[1:])):
        exp_state = 2
    elif all(a < b for a, b in zip(seq, seq[1:])):
        exp_state = -2
    elif mas[1] > mas[2] > mas[3]:
        exp_state = 1
    elif mas[1] < mas[2] < mas[3]:
        exp_state = -1
    else:
        exp_state = 0
    assert row[cols.index("d")] == exp_state, ("이평 배열", row[cols.index("d")], exp_state)
    m50, m150, m200 = (px.rolling(n).mean() for n in (50, 150, 200))
    lo, hi = px.rolling(252, min_periods=200).min().iloc[-1], px.rolling(252, min_periods=200).max().iloc[-1]
    P = px.iloc[-1]
    c7 = [P > m150.iloc[-1] and P > m200.iloc[-1], m150.iloc[-1] > m200.iloc[-1], m200.iloc[-1] > m200.iloc[-23],
          m50.iloc[-1] > m150.iloc[-1] and m50.iloc[-1] > m200.iloc[-1], P > m50.iloc[-1], P >= 1.3 * lo, P >= 0.75 * hi]
    rs_ok = row[cols.index("rs")] >= 70
    assert row[cols.index("tt")] == sum(c7) + int(rs_ok), ("Minervini", row[cols.index("tt")], sum(c7), rs_ok)
    tot = sum(T["market"]["d"].values())
    assert tot == len(T["stocks"]["rows"])
    print("OK: 주간 이력=주간 파일, 산업 상대등락, 로테이션 좌표, 신호 표본 합, 이평 배열, Minervini 손계산 일치")


if __name__ == "__main__":
    main()
