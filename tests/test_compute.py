"""계산 검증: 엔진 결과를 손계산(루프)과 대조.  python -m tests.test_compute"""
import numpy as np
import pandas as pd

from pipeline import synthetic
from pipeline.compute import Engine


def main():
    uni, A, C, V = synthetic.make(n_days=260, seed=3)
    eng = Engine(uni, A, C, V)
    meta = pd.DataFrame(uni).set_index("ticker")
    d = A.index[-3]
    p = A.index[A.index.get_loc(d) - 1]
    s = "Finance"
    mem = meta.index[meta.sector == s]

    r = A.loc[d] / A.loc[p] - 1
    w = meta.shares * C.loc[p]
    sec = (w[mem] * r[mem]).sum() / w[mem].sum()
    mkt = (w * r).sum() / w.sum()
    assert abs(eng.rc.at[d, s] - (sec - mkt) * 100) < 1e-9, "시총가중 상대등락 불일치"

    ew = r[mem].mean() - r.mean()
    assert abs(eng.re.at[d, s] - ew * 100) < 1e-9, "동일가중 상대등락 불일치"

    val = C * V
    win = A.index[A.index.get_loc(d) - 20: A.index.get_loc(d)]
    sec_ratio = val.loc[d, mem].sum() / val.loc[win, mem].sum(axis=1).mean()
    mkt_ratio = val.loc[d].sum() / val.loc[win].sum(axis=1).mean()
    assert abs(eng.tv.at[d, s] - sec_ratio / mkt_ratio) < 1e-9, "상대 거래대금 불일치"

    # 3번째 금요일 이벤트
    assert "월물 옵션 만기" in eng.events(pd.Timestamp("2026-10-16"))
    assert eng.events(pd.Timestamp("2026-09-18"))[0].startswith("쿼드러플")
    # 시장별 만기일: 2026-10-01 은 목요일 → 한국 2번째 목 10/8, 일본 2번째 금 10/9
    from pipeline.compute import derivative_events
    assert derivative_events("kr", pd.Timestamp("2026-10-08")) == ["옵션 만기"]
    assert derivative_events("kr", pd.Timestamp("2026-09-10")) == ["선물·옵션 동시만기"]
    assert derivative_events("jp", pd.Timestamp("2026-10-09")) == ["SQ (옵션 정산)"]
    assert derivative_events("jp", pd.Timestamp("2026-10-16")) == []

    # 주간 시총 증감 / 규모 버킷 손계산
    wk = eng.week_keys()[-2]
    data = eng.build_week(wk, "t")
    days = A.index[(A.index >= wk) & (A.index < wk + pd.Timedelta(days=7))]
    prev = A.index[A.index.get_loc(days[0]) - 1]
    cols = data["stocks"]["cols"]
    row = data["stocks"]["rows"][0]
    t = row[0]
    exp = meta.shares[t] * (C.at[days[-1], t] - C.at[prev, t]) / 1e8
    assert abs(row[cols.index("dmcap")] - round(exp)) <= 1, "시총 증감 불일치"
    top10 = data["size"]["buckets"][0]
    assert top10["n"] == 10
    ys = A.index[A.index >= pd.Timestamp(days[0].year, 1, 1)][0]
    big = (meta.shares * C.loc[ys]).nlargest(10).index
    d = days[1]; p = A.index[A.index.get_loc(d) - 1]
    rr = A.loc[d, big] / A.loc[p, big] - 1
    ww = meta.shares[big] * C.loc[p, big]
    assert abs(top10["day"][d.strftime("%Y-%m-%d")]["cw"] - round((ww * rr).sum() / ww.sum() * 100, 2)) < 0.011, "규모 버킷 불일치"
    print("OK: 상대등락(시총·동일가중), 상대 거래대금, 시장별 만기일, 시총 증감, 규모 버킷 모두 손계산과 일치")


if __name__ == "__main__":
    main()
