"""Separate business classification, legacy theme tags and size.

Only explicit, evidence-backed reviewed rows can override provider industry.
DART candidates are never automatically promoted by this module.
"""
from __future__ import annotations
import csv
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


def profile(row, market, legacy=None, reviewed=None):
    code = str(row.get('name') or '')
    approved = (reviewed if reviewed is not None else reviewed_rows()).get((market, code))
    sector = config.SECTOR_KO.get(row.get('sector'), row.get('sector')) or '미분류'
    raw = row.get('industry') or ''
    industry = config.INDUSTRY_KO.get(raw, raw) or '미분류'
    out = {'sector': sector, 'industry': industry, 'subindustry': None,
           'themes': [], 'legacy_group': (legacy or {}).get((market, code)),
           'source': 'provider' if raw else 'unknown', 'source_url': None,
           'reviewed_on': None, 'status': 'provider_unreviewed' if raw else 'unclassified'}
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
