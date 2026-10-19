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
                              'ambiguous': ambiguous, 'memberships': [path] + ([[{'id':'d','name':'유통','depth':0}]] if ambiguous else [])}}}, '2026-10-19'

    def test_engine_uses_toss_roots_and_keeps_all_branches(self):
        uni, A, C, V = synthetic.make(n_days=260, seed=3)
        ticker = uni[0]['ticker']
        with patch('pipeline.taxonomy.toss_rows', return_value=self.members(ticker)):
            eng = Engine(uni, A, C, V, use_toss=True)
        self.assertEqual(eng.meta.at[ticker, 'sector'], 'toss:a')
        self.assertEqual(eng.meta.at[ticker, 'industry'], '검사장비')
        self.assertEqual(eng.classification_counts['toss'], 1)
        with patch('pipeline.taxonomy.toss_rows', return_value=self.members(ticker, True)):
            ambiguous = Engine(uni, A, C, V, use_toss=True)
        self.assertEqual(set(ambiguous.sector_memberships[ticker]), {'toss:a','toss:d'})
        self.assertIn(ticker, ambiguous.S.members['toss:d'])

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
            self.assertEqual(out['cum5'],{'토스 대분류 › 반도체':1})
            self.assertEqual(json.loads((root/'index.json').read_text())['counts']['2026-10-19'],{'토스 대분류 › 반도체':1})

    def test_reviewed_primary_business_corrects_sector_too(self):
        uni, A, C, V = synthetic.make(n_days=260, seed=3)
        ticker = uni[0]['ticker']
        reviewed = {('us', ticker): {'sector':'Consumer Services', 'industry':'호텔·레저',
                    'subindustry':'관광호텔', 'themes':'부동산개발',
                    'source_url':'https://kind.krx.co.kr/', 'reviewed_on':'2026-10-19'}}
        with patch('pipeline.taxonomy.reviewed_rows', return_value=reviewed), patch('pipeline.taxonomy.toss_rows',return_value=({},None)):
            eng = Engine(uni, A, C, V, use_toss=True)
        self.assertEqual(eng.sector_names[eng.meta.at[ticker, 'sector']], '검토 승인 · 소비자 서비스')
        self.assertEqual(eng.meta.at[ticker, 'industry'], '관광호텔')
        self.assertEqual(eng.classification_counts['reviewed'], 1)

    def test_multimembership_market_is_unique_and_group_returns_are_correct(self):
        uni,A,C,V = synthetic.make(n_days=260,seed=4)
        uni=uni[:3]; cols=[u['ticker'] for u in uni]
        A,C,V=(df[cols] for df in (A,C,V))
        root1=[{'id':'7','name':'여행','depth':0},{'id':'9','name':'호텔과 리조트','depth':1}]
        root2=[{'id':'101','name':'유통','depth':0}]
        paths={cols[0]:[root1,root2],cols[1]:[root1],cols[2]:[root2]}
        cache={'us':{t:{'memberships':p,'primary':p[0] if len(p)==1 else None,'ambiguous':len(p)>1} for t,p in paths.items()}}
        with patch('pipeline.taxonomy.toss_rows',return_value=(cache,'2026-10-19')):
            eng=Engine(uni,A,C,V,use_toss=True)
        baseline=Engine(uni,A,C,V,use_toss=False)
        self.assertAlmostEqual(eng.mkt_cw.iloc[-1],baseline.mkt_cw.iloc[-1])
        self.assertAlmostEqual(eng.mkt_ew.iloc[-1],baseline.mkt_ew.iloc[-1])
        self.assertAlmostEqual(eng.mkt_val.iloc[-1],baseline.mkt_val.iloc[-1])
        members=cols[:2]; day=A.index[-1]
        expected=(eng.W.loc[day,members]*eng.ret.loc[day,members]).sum()/eng.W.loc[day,members].sum()
        self.assertAlmostEqual(eng.S.cw.at[day,'toss:7'],expected)
        data=eng.build_week(eng.week_keys()[-1],'test')
        row=next(r for r in data['stocks']['rows'] if r[0]==cols[0])
        self.assertEqual(len(row[12]),2)
        self.assertEqual(len(data['stocks']['rows']),3)

    def test_unmapped_is_not_grouped_under_provider_refining(self):
        uni,A,C,V=synthetic.make(n_days=260,seed=4)
        uni=uni[:2]; cols=[u['ticker'] for u in uni]
        A,C,V=(df[cols] for df in (A,C,V))
        with patch('pipeline.taxonomy.toss_rows', return_value=self.members(cols[0])):
            eng=Engine(uni,A,C,V,use_toss=True)
        self.assertEqual(eng.sector_memberships[cols[1]],['toss:unmapped'])
        self.assertEqual(eng.classification_counts['unmapped'],1)
