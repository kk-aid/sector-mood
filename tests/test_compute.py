"""계산 검증: 엔진 결과를 손계산(루프)과 대조.  python -m tests.test_compute"""
import numpy as np
import pandas as pd

from pipeline import synthetic
from pipeline.compute import Engine


def main():
    uni, A, C, V = synthetic.make(n_days=120, seed=3)
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
    print("OK: 상대등락(시총·동일가중), 상대 거래대금, 이벤트일 모두 손계산과 일치")


if __name__ == "__main__":
    main()
