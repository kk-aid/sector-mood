"""Japan -> shared Toss sector IDs, with separately evidenced business reviews.

A crosswalk is our mapping, never a claim that Toss classifies Japanese stocks.
Broad / mixed industries stay under the original provider classification.
"""
import json
from functools import lru_cache
from . import config

@lru_cache(maxsize=8)
def _read(path, mtime, size):
    from pathlib import Path
    return json.loads(Path(path).read_text(encoding='utf-8'))

def read(path):
    if not path.exists(): return {}
    st=path.stat()
    return _read(str(path),st.st_mtime_ns,st.st_size)

def catalog():
    p=config.NEWHIGH_ROOT/'toss'/'labels.json'
    if not p.exists(): return {}
    st=p.stat()
    return _catalog(str(p),st.st_mtime_ns,st.st_size)

@lru_cache(maxsize=2)
def _catalog(path,mtime,size):
    from pathlib import Path
    d=read(Path(path))
    paths={}
    for market in d.get('markets',{}).values():
        for stock in market.values():
            for path in stock.get('memberships',[]):
                for i in range(1,len(path)+1):
                    branch=path[:i]
                    paths[tuple(str(n['id']) for n in branch)]=branch
    return paths

def classify(row):
    paths=catalog()
    if not paths: return None
    root=config.NEWHIGH_ROOT/'classification'/'jp'
    reviews=read(root/'business_review.json')
    code=str(row.get('name') or '').upper().removesuffix('.T')
    approved=next((r for r in reviews.get('candidates',[]) if r['code']==code and r.get('status')=='approved' and r.get('reviewed_on') and r.get('sources') and r.get('financial_basis')),None)
    if approved:
        key=(approved['common_root_id'],approved['common_industry_id'])
        path=paths.get(key)
        if not path: return None  # Unknown or changed taxonomy: do not invent IDs.
        return dict(sector=path[0]['name'],industry=path[1]['name'],subindustry=approved['proposed_subindustry'],
                    source='jp_reviewed',source_url=approved['sources'][0]['url'],reviewed_on=approved['reviewed_on'],
                    status='business_reviewed',common_path=path,business_review=approved)
    rules=read(root/'common_sectors.json')
    industry=row.get('industry') or ''
    if not industry:
        files=sorted((config.UNIVERSE_ROOT/'jp').glob('*.json'))
        if files:
            records=read(files[-1])
            old=next((r for r in records if str(r['ticker'])==code),{})
            industry=old.get('industry_en') or old.get('industry') or ''
    match=next((r for r in rules.get('rules',[]) if r['provider_industry']==industry),None)
    if match:
        path=paths.get((match['root_id'],))
        if path:
            return dict(sector=path[0]['name'],industry=config.INDUSTRY_KO.get(industry,industry),source='jp_mapped',status='provider_crosswalk',
                        common_path=path,mapping_basis=rules['basis'],reviewed_on=rules['reviewed_on'])
    return None
