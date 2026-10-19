import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pipeline import config, synthetic
from pipeline.taxonomy import profile, labels_from_profile
from pipeline.compute import Engine
from pipeline.refresh_classification import refresh

class JapanClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        p=self.root/'toss';p.mkdir()
        self.path=[{'id':'169','name':'반도체','depth':0},{'id':'173','name':'반도체장비','depth':1}]
        (p/'labels.json').write_text(json.dumps({'markets':{'us':{'AMAT':{'memberships':[self.path]}}}}))
        p=self.root/'classification/jp';p.mkdir(parents=True)
        self.rules={'basis':'test explicit crosswalk','reviewed_on':'2026-10-19','rules':[{'provider_industry':'Semiconductors','root_id':'169'}]}
        (p/'common_sectors.json').write_text(json.dumps(self.rules))
        self.review=dict(code='TEST',status='approved',reviewed_on='2026-10-19',common_root_id='169',common_industry_id='173',proposed_subindustry='전기적 테스트',financial_basis={'period_end':'2026-03-31','share_pct':90},sources=[{'url':'https://example.com/annual'}])
        self.save_review()
        self.patches=[patch.object(config,'NEWHIGH_ROOT',self.root),patch.object(config,'UNIVERSE_ROOT',self.root/'universe'),patch('pipeline.taxonomy.toss_rows',return_value=({},None))]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def save_review(self):
        (self.root/'classification/jp/business_review.json').write_text(json.dumps({'candidates':[self.review]}))
    def test_crosswalk_is_not_a_toss_membership(self):
        p=profile({'name':'OTHER','industry':'Semiconductors'},'jp')
        self.assertEqual(p['sector'],'반도체');self.assertEqual(p['source'],'jp_mapped')
        self.assertEqual(p['toss_memberships'],[])
        self.assertNotEqual(p['industry'],'반도체장비')
        self.assertEqual(profile({'name':'MIXED','industry':'Industrial Conglomerates'},'jp')['source'],'provider')
    def test_review_requires_financial_evidence_and_real_target_ids(self):
        p=profile({'name':'TEST'},'jp');self.assertEqual(p['source'],'jp_reviewed')
        self.assertEqual(p['subindustry'],'전기적 테스트')
        self.assertEqual(labels_from_profile(p),['반도체 › 반도체장비'])
        self.review['financial_basis']={};self.save_review()
        self.assertNotEqual(profile({'name':'TEST'},'jp')['source'],'jp_reviewed')
        self.review['financial_basis']={'basis':'single segment'};self.review['common_industry_id']='invented';self.save_review()
        self.assertNotEqual(profile({'name':'TEST'},'jp')['source'],'jp_reviewed')
    def test_market_totals_preserved_and_group_id_shared_with_us(self):
        u,A,C,V=synthetic.make(n_days=260,seed=4);u=u[:2];cols=[r['ticker'] for r in u];A,C,V=(d[cols] for d in (A,C,V))
        baseline=Engine(u,A,C,V,mkt='jp')
        for r in u:r.pop('_synthetic',None)
        self.review['code']=cols[0];self.save_review();u[1]['industry']='Semiconductors'
        e=Engine(u,A,C,V,mkt='jp')
        self.assertEqual(e.sector_memberships[cols[0]],['toss:169'])
        self.assertEqual(e.industry_memberships[cols[0]],['toss:169/173'])
        self.assertNotEqual(e.industry_memberships[cols[1]],['toss:169/173'])
        self.assertAlmostEqual(e.mkt_cw.iloc[-1],baseline.mkt_cw.iloc[-1])
        self.assertAlmostEqual(e.mkt_val.iloc[-1],baseline.mkt_val.iloc[-1])
    def test_archive_refresh_keeps_charts_and_correct_labels(self):
        root=self.root/'site/jp/newhigh';root.mkdir(parents=True)
        p=root/'2026-10-19.json';p.write_text(json.dumps({'day':'2026-10-19','stocks':[{'code':'TEST','label':'old','industry':'Semiconductors','change':3,'chart':{'c':[1,2]}}],'follow':[]}))
        with patch.object(config,'DATA_ROOT',self.root/'site'):refresh('jp')
        s=json.loads(p.read_text())['stocks'][0]
        self.assertEqual(s['classification']['source'],'jp_reviewed')
        self.assertEqual(s['chart'],{'c':[1,2]})
        self.assertEqual(s['labels'],['반도체 › 반도체장비'])

if __name__=='__main__':unittest.main()
