"""실행 진입점.

  python -m pipeline.run --market us             # 평소 (최근 2주 재계산)
  python -m pipeline.run --market kr --weeks 26  # 백필
  python -m pipeline.run --market jp --rebuild-universe
  python -m pipeline.run --market us --synthetic # 네트워크 없이 합성 데이터로 테스트

출력 폴더에 데이터가 없으면 자동으로 config.BACKFILL_WEEKS 주를 백필함.
"""
from __future__ import annotations

import argparse

from . import config
from .compute import Engine, write_outputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="us", choices=list(config.MARKETS))
    ap.add_argument("--weeks", type=int, default=2, help="다시 계산할 최근 주 수")
    ap.add_argument("--rebuild-universe", action="store_true")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()
    mkt = args.market

    weeks = args.weeks
    if not (config.DATA_ROOT / mkt / "index.json").exists():
        weeks = max(weeks, config.BACKFILL_WEEKS)
        print(f"[run:{mkt}] 기존 데이터 없음 → {weeks}주 백필")

    if args.synthetic:
        from . import synthetic
        universe, A, C, V = synthetic.make(n_days=420, seed={"us": 7, "kr": 11, "jp": 13}[mkt])
        label = "synthetic"
    else:
        from .prices import fetch_prices
        from .universe import load_universe
        label, universe = load_universe(mkt, force=args.rebuild_universe)
        A, C, V = fetch_prices(universe, mkt)

    eng = Engine(universe, A, C, V, mkt)
    idx = write_outputs(eng, label, weeks)
    print(f"[done:{mkt}] 주 {len(idx['weeks'])}개, 최근 거래일 {idx['last_day']}, 종목 {idx['n_stocks']}")


if __name__ == "__main__":
    main()
