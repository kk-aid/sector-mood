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

    def test_invalid_schema_or_codes_fail(self):
        with self.assertRaises(ValueError): parse_frame(pd.DataFrame())
        frame=self.rows();frame.loc[0,'33業種コード']='9999'
        with self.assertRaises(ValueError): parse_frame(frame)

    def test_japan_keeps_provider_despite_jpx_cache(self):
        rows=parse_frame(self.rows())
        with patch('pipeline.jpx_classify.lookup',side_effect=lambda c:rows.get(normalize(c))), patch('pipeline.japan_classify.classify',return_value=None):
            p=profile({'name':'8035','sector':'Electronic Technology','industry':'Semiconductors'},'jp')
        self.assertEqual(p['source'],'provider')
        self.assertEqual(p['provider_industry'],p['industry'])

if __name__=='__main__': unittest.main()
