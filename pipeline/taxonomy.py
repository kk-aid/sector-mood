"""Separate business classification, legacy theme tags and size.

Priority: all fresh Toss branches > evidenced manual review > explicit unmapped.
DART candidates are never automatically promoted by this module.
"""
from __future__ import annotations
import csv
import json
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from . import config

FIELDS = ['market', 'code', 'sector', 'industry', 'subindustry', 'themes',
          'source_url', 'reviewed_on', 'status']


def reviewed_rows(path: Path | None = None):
    path = path or config.NEWHIGH_ROOT / 'taxonomy.csv'
    if not path.exists():
        return {}
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    return {(r['market'], r['code']): r for r in rows
            if r.get('status') == 'approved' and r.get('industry') and r.get('source_url')
            and r.get('reviewed_on')}


@lru_cache(maxsize=2)
def _toss_document(path, modified, size):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def toss_rows():
    path = config.NEWHIGH_ROOT / 'toss' / 'labels.json'
    if not path.exists():
        return {}, None
    try:
        stat = path.stat()
        d = _toss_document(str(path), stat.st_mtime_ns, stat.st_size)
        asof = datetime.fromisoformat(d['asof'])
        age = (datetime.now(timezone.utc) - asof).total_seconds()
        if d.get('partial') or age < 0 or age > 14 * 86400:
            return {}, d.get('asof')
        return d.get('markets', {}), d.get('asof')
    except (ValueError, KeyError, TypeError):
        return {}, None


def profile(row, market, legacy=None, reviewed=None, asset="stock"):
    code = str(row.get('name') or '')
    approved = (reviewed if reviewed is not None else reviewed_rows()).get((market, code))
    sector = config.SECTOR_KO.get(row.get('sector'), row.get('sector')) or '미분류'
    raw = row.get('industry') or ''
    industry = config.INDUSTRY_KO.get(raw, raw) or '미분류'
    out = {'sector': sector, 'industry': industry, 'subindustry': None,
           'themes': [], 'legacy_group': (legacy or {}).get((market, code)),
           'source': 'provider' if raw else 'unknown', 'source_url': None,
           'reviewed_on': None, 'status': 'provider_unreviewed' if raw else 'unclassified'}
    markets, asof = toss_rows()
    lookup = 'etf:' + code if asset == 'etf' else code
    membership = markets.get(market, {}).get(lookup)
    out.update(toss_memberships=(membership or {}).get('memberships', []), toss_asof=asof)
    out['provider_sector'] = sector
    out['provider_industry'] = industry
    if market == 'jp':
        from .jpx_classify import lookup, SOURCE
        jpx = lookup(code)
        if jpx and jpx['kind'] == 'stock' and asset == 'stock':
            out.update(sector=jpx['sector'], industry=jpx['industry'], source='jpx',
                       source_url=SOURCE, status='official_classified', jpx=jpx)
        elif jpx and jpx['kind'] == 'product':
            out.update(sector='상장 상품', industry={'ETF・ETN':'ETF·ETN', 'REIT・ベンチャーファンド・カントリーファンド・インフラファンド':'리츠·벤처·국가·인프라 펀드'}.get(jpx['product'], jpx['product']), source='jpx_product',
                       source_url=SOURCE, status='official_product', jpx=jpx)
        elif approved:
            out.update(sector=approved.get('sector') or sector, industry=approved['industry'],
                       source='reviewed', source_url=approved['source_url'],
                       reviewed_on=approved['reviewed_on'], status='approved')
        else:
            out.update(sector='JPX 미등록', industry='JPX 미등록', source='jpx_unmapped', status='jpx_unmapped')
    elif membership:
        paths = membership.get('memberships', [])
        roots = list(dict.fromkeys(p[0]['name'] for p in paths if p))
        industries = list(dict.fromkeys(p[min(1,len(p)-1)]['name'] for p in paths if p))
        leaves = list(dict.fromkeys(p[-1]['name'] for p in paths if len(p)>2))
        out.update(sector=' / '.join(roots), industry=' / '.join(industries),
                   subindustry=' / '.join(leaves) or None, source='toss',
                   status='provider_classified', toss_ambiguous=len(paths)>1,
                   source_url='https://developers.tossinvest.com/docs', reviewed_on=None)
        if approved:
            out['reviewed_business'] = approved
    elif approved:
        approved_sector = approved.get('sector') or sector
        approved_sector = config.SECTOR_KO.get(approved_sector, approved_sector)
        out.update(sector=approved_sector, industry=approved['industry'],
                   subindustry=approved.get('subindustry') or None,
                   themes=[x.strip() for x in approved.get('themes', '').split('|') if x.strip()],
                   source='reviewed', source_url=approved['source_url'],
                   reviewed_on=approved['reviewed_on'], status='approved')
    elif market in ('kr','us'):
        out.update(sector='토스 미등록', industry='토스 미등록', subindustry=None,
                   source='unmapped', status='toss_unmapped')
    # Size is metadata; it never replaces the business industry.
    limit = config.NEWHIGH[market]['small_cap']
    cap = row.get('market_cap_basic')
    out['size'] = '소형주' if limit and cap is not None and cap < limit else None
    return out


def labels_from_profile(p):
    """All Toss branches; each stock occurs once per branch, never per ancestor."""
    if p['source'] == 'toss':
        return list(dict.fromkeys(' › '.join(x['name'] for x in path[:2])
                                 for path in p.get('toss_memberships', []) if path))
    return [p['industry']]
