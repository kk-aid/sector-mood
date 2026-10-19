"""주간 요약 검증.  python -m tests.test_weekly"""
import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from pipeline import config, synthetic, weekly
from pipeline.compute import Engine, write_outputs


def main():
    # 1) 실제 지수 주간·요일별 수익률: 전주 마지막 종가 기준, 휴장일은 빈칸
    idx = pd.to_datetime(["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-15"])
    c = pd.Series([100, 110, 99, 108.9, 108.9], index=idx)
    p = weekly.week_perf(c, ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"])
    assert p["week"] == -1.0 and p["days"] == {"2026-10-12": -10.0, "2026-10-13": 10.0, "2026-10-15": 0.0}, p
    assert weekly.week_perf(None, ["2026-10-12"]) is None

    tmp = Path(tempfile.mkdtemp())
    old = config.DATA_ROOT
    config.DATA_ROOT, weekly.OUT = tmp, tmp / "weekly"
    try:
        # 2) 합성 시장 3개로 주간 파일 만든 뒤 요약
        for mkt, seed in (("us", 7), ("kr", 11), ("jp", 13)):
            uni, A, C, V = synthetic.make(n_days=320, seed=seed)
            write_outputs(Engine(uni, A, C, V, mkt), "t", 3)
        wk = sorted(p.stem for p in (tmp / "kr" / "weeks").glob("*.json"))[-1]
        syms = [s for m in weekly.ORDER for _, s in config.WEEKLY_BENCH[m] + config.WEEKLY_ETFS[m]]
        d = weekly.build(wk, weekly.synthetic_closes(syms, pd.Timestamp.today().normalize()))
        assert d["markets"] == ["kr", "jp", "us"]
        W = json.loads((tmp / "kr" / "weeks" / f"{wk}.json").read_text())
        b = d["blocks"]["kr"]
        cols = {c: i for i, c in enumerate(W["stocks"]["cols"])}
        rets = sorted(r[cols["week"]] for r in W["stocks"]["rows"] if r[cols["week"]] is not None)
        assert b["recon"]["cw"] == W["market"]["week"]["cw"] and b["n"] == len(W["stocks"]["rows"])
        assert abs(b["median"] - pd.Series(rets).median()) < 0.006
        assert b["up_pct"] == round(sum(x > 0 for x in rets) / len(rets) * 100)
        # 규모: 시장 대비 = 묶음 − 시장, 오른 종목 % 존재
        s0 = b["size"][0]
        assert abs(s0["rel"] - (s0["cw"] - b["recon"]["cw"])) < 0.011 and s0["up"] is not None
        # 시총 증감: 감소는 오름차순·음수, 증가는 내림차순·양수
        dn, up = [x["dmcap"] for x in b["movers"]["down"]], [x["dmcap"] for x in b["movers"]["up"]]
        assert dn == sorted(dn) and all(x < 0 for x in dn) and up == sorted(up, reverse=True) and all(x > 0 for x in up)
        # 강·약 산업: 시장 대비 부호·정렬·최소 종목 수
        st, wkk = b["ind_strong"], b["ind_weak"]
        assert all(x["rel"] > 0 and x["n"] >= config.WEEKLY_INDUSTRY_MIN_N for x in st)
        assert [x["rel"] for x in st] == sorted([x["rel"] for x in st], reverse=True)
        assert all(x["rel"] < 0 for x in wkk)
        # 3국 공통: 모든 시장에서 같은 부호, 평균 = 세 값 평균
        for x in d["common"]["strong"]:
            assert len(x["by"]) == 3 and all(v > 0 for v in x["by"].values())
            assert abs(x["avg"] - sum(x["by"].values()) / 3) < 0.011
        for x in d["common"]["weak"]:
            assert all(v < 0 for v in x["by"].values())
        # 벤치마크·ETF 는 합성 가격에서 계산됨, ETF 내림차순
        assert b["bench"] and b["bench"][0]["name"] == "코스피"
        e = [x["week"] for x in b["etfs"]]
        assert e == sorted(e, reverse=True)
        assert d["headline"] and all(isinstance(t, str) for t in b["notes"])
        # 기여도: 종목 기여 합 ≈ 재구성 시총가중 (보유 기준 근사라 작은 차이 허용), 섹터 합 = 종목 합
        cb = b["contrib"]
        assert abs(cb["total"] - b["recon"]["cw"]) < 0.6, (cb["total"], b["recon"]["cw"])
        assert abs(sum(x["c"] for x in cb["sectors"]) - cb["total"]) < 0.05
        assert all(x["c"] < 0 for x in cb["down"]) and all(x["c"] > 0 for x in cb["up"])
        assert abs(cb["top5_down"] - sum(x["c"] for x in cb["down"][:5])) < 0.01
        # 지난주 강·약 산업 지속: 이번 주 값이 이번 주 파일과 같음
        ps = b["persist"]
        now = {g["name"]: g["week"]["rc"] for g in W["industries"]}
        assert ps and all(x["now"] == now.get(x["name"]) for x in ps["strong"] if x["name"] in now)
        assert ps["keep_strong"] == sum(1 for x in ps["strong"] if x["now"] is not None and x["now"] > 0)
        # 연속 상회: 3주 이상, 정렬
        assert all(x["weeks"] >= 3 and x["dir"] > 0 for x in b.get("streak_up", []))
        # 테마: 등록 종목 수 ≥ 계산 종목 수, 평균은 종목 평균
        for t in d["themes"]:
            assert t["n"] <= t["listed"] and t["n"] >= 2
        json.dumps(d, allow_nan=False)
        # 3) main(): 파일·색인 작성
        import sys
        argv = sys.argv
        sys.argv = ["x", "--synthetic"]
        try:
            weekly.main()
        finally:
            sys.argv = argv
        assert json.loads((tmp / "weekly" / "index.json").read_text())["weeks"][-1] == wk
    finally:
        config.DATA_ROOT = old
        weekly.OUT = old / "weekly"
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_weekly: OK")


if __name__ == "__main__":
    main()
