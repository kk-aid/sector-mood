"""Toss official sector hierarchy/membership sync. No account/order endpoints.

Credentials are in memory only. A token issue invalidates the client's prior
access token: use a dedicated API client, not one shared with another program.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from . import config

BASE = 'https://openapi.tossinvest.com'


class TossError(RuntimeError):
    pass


class Client:
    def __init__(self, client_id, client_secret):
        self.session = requests.Session()
        self._id, self._secret, self._token = client_id, client_secret, None

    def _request(self, method, path, **kwargs):
        try:
            r = self.session.request(method, BASE + path, timeout=45,
                                     allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise TossError('Toss connection error (credentials omitted)') from None
        if not r.ok or 300 <= r.status_code < 400:
            msg = {401:'invalid credentials/token', 403:'IP not permitted; check allowed IP and runner',
                   429:'rate limit; retry later'}.get(r.status_code, 'API error')
            raise TossError(f'Toss HTTP {r.status_code}: {msg}')
        try:
            return r.json()
        except ValueError:
            raise TossError('Invalid Toss JSON response') from None

    def authenticate(self):
        d = self._request('POST', '/oauth2/token', data={'grant_type':'client_credentials',
                'client_id':self._id, 'client_secret':self._secret})
        if not isinstance(d.get('access_token'), str) or not d['access_token']:
            raise TossError('Toss token response missing access_token')
        self._token = d['access_token']

    def get(self, path, **params):
        # Explicit allowlist prevents accidental expansion into financial actions.
        if path != '/api/v1/sectors' and not re.fullmatch(r'/api/v1/sectors/[A-Za-z0-9_-]{1,40}/(?:stocks|etfs)', path):
            raise TossError('Only sector read endpoints are allowed')
        if not self._token:
            self.authenticate()
        d = self._request('GET', path, headers={'Authorization':'Bearer ' + self._token}, params=params)
        if not isinstance(d.get('result'), dict):
            raise TossError('Toss sector response missing result')
        return d['result']


def lineage(sector_id, sectors):
    path, seen = [], set()
    while sector_id is not None:
        sector_id = str(sector_id)
        if sector_id in seen or sector_id not in sectors:
            raise TossError('Invalid sector hierarchy (cycle/missing parent)')
        seen.add(sector_id)
        node = sectors[sector_id]
        path.append({'id':sector_id, 'name':node['name'], 'depth':node['depth']})
        sector_id = node.get('parentSectorId')
    path.reverse()
    if [p['depth'] for p in path] != list(range(len(path))):
        raise TossError('Sector depth/parent mismatch')
    return path


def build_index(sectors, memberships):
    """Keep all genuine branches. Remove ancestors only within their own branch.

    Multiple deepest branches have no invented primary industry: callers fall
    back to provider industry for grouping, while retaining Toss memberships.
    """
    nodes = {str(s['sectorId']):s for s in sectors}
    if len(nodes) != len(sectors):
        raise TossError('Duplicate sector ids')
    for sid in nodes:
        lineage(sid,nodes)
    out = {'kr':{},'us':{}}
    for market, kind, sid, items in memberships:
        for item in items:
            symbol = str(item['symbol'])
            key = symbol if kind == 'stock' else 'etf:' + symbol
            r = out[market].setdefault(key, {'symbol':symbol,'kind':kind,'name':item['name'],'memberships':[]})
            path = lineage(sid,nodes)
            if path not in r['memberships']:
                r['memberships'].append(path)
    for stocks in out.values():
        for r in stocks.values():
            paths = r['memberships']
            deepest = [p for p in paths if not any(len(q)>len(p) and q[:len(p)]==p for q in paths)]
            r['memberships'] = sorted(deepest,key=lambda p: '/'.join(x['id'] for x in p))
            r['ambiguous'] = len(deepest)>1
            r['primary'] = deepest[0] if len(deepest)==1 else None
    return out


def refresh(dry_run=False, max_sectors=None):
    cid, secret = os.environ.get('TOSS_CLIENT_ID'), os.environ.get('TOSS_CLIENT_SECRET')
    if not cid or not secret:
        raise TossError('Register TOSS_CLIENT_ID and TOSS_CLIENT_SECRET as Actions secrets')
    client = Client(cid,secret)
    sectors = client.get('/api/v1/sectors').get('sectors')
    if not isinstance(sectors,list) or not sectors:
        raise TossError('Empty/invalid Toss sector list; previous cache preserved')
    # Validate full hierarchy before making hundreds of membership requests.
    build_index(sectors,[])
    chosen = sectors if max_sectors is None else sectors[:max_sectors]
    memberships=[]
    for s in chosen:
        sid=str(s['sectorId'])
        for market in ('kr','us'):
            for kind,endpoint in (('stock','stocks'),('etf','etfs')):
                result=client.get(f'/api/v1/sectors/{sid}/{endpoint}',marketCountry=market.upper())
                items=result.get(endpoint)
                if not isinstance(items,list):
                    raise TossError('Invalid membership response; previous cache preserved')
                memberships.append((market,kind,sid,items))
                time.sleep(.3)  # bounded sequential requests; stop on 429, do not hammer
    index=build_index(sectors,memberships)
    counts={m:len(v) for m,v in index.items()}
    if not any(counts.values()):
        raise TossError('No membership data; previous cache preserved')
    doc={'source':'Toss official Sector API','asof':datetime.now(timezone.utc).isoformat(),
         'partial':max_sectors is not None,'sectors':sectors,'markets':index}
    if not dry_run:
        if max_sectors is not None:
            raise TossError('Partial discovery is dry-run only')
        path=config.NEWHIGH_ROOT/'toss'/'labels.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(doc,ensure_ascii=False,indent=2))
        tmp.replace(path)  # no partial overwrite on request or authentication failure
    print(f'[toss] sector read OK: {len(chosen)}/{len(sectors)} sectors; memberships={counts}; dry_run={dry_run}')
    return doc


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--max-sectors',type=int,help='연결 확인용: 일부 섹터만 조회 (dry-run 전용)')
    a=ap.parse_args()
    if a.max_sectors is not None and (not a.dry_run or not 1<=a.max_sectors<=10):
        ap.error('--max-sectors requires --dry-run and a value of 1..10')
    refresh(a.dry_run,a.max_sectors)


if __name__=='__main__':
    main()
