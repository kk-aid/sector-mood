import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pipeline import config, synthetic
from pipeline.compute import Engine
from pipeline.refresh_classification import refresh


class SiteClassificationTests(unittest.TestCase):
    def members(self, code, ambiguous=False):
        path = [{'id': 'a', 'name': '토스 대분류', 'depth': 0},
                {'id': 'b', 'name': '반도체', 'depth': 1},
                {'id': 'c', 'name': '검사장비', 'depth': 2}]
        return {'us': {code: {'primary': None if ambiguous else path,
                              'ambiguous': ambiguous, 'memberships': [path]}}}, '2026-10-19'

    def test_engine_preserves_common_sector_and_handles_ambiguous(self):
        uni, A, C, V = synthetic.make(n_days=260, seed=3)
        ticker = uni[0]['ticker']
        with patch('pipeline.taxonomy.toss_rows', return_value=self.members(ticker)):
            eng = Engine(uni, A, C, V)
        self.assertEqual(eng.meta.at[ticker, 'sector'], uni[0]['sector'])
        self.assertEqual(eng.meta.at[ticker, 'industry'], '검사장비')
        self.assertEqual(eng.classification_counts['toss'], 1)
        with patch('pipeline.taxonomy.toss_rows', return_value=self.members(ticker, True)):
            ambiguous = Engine(uni, A, C, V)
        self.assertFalse(ambiguous.meta.at[ticker, 'industry_en'].startswith('toss:'))

    def test_refresh_preserves_prices_materials_and_rebuilds_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, records = Path(tmp)/'docs', Path(tmp)/'records'
            root = data/'us'/'newhigh'
            root.mkdir(parents=True)
            page = {'day':'2026-10-19','stocks':[{'code':'TEST','name':'Test',
                    'label':'old','industry':'Semiconductors','kind':'ATH','change':5,
                    'chart':{'c':[1,2,3]},'news':[{'t':'unchanged'}]}],
                    'follow':[{'code':'TEST','label':'old','ret':3}], 'clusters':[]}
            f=root/'2026-10-19.json'
            f.write_text(json.dumps(page))
            (root/'index.json').write_text('{"days":["2026-10-19"]}')
            with patch.object(config,'DATA_ROOT',data), patch.object(config,'NEWHIGH_ROOT',records), patch('pipeline.taxonomy.toss_rows',return_value=self.members('TEST')):
                refresh('us')
            out=json.loads(f.read_text())
            self.assertEqual(out['stocks'][0]['label'],'반도체')
            self.assertEqual(out['stocks'][0]['chart'],page['stocks'][0]['chart'])
            self.assertEqual(out['stocks'][0]['news'],page['stocks'][0]['news'])
            self.assertEqual(out['follow'][0]['ret'],3)
            self.assertEqual(out['follow'][0]['label'],'반도체')
            self.assertEqual(out['cum5'],{'반도체':1})
            self.assertEqual(json.loads((root/'index.json').read_text())['counts']['2026-10-19'],{'반도체':1})

    def test_reviewed_primary_business_corrects_sector_too(self):
        uni, A, C, V = synthetic.make(n_days=260, seed=3)
        ticker = uni[0]['ticker']
        reviewed = {('us', ticker): {'sector':'Consumer Services', 'industry':'호텔·레저',
                    'subindustry':'관광호텔', 'themes':'부동산개발',
                    'source_url':'https://kind.krx.co.kr/', 'reviewed_on':'2026-10-19'}}
        with patch('pipeline.taxonomy.reviewed_rows', return_value=reviewed), patch('pipeline.taxonomy.toss_rows',return_value=({},None)):
            eng = Engine(uni, A, C, V)
        self.assertEqual(eng.meta.at[ticker, 'sector'], 'Consumer Services')
        self.assertEqual(eng.meta.at[ticker, 'industry'], '관광호텔')
        self.assertEqual(eng.classification_counts['reviewed'], 1)
