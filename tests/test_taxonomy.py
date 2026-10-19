import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, Mock
from pipeline import taxonomy as T, dart_classify as D


class TaxonomyTests(unittest.TestCase):
    def test_size_and_themes_never_replace_business(self):
        r={'name':'007660','industry':'Electronic Components','sector':'Electronic Technology','market_cap_basic':1e9}
        p=T.profile(r,'kr',{('kr','007660'):'HBM'},reviewed={})
        self.assertEqual(p['industry'],'전자부품')
        self.assertEqual(p['size'],'소형주')
        self.assertEqual(p['legacy_group'],'HBM')
        self.assertEqual(p['sector'],'전자 기술')

    def test_only_evidenced_approved_rows_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'taxonomy.csv'
            base=dict.fromkeys(T.FIELDS,'')
            a={**base,'market':'kr','code':'000001','industry':'후공정 장비','status':'approved'}
            b={**base,'market':'kr','code':'000002','industry':'기판','status':'needs_review','source_url':'https://dart.fss.or.kr','reviewed_on':'2026-10-19'}
            c={**a,'code':'000003','source_url':'https://dart.fss.or.kr','reviewed_on':'2026-10-19','themes':'HBM|AI'}
            with f.open('w') as h:
                w=csv.DictWriter(h,fieldnames=T.FIELDS);w.writeheader();w.writerows([a,b,c])
            approved=T.reviewed_rows(f)
            self.assertEqual(set(approved),{('kr','000003')})
            p=T.profile({'name':'000003'},'kr',reviewed=approved)
            self.assertEqual(p['industry'],'후공정 장비')
            self.assertEqual(p['themes'],['HBM','AI'])

    def test_extract_business_not_financial_or_risk(self):
        text='II. 사업의 내용\n사업의 개요\n주요 제품\n'+'당사는 본더를 제조합니다. '*20+'\n매출액 100\nIII. 재무에 관한 사항\n경쟁사는 양극재 제조'
        business=D.business_section(text)
        self.assertIn('본더',business)
        self.assertNotIn('경쟁사는',business)
        proposals=D.propose(business)
        self.assertEqual(proposals[0]['subindustry_candidate'],'반도체 패키징 장비')
        self.assertEqual(proposals[0]['status'],'needs_review')
        self.assertTrue(proposals[0]['evidence'])
        self.assertEqual(D.propose(''),[])

    def test_zip_xml_and_dart_errors(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr('report.xml','<ROOT><TITLE>II. 사업의 내용</TITLE><P>주요 제품 매출 '+('본더를 제조합니다. '*20)+'</P><TITLE>III. 재무에 관한 사항</TITLE></ROOT>')
        client=D.Client('secret-value')
        client.get=Mock(return_value=Mock(content=buf.getvalue()))
        self.assertIn('본더',client.business('123'))
        with self.assertRaisesRegex(D.DartError,'020'):
            D.archive(b'<result><status>020</status></result>')

    def test_latest_report_keeps_correction(self):
        c=D.Client('secret-value')
        c.json=Mock(return_value={'list':[
            {'report_nm':'사업보고서','rcept_dt':'20260301','rcept_no':'1'},
            {'report_nm':'[정정]반기보고서','rcept_dt':'20260815','rcept_no':'3'},
            {'report_nm':'반기보고서','rcept_dt':'20260814','rcept_no':'2'}]})
        self.assertEqual(c.latest('corp')['rcept_no'],'3')

    def test_error_does_not_leak_key_or_url(self):
        import requests
        c=D.Client('secret-value')
        c.session.get=Mock(side_effect=requests.ConnectionError('https://example?crtfc_key=secret-value'))
        with self.assertRaises(D.DartError) as e:
            c.get('company.json')
        self.assertNotIn('secret-value',str(e.exception))
        self.assertNotIn('https',str(e.exception))


    def test_refresh_stores_evidence_but_never_approves(self):
        from pipeline import config
        import json
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'DART_API_KEY':'test-key'}), patch.object(config,'NEWHIGH_ROOT',Path(tmp)), patch.object(D,'Client') as ctor, patch.object(D.time,'sleep'):
            c=ctor.return_value
            c.companies.return_value={'007660':'corp'}
            c.company.return_value={'stock_code':'007660','induty_code':'26','corp_name':'테스트'}
            c.latest.return_value={'rcept_no':'20261019000001','report_nm':'반기보고서','rcept_dt':'20260814'}
            c.business.return_value='주요 제품은 인쇄회로기판입니다. 매출액은 100입니다.'
            D.refresh(['007660'],1,dry_run=True)
            self.assertFalse((Path(tmp)/'classification').exists())
            D.refresh(['007660'],1)
            data=json.loads((Path(tmp)/'classification/007660.json').read_text())
            self.assertEqual(data['status'],'needs_review')
            self.assertEqual(data['company']['induty_code'],'26')
            self.assertIn('rcpNo=',data['source_url'])
            self.assertFalse((Path(tmp)/'taxonomy.csv').exists())
            c.business.reset_mock()
            D.refresh(['007660'],1)
            c.business.assert_not_called()


if __name__=='__main__':
    unittest.main()
