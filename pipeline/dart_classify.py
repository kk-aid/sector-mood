"""DART evidence collection and REVIEW-ONLY business-label suggestions.

Uses existing DART_API_KEY. No language-model service or automatic approval.
"""
from __future__ import annotations
import argparse
import io
import json
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests
from . import config

API = 'https://opendart.fss.or.kr/api/'
STOP = {'010', '011', '012', '020', '100', '101', '800', '900', '901'}
# Review suggestions, not definitive company businesses. A mention may describe
# a customer/competitor, aspiration or small segment. Revenue dominance not inferred.
RULES = {
    '반도체 패키징 장비': ('본더', '다이본딩', '다이 본딩', 'TC Bonder', '패키징 장비'),
    '반도체 후공정 서비스': ('반도체 패키징 서비스', '반도체 테스트 서비스', 'OSAT'),
    '반도체 전공정 장비': ('증착장비', '증착 장비', '식각장비', '식각 장비'),
    '반도체 설계': ('팹리스', '디자인하우스', '디자인 하우스', '반도체 설계'),
    '인쇄회로기판': ('인쇄회로기판', '인쇄 회로 기판', 'FC-BGA', 'MLB'),
    '이차전지 소재': ('양극재', '음극재', '전해액', '분리막'),
    '전력기기': ('변압기', '배전반', '차단기'),
    '조선': ('선박 건조', '선박건조'),
    '의약품': ('의약품 제조', '의약품제조', '바이오의약품'),
}


class DartError(RuntimeError):
    def __init__(self, status):
        self.status = str(status)
        # Never include request URLs, response text or authentication parameters.
        super().__init__('DART status ' + self.status)


class Client:
    def __init__(self, key):
        self.key = key
        self.session = requests.Session()

    def get(self, endpoint, **params):
        try:
            r = self.session.get(API + endpoint, params={'crtfc_key': self.key, **params}, timeout=60)
            if not r.ok:
                raise DartError('http_' + str(r.status_code))
            return r
        except requests.RequestException:
            raise DartError('network') from None

    def json(self, endpoint, **params):
        try:
            d = self.get(endpoint, **params).json()
        except ValueError:
            raise DartError('invalid_json') from None
        if d.get('status') != '000':
            raise DartError(d.get('status', 'unknown'))
        return d

    def companies(self):
        raw = self.get('corpCode.xml').content
        with archive(raw) as z:
            names = [n for n in z.namelist() if n.lower().endswith('.xml')]
            root = ET.fromstring(z.read(names[0]))
        return {e.findtext('stock_code', '').strip(): e.findtext('corp_code', '')
                for e in root.iter('list') if re.fullmatch(r'\d{6}', e.findtext('stock_code', '').strip())}

    def company(self, corp):
        d = self.json('company.json', corp_code=corp)
        return {k: d.get(k) for k in ('corp_code', 'corp_name', 'stock_code', 'corp_cls', 'induty_code')}

    def latest(self, corp):
        try:
            d = self.json('list.json', corp_code=corp, pblntf_ty='A', last_reprt_at='Y',
                bgn_de=(date.today() - timedelta(days=550)).strftime('%Y%m%d'),
                end_de=date.today().strftime('%Y%m%d'), sort='date', sort_mth='desc', page_count=100)
        except DartError as ex:
            if ex.status == '013':
                return None
            raise
        # Prefer the latest available periodic report incl. corrections.
        reports = [x for x in d.get('list', []) if any(k in x.get('report_nm', '')
                    for k in ('사업보고서', '반기보고서', '분기보고서'))]
        return max(reports, key=lambda x: (x.get('rcept_dt', ''), x.get('rcept_no', ''))) if reports else None

    def business(self, receipt):
        with archive(self.get('document.xml', rcept_no=receipt).content) as z:
            chunks = []
            for n in sorted(z.namelist()):
                if not n.lower().endswith('.xml'):
                    continue
                try:
                    root = ET.fromstring(z.read(n))
                    text = '\n'.join(t.strip() for t in root.itertext() if t.strip())
                    section = business_section(text)
                    if section:
                        chunks.append(section)
                except ET.ParseError:
                    continue
        return max(chunks, key=len) if chunks else ''


def archive(raw):
    if not raw.startswith(b'PK'):
        try:
            status = ET.fromstring(raw).findtext('status') or 'invalid_zip'
        except ET.ParseError:
            status = 'invalid_zip'
        raise DartError(status)
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        if sum(i.file_size for i in z.infolist()) > 64 * 1024 * 1024:
            z.close()
            raise DartError('archive_too_large')
        return z
    except zipfile.BadZipFile:
        raise DartError('invalid_zip') from None


def business_section(text):
    # DART TOCs may mention the heading first. Keep the longest II section.
    starts = list(re.finditer(r'(?:II[.．]?\s*)?사업의\s*내용', text))
    chunks = []
    for hit in starts:
        tail = text[hit.end():]
        end = re.search(r'(?:III[.．]?\s*)?재무에\s*관한\s*사항', tail)
        section = tail[:end.start()] if end else tail[:120000]
        if len(section) >= 100 and re.search(r'주요\s*제품|사업의\s*개요|매출', section):
            chunks.append(section[:120000])
    return max(chunks, key=len) if chunks else ''


def excerpts(text, terms, limit=3):
    hits = []
    for term in terms:
        for m in re.finditer(re.escape(term), text, flags=re.I):
            clip = re.sub(r'\s+', ' ', text[max(0, m.start()-70):m.end()+150]).strip()
            if clip not in hits:
                hits.append(clip)
            if len(hits) >= limit:
                return hits
    return hits


def propose(text):
    out = []
    for label, terms in RULES.items():
        evidence = excerpts(text, terms)
        if evidence:
            out.append({'subindustry_candidate': label, 'evidence': evidence,
                        'status': 'needs_review', 'confidence': 'keyword_only'})
    return out


def refresh(codes=None, limit=40, dry_run=False):
    key = os.environ.get('DART_API_KEY')
    if not key:
        raise RuntimeError('DART_API_KEY is required (same Actions secret)')
    client = Client(key)
    root = config.NEWHIGH_ROOT / 'classification'
    companies = client.companies()
    if codes:
        selected = list(dict.fromkeys(codes))[:limit]
    else:
        # Process previously unseen/oldest companies first, rather than forever
        # repeating only hand-labelled large companies.
        from .newhigh_enrich import read_records
        recent = {r['code'] for r in read_records('kr') if r.get('date', '') >= (date.today() - timedelta(days=14)).isoformat()}
        selected = sorted(companies, key=lambda code: (
            0 if code in recent and not (root / (code + '.json')).exists() else 1,
            (root / (code + '.json')).stat().st_mtime if (root / (code + '.json')).exists() else 0, code))[:limit]
    stats = {'selected': len(selected), 'success': 0, 'failed': 0, 'candidates': 0}
    for code in selected:
        if code not in companies:
            print(f'[classification] {code}: no DART listing')
            stats['failed'] += 1
            continue
        path = root / (code + '.json')
        try:
            company = client.company(companies[code])
            if company.get('stock_code') != code:
                raise DartError('identity_mismatch')
            report = client.latest(companies[code])
            prior = json.loads(path.read_text()) if path.exists() else {}
            receipt = (report or {}).get('rcept_no')
            if receipt and receipt == prior.get('receipt') and prior.get('extract_status') == 'ok':
                data = prior
                data.update(company=company, checked_on=date.today().isoformat())
            else:
                business = client.business(receipt) if receipt else ''
                candidates = propose(business)
                data = {'code': code, 'company': company, 'checked_on': date.today().isoformat(),
                        'receipt': receipt, 'report_name': (report or {}).get('report_nm'),
                        'filing_date': (report or {}).get('rcept_dt'),
                        'source_url': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + receipt if receipt else None,
                        'extract_status': 'ok' if business else 'business_section_unavailable',
                        'candidates': candidates, 'revenue_evidence': excerpts(business, ('매출액', '매출 비중', '매출비중'), 5),
                        'status': 'needs_review',
                        'note': 'Keyword candidates only; not revenue-weighted. Customer/competitor/new-business mentions require human review.'}
            stats['success'] += 1
            stats['candidates'] += len(data.get('candidates', []))
            if not dry_run:
                root.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            print(f'[classification] {code}: {data["extract_status"]}, {len(data.get("candidates", []))} review candidates')
        except DartError as ex:
            stats['failed'] += 1
            print(f'[classification] {code}: {ex}')
            if ex.status in STOP:
                raise
        except Exception as ex:
            stats['failed'] += 1
            print(f'[classification] {code}: {type(ex).__name__}')
        time.sleep(.25)
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        rows = [json.loads(p.read_text()) for p in sorted(root.glob('*.json')) if p.name != 'summary.json']
        (root / 'summary.json').write_text(json.dumps({'updated': date.today().isoformat(), 'run': stats,
            'companies': [{'code': r['code'], 'name': r.get('company', {}).get('corp_name'),
                           'source_url': r.get('source_url'), 'status': r.get('status'),
                           'candidates': [x['subindustry_candidate'] for x in r.get('candidates', [])]} for r in rows]}, ensure_ascii=False, indent=2))
    print('[classification]', stats)
    if stats['success'] == 0:
        raise RuntimeError('No company evidence collected')
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--codes', help='쉼표로 구분한 국내 종목코드; 없으면 미수집/오래된 순')
    ap.add_argument('--limit', type=int, default=40)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if not 1 <= a.limit <= 200:
        ap.error('--limit must be 1..200')
    codes = [x.strip() for x in a.codes.split(',') if x.strip()] if a.codes else None
    if codes and any(not re.fullmatch(r'\d{6}', c) for c in codes):
        ap.error('codes must be six-digit stock codes')
    refresh(codes, a.limit, a.dry_run)


if __name__ == '__main__':
    main()
