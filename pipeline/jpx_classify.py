"""JPX monthly TSE security list: official 17 sectors / 33 industries.

Keep Japanese labels and codes alongside Korean display labels. Non-equity
products have no 17/33 codes and must never inherit an issuer's stock industry.
"""
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import argparse
import json
import os
import re
from urllib.parse import urljoin

import pandas as pd
import requests
from . import config

SOURCE = 'https://www.jpx.co.jp/markets/statistics-equities/misc/01.html'
SECTORS = dict(zip(map(str, range(1,18)), ['식품','에너지 자원','건설·자재','소재·화학','의약품','자동차·운송기기','철강·비철금속','기계','전기·정밀기기','정보통신·기타 서비스','전력·가스','운수·물류','상사·도매','소매','은행','금융(은행 제외)','부동산']))
INDUSTRIES = dict(zip(['50','1050','2050','3050','3100','3150','3200','3250','3300','3350','3400','3450','3500','3550','3600','3650','3700','3750','3800','4050','5050','5100','5150','5200','5250','6050','6100','7050','7100','7150','7200','8050','9050'], ['수산·농림업','광업','건설업','식료품','섬유제품','펄프·종이','화학','의약품','석유·석탄제품','고무제품','유리·토석제품','철강','비철금속','금속제품','기계','전기기기','운송용 기기','정밀기기','기타 제품','전기·가스업','육상운송업','해운업','항공운송업','창고·운수 관련업','정보·통신업','도매업','소매업','은행업','증권·상품선물업','보험업','기타 금융업','부동산업','서비스업']))

def cache_path():
    return config.NEWHIGH_ROOT / 'jpx' / 'labels.json'

def normalize(code):
    return str(code).strip().upper().removesuffix('.T')

def parse_frame(df):
    required = ['日付','コード','銘柄名','市場・商品区分','33業種コード','33業種区分','17業種コード','17業種区分']
    if not set(required).issubset(df.columns):
        raise ValueError('JPX columns changed; retain previous cache')
    rows = {}
    for _, r in df.fillna('-').iterrows():
        code = normalize(r['コード'])
        if not re.fullmatch(r'[0-9A-Z]{4,5}', code):
            raise ValueError(f'Unexpected JPX security code: {code}')
        if code in rows:
            raise ValueError(f'Duplicate JPX code: {code}')
        s, i = str(r['17業種コード']), str(r['33業種コード'])
        d = dict(name=str(r['銘柄名']), product=str(r['市場・商品区分']), asof=str(r['日付']))
        if s in SECTORS and i in INDUSTRIES:
            d.update(sector_code=s, industry_code=i, sector=SECTORS[s], industry=INDUSTRIES[i],
                     sector_ja=str(r['17業種区分']), industry_ja=str(r['33業種区分']), kind='stock')
        elif s == '-' and i == '-':
            d.update(kind='product')
        else:
            raise ValueError(f'Unknown JPX industry code {s}/{i}')
        rows[code] = d
    return rows

@lru_cache(maxsize=2)
def _read(path, modified, size):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def document():
    p = cache_path()
    if not p.exists():
        return {}
    st = p.stat()
    return _read(str(p), st.st_mtime_ns, st.st_size)

def lookup(code):
    return document().get('securities', {}).get(normalize(code))

def collect():
    response = requests.get(SOURCE, timeout=60); response.raise_for_status()
    links = re.findall(r'href=["\']([^"\']+data_j\.xlsx?)["\']', response.text)
    if not links:
        raise ValueError('JPX workbook link missing; retain previous cache')
    url = urljoin(SOURCE, links[0])
    response = requests.get(url, timeout=90); response.raise_for_status()
    frame = pd.read_excel(BytesIO(response.content), dtype=str)
    rows = parse_frame(frame)
    stocks = [r for r in rows.values() if r['kind']=='stock']
    if len(stocks)<3000 or len({r['sector_code'] for r in stocks})!=17 or len({r['industry_code'] for r in stocks})!=33:
        raise ValueError('Incomplete JPX workbook; retain previous cache')
    data = dict(source_url=SOURCE, download_url=url, fetched_at=datetime.now(timezone.utc).isoformat(),
                asof=max(r['asof'] for r in rows.values()), securities=rows)
    p = cache_path(); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(',',':')), encoding='utf-8'); os.replace(tmp,p)
    print(f'[jpx] asof={data["asof"]}, stocks={len(stocks)}, products={len(rows)-len(stocks)}')

if __name__ == '__main__':
    collect()
