import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import Mock,patch
import requests
from pipeline import toss_classify as T,taxonomy,config

SECTORS=[{'sectorId':'1','name':'IT','depth':0,'parentSectorId':None},
 {'sectorId':'2','name':'반도체','depth':1,'parentSectorId':'1'},
 {'sectorId':'3','name':'메모리','depth':2,'parentSectorId':'2'},
 {'sectorId':'4','name':'기판','depth':1,'parentSectorId':'1'}]
ITEM=[{'symbol':'005930','name':'삼성전자'}]


class TossTests(unittest.TestCase):
    def test_ancestor_removed_but_multiple_branches_kept(self):
        x=T.build_index(SECTORS,[('kr','stock',s,ITEM) for s in ('1','2','3')])
        r=x['kr']['005930']
        self.assertEqual([z['name'] for z in r['primary']],['IT','반도체','메모리'])
        x=T.build_index(SECTORS,[('kr','stock',s,ITEM) for s in ('1','2','3','4')])
        self.assertTrue(x['kr']['005930']['ambiguous'])
        self.assertIsNone(x['kr']['005930']['primary'])
        self.assertEqual(len(x['kr']['005930']['memberships']),2)

    def test_hierarchy_validation(self):
        bad=[{**SECTORS[0],'parentSectorId':'1'}]
        with self.assertRaises(T.TossError):T.build_index(bad,[])
        with self.assertRaises(T.TossError):T.build_index([SECTORS[2]],[])

    def test_stock_etf_and_markets_separate(self):
        x=T.build_index(SECTORS,[('kr','stock','2',ITEM),('kr','etf','2',ITEM),('us','stock','2',ITEM)])
        self.assertEqual(set(x['kr']),{'005930','etf:005930'})
        self.assertEqual(set(x['us']),{'005930'})

    def test_allowlist_and_no_credential_leak(self):
        c=T.Client('secret-id','secret-key')
        with self.assertRaises(T.TossError):c.get('/api/v1/orders')
        c.session.request=Mock(side_effect=requests.ConnectionError('secret-key in URL'))
        with self.assertRaises(T.TossError) as err:c.authenticate()
        self.assertNotIn('secret-key',str(err.exception))
        c.session.request=Mock(return_value=Mock(ok=False,status_code=403))
        with self.assertRaisesRegex(T.TossError,'IP not permitted'):c.authenticate()

    def test_token_issued_once_and_only_read_calls_follow(self):
        c=T.Client('id','secret')
        c._request=Mock(side_effect=[{'access_token':'token'},{'result':{'sectors':SECTORS}},{'result':{'stocks':ITEM}}])
        c.get('/api/v1/sectors');c.get('/api/v1/sectors/2/stocks',marketCountry='KR')
        self.assertEqual([x.args[0] for x in c._request.call_args_list],['POST','GET','GET'])

    def test_cache_fallback_and_manual_override(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(config,'NEWHIGH_ROOT',Path(tmp)):
            p=Path(tmp)/'toss/labels.json';p.parent.mkdir()
            doc={'asof':datetime.now(timezone.utc).isoformat(),'partial':False,
                 'markets':T.build_index(SECTORS,[('kr','stock','3',ITEM)])}
            p.write_text(json.dumps(doc))
            row={'name':'005930','industry':'Electronic Components'}
            x=taxonomy.profile(row,'kr',reviewed={})
            self.assertEqual(x['source'],'toss');self.assertEqual(x['subindustry'],'메모리')
            manual={('kr','005930'):{'industry':'복합 반도체','source_url':'https://dart.fss.or.kr','reviewed_on':'2026-10-19'}}
            self.assertEqual(taxonomy.profile(row,'kr',reviewed=manual)['source'],'reviewed')
            doc['asof']=(datetime.now(timezone.utc)-timedelta(days=15)).isoformat();p.write_text(json.dumps(doc))
            self.assertEqual(taxonomy.profile(row,'kr',reviewed={})['source'],'provider')

    def test_failure_preserves_previous_cache_and_dryrun_never_writes(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(config,'NEWHIGH_ROOT',Path(tmp)),patch.dict('os.environ',{'TOSS_CLIENT_ID':'id','TOSS_CLIENT_SECRET':'secret'}),patch.object(T,'Client') as ctor,patch.object(T.time,'sleep'):
            p=Path(tmp)/'toss/labels.json';p.parent.mkdir();p.write_text('existing')
            c=ctor.return_value
            c.get.side_effect=[{'sectors':SECTORS},T.TossError('failed')]
            with self.assertRaises(T.TossError):T.refresh()
            self.assertEqual(p.read_text(),'existing')
            def response(path,**kwargs):
                if path=='/api/v1/sectors':return {'sectors':SECTORS}
                return {'etfs':ITEM} if path.endswith('etfs') else {'stocks':ITEM}
            c.get.side_effect=response
            T.refresh(dry_run=True,max_sectors=1)
            self.assertEqual(p.read_text(),'existing')
            T.refresh()
            doc=json.loads(p.read_text())
            self.assertFalse(doc['partial'])
            self.assertNotIn('secret',p.read_text())


if __name__=='__main__':unittest.main()
