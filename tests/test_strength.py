"""Custom RS formulas, market separation, IPOs, gaps and R/S event semantics."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from pipeline import strength


def frame(rate=.001, n=300):
    idx = pd.bdate_range('2024-01-01', periods=n)
    p = 100 * np.exp(np.arange(n) * rate)
    return pd.DataFrame({'adj': p, 'close': p, 'open': p * .99, 'high': p * 1.01,
                         'low': p * .99, 'volume': np.ones(n) * 100}, index=idx)


class StrengthTests(unittest.TestCase):
    def test_quarter_relative_formula(self):
        f, b = frame(.002), frame(.001)
        m = strength.metrics(f, b)
        self.assertAlmostEqual(m['score'], np.exp(.001 * 63) - 1)
        self.assertAlmostEqual(m['excess_1m'], (np.exp(.001 * 21) - 1) * 100)
        # Both falling, stock falling less: positive market-relative strength.
        self.assertGreater(strength.metrics(frame(-.001), frame(-.002))['score'], 0)

    def test_ties_and_endpoints(self):
        self.assertEqual(strength.percentile({'a': 1, 'b': 1}), {'a': 50, 'b': 50})
        self.assertEqual(strength.percentile({'a': 0, 'b': 1}), {'a': 1, 'b': 99})
        self.assertIsNone(strength.percentile({'only': 1})['only'])

    def test_ipo_missing_sessions_and_stale(self):
        f, b = frame(), frame()
        ipo = f.iloc[-70:]
        m = strength.metrics(ipo, b)
        self.assertIsNone(m['score'])
        self.assertIsNotNone(m['excess_1m'])
        self.assertIsNone(m['mtt_price'])
        gap = f.copy(); gap.loc[gap.index[-64], 'adj'] = np.nan
        self.assertIsNone(strength.metrics(gap, b)['score'])
        gap = f.copy(); gap.loc[gap.index[-10], 'adj'] = np.nan
        self.assertIsNotNone(strength.metrics(gap, b)['score'])
        self.assertIsNone(strength.metrics(gap, b)['mtt_price'])
        self.assertIsNone(strength.metrics(f.iloc[:-1], b))

    def test_market_groups_and_independent_period_denominators(self):
        rows = [{'name': c} for c in ['A', 'B', 'C', 'D', 'IPO']]
        fs = {'A': frame(.004), 'B': frame(.002), 'C': frame(.003), 'D': frame(.001),
              'IPO': frame(.006).iloc[-70:], '@kospi': frame(.001), '@kosdaq': frame(.002)}
        resolved = {c: c + ('.KQ' if c in ['C', 'D'] else '.KS') for c in fs}
        result = strength.calculate(rows, 'kr', fs, resolved)
        self.assertEqual(result['A']['rs'], 99)
        self.assertEqual(result['C']['rs'], 99)
        self.assertEqual(result['D']['benchmark'], 'KOSDAQ')
        self.assertEqual(result['IPO']['rs1_n'], 3)
        self.assertEqual(result['IPO']['rs_n'], 2)
        self.assertIsNone(result['IPO']['rs'])

    def test_turnover_excludes_today(self):
        f = frame(0)
        f.loc[f.index[-1], 'volume'] *= 3
        m = strength.metrics(f, frame(0))
        self.assertAlmostEqual(m['turnover_multiple'], 3)
        self.assertTrue(m['turnover_peak'])
        f.loc[f.index[-5], 'volume'] = 0
        self.assertIsNone(strength.metrics(f, frame())['turnover_multiple'])

    def test_split_adjusted_mtt(self):
        f, b = frame(.003), frame()
        split = f.copy()
        split.loc[split.index[:-30], ['close', 'high', 'low']] *= 2
        self.assertEqual(strength.metrics(f, b)['mtt_price'], strength.metrics(split, b)['mtt_price'])

    def test_flip_requires_prior_breakout_and_first_hold(self):
        n = 160
        c = pd.Series(np.full(n, 90.))
        h, low = c + 1, c - 1
        h.iloc[100] = 100
        c.iloc[150:159] = 110; h.iloc[150:159] = 111; low.iloc[150:159] = 108
        c.iloc[-1], h.iloc[-1], low.iloc[-1] = 111, 112, 101
        flip = strength.support_flip(c, h, low)
        self.assertIsNotNone(flip)
        self.assertEqual(flip['level'], 100)
        low.iloc[155] = 101
        self.assertIsNone(strength.support_flip(c, h, low))
        low.iloc[155] = 108
        c.iloc[150:159] = 90
        self.assertIsNone(strength.support_flip(c, h, low))

    def test_etf_pool_separate_and_display(self):
        rows = [{'name': 'ETF', 'description': '테스트 ETF', 'yf': 'ETF'}]
        fs = {'ETF': frame(.002), '@us': frame(.001)}
        with patch.object(strength, 'download', return_value=(fs, {'ETF': 'ETF'})):
            results, text = strength.run(rows, 'us', lambda r, _: r['description'], write=False, etf=True)
        self.assertEqual(results['ETF']['asset'], 'ETF')
        self.assertIsNone(results['ETF']['rs'])
        self.assertIn('ETF 52주 신고가', text)
        self.assertIn('주식과 별도 순위', text)


if __name__ == '__main__':
    unittest.main()
