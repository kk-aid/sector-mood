import unittest
from unittest.mock import patch
import pandas as pd
from pipeline import synthetic
from pipeline.jpx_classify import parse_frame, normalize
from pipeline.taxonomy import profile
from pipeline.compute import Engine

class JpxTests(unittest.TestCase):
    def rows(self):
        cols=['日付','コード','銘柄名','市場・商品区分','33業種コード','33業種区分','17業種コード','17業種区分']
        return pd.DataFrame([
            ['20260930','8035','東京エレクトロン','プライム（内国株式）','3650','電気機器','9','電機・精密'],
            ['20260930','130A','Test','グロース（内国株式）','9050','サービス業','10','情報通信・サービスその他'],
            ['20260930','1306','ETF','ETF・ETN','-','-','-','-']],columns=cols)

    def test_official_codes_alpha_codes_and_products(self):
        rows=parse_frame(self.rows())
        self.assertEqual(rows['8035']['industry'],'전기기기')
        self.assertEqual(rows['8035']['industry_ja'],'電気機器')
        self.assertEqual(rows['130A']['kind'],'stock')
        self.assertEqual(rows['1306']['kind'],'product')
        self.assertNotIn('industry',rows['1306'])
        self.assertEqual(normalize('130a.T'),'130A')
        with patch('pipeline.jpx_classify.lookup',side_effect=lambda c:rows.get(normalize(c))):
            self.assertEqual(profile({'name':'8035.T'},'jp')['source'],'jpx')
            self.assertEqual(profile({'name':'1306'},'jp',asset='etf')['industry'],'ETF·ETN')
            p=profile({'name':'9999','industry':'Semiconductors'},'jp')
            self.assertEqual(p['industry'],'JPX 미등록')

    def test_invalid_schema_or_codes_fail(self):
        with self.assertRaises(ValueError): parse_frame(pd.DataFrame())
        frame=self.rows();frame.loc[0,'33業種コード']='9999'
        with self.assertRaises(ValueError): parse_frame(frame)

    def test_engine_uses_official_hierarchy_preserving_market_totals(self):
        uni,A,C,V=synthetic.make(n_days=260,seed=4)
        uni=uni[:2];cols=[u['ticker'] for u in uni];A,C,V=(f[cols] for f in (A,C,V))
        baseline=Engine(uni,A,C,V,mkt='jp')
        for u in uni: u.pop('_synthetic',None)
        row=parse_frame(self.rows())['8035']
        with patch('pipeline.jpx_classify.lookup',side_effect=lambda c:row if c==cols[0] else None):
            eng=Engine(uni,A,C,V,mkt='jp')
        self.assertEqual(eng.sector_memberships[cols[0]],['jpx:9'])
        self.assertEqual(eng.industry_memberships[cols[0]],['jpx:3650'])
        self.assertEqual(eng.meta.at[cols[1],'industry'],'JPX 미등록')
        self.assertAlmostEqual(eng.mkt_cw.iloc[-1],baseline.mkt_cw.iloc[-1])
        self.assertAlmostEqual(eng.mkt_val.iloc[-1],baseline.mkt_val.iloc[-1])

if __name__=='__main__': unittest.main()
