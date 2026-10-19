"""Separate business classification, legacy theme tags and size.

Priority: evidenced manual review > unambiguous fresh Toss hierarchy > provider industry.
DART candidates are never automatically promoted by this module.
"""
from __future__ import annotations
import csv
import json
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


def toss_rows():
    path = config.NEWHIGH_ROOT / 'toss' / 'labels.json'
    if not path.exists():
        return {}, None
    try:
        d = json.loads(path.read_text())
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
    if membership:
        primary = membership.get('primary')
        out['toss_ambiguous'] = membership.get('ambiguous', False)
        if primary:
            by_depth = {p['depth']:p['name'] for p in primary}
            out.update(sector=by_depth.get(0, sector), industry=by_depth.get(1, by_depth.get(0, industry)),
                       subindustry=by_depth.get(2), source='toss', status='provider_classified',
                       source_url='https://developers.tossinvest.com/docs', reviewed_on=None)
    if approved:
        out.update(sector=approved.get('sector') or sector, industry=approved['industry'],
                   subindustry=approved.get('subindustry') or None,
                   themes=[x.strip() for x in approved.get('themes', '').split('|') if x.strip()],
                   source='reviewed', source_url=approved['source_url'],
                   reviewed_on=approved['reviewed_on'], status='approved')
    # Size is metadata; it never replaces the business industry.
    limit = config.NEWHIGH[market]['small_cap']
    cap = row.get('market_cap_basic')
    out['size'] = '소형주' if limit and cap is not None and cap < limit else None
    return out
