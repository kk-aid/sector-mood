"""매크로 검증.  python -m tests.test_macro"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

from pipeline import macro


def main():
    # 단위별 변화: % / bp / pt
    assert macro.change("pct", 110, 100) == 10.0
    assert macro.change("bp", 4.25, 4.10) == 15.0
    assert macro.change("pt", 18.5, 16.0) == 2.5
    assert macro.change("pct", None, 100) is None
    # 기간 변화와 52주 위치, 주간 키
    idx = pd.bdate_range("2025-10-01", "2026-10-16")
    c = pd.Series(range(len(idx)), index=idx, dtype=float) + 100
    it = macro.item("테스트", "T", "pct", c)
    assert it["pos52"] == 100 and it["chg"]["d1"] == round((c.iloc[-1] / c.iloc[-2] - 1) * 100, 2)
    assert it["wk"]["2026-10-12"] == c.loc["2026-10-16"] and len(it["spark"]) == 130
    ytd_base = c[c.index <= "2025-12-31"].iloc[-1]
    assert it["chg"]["ytd"] == round((c.iloc[-1] / ytd_base - 1) * 100, 2)
    # 전체 실행 (합성)
    tmp = Path(tempfile.mkdtemp())
    old = macro.OUT
    macro.OUT = tmp / "macro.json"
    argv = sys.argv
    try:
        sys.argv = ["x", "--synthetic"]
        macro.main()
        d = json.loads(macro.OUT.read_text())
        n = sum(len(g["items"]) for g in d["groups"])
        assert n == sum(len(items) for _, items in macro.GROUPS) and not d["missing"]
        tnx = [x for g in d["groups"] for x in g["items"] if x["sym"] == "^TNX"][0]
        assert tnx["kind"] == "bp" and 0 < tnx["last"] < 20
    finally:
        sys.argv = argv
        macro.OUT = old
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_macro: OK")


if __name__ == "__main__":
    main()
