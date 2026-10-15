"""실행 진입점.

  python -m pipeline.run                 # 평소 (최근 2주 재계산)
  python -m pipeline.run --weeks 26      # 백필 (최근 26주)
  python -m pipeline.run --rebuild-universe
  python -m pipeline.run --synthetic     # 네트워크 없이 합성 데이터로 테스트
"""
from __future__ import annotations

import argparse

from . import config
from .compute import Engine, write_outputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=2, help="다시 계산할 최근 주 수")
    ap.add_argument("--rebuild-universe", action="store_true")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()

    if args.synthetic:
        from . import synthetic
        universe, A, C, V = synthetic.make()
        label = "synthetic"
    else:
        from .prices import fetch_prices
        from .universe import load_universe
        label, universe = load_universe(force=args.rebuild_universe)
        A, C, V = fetch_prices(universe)

    eng = Engine(universe, A, C, V)
    idx = write_outputs(eng, label, args.weeks)
    print(f"[done] 주 {len(idx['weeks'])}개, 최근 거래일 {idx['last_day']}, 출력: {config.DATA_OUT}")


if __name__ == "__main__":
    main()
