"""Reclassify stored site pages without fetching prices or sending notifications.
Historical returns remain unchanged; grouping uses today's classification.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import statistics

from . import config
from .taxonomy import profile, reviewed_rows, toss_rows, labels_from_profile


def refresh(market):
    reviewed = reviewed_rows()
    root = config.DATA_ROOT / market / 'newhigh'
    pages = [(p, json.loads(p.read_text(encoding='utf-8'))) for p in sorted(root.glob('20*.json'))]
    known = {}
    counts = Counter()
    for _, page in pages:
        for stock in page['stocks']:
            code = stock['code']
            row = {'name': code, 'industry': stock.get('industry'), 'sector': None,
                   'market_cap_basic': None if stock.get('mcap') is None else stock['mcap'] * 1e8}
            p = profile(row, market, reviewed=reviewed)
            stock.setdefault('provider_label', stock['label'])
            if p['source'] in ('toss', 'reviewed', 'unmapped', 'jpx', 'jpx_product', 'jpx_unmapped'):
                stock['label'] = p['industry']
            else:
                stock['label'] = p['industry'] if stock.get('industry') else stock['provider_label']
            stock['classification'] = p
            stock['labels'] = labels_from_profile(p)
            known[code] = stock['label']
            counts[p['source']] += 1
    records = []
    for path in sorted((config.NEWHIGH_ROOT / market).glob('*.csv')):
        with path.open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            fields, rows = reader.fieldnames, list(reader)
        for row in rows:
            code = row['code']
            p = profile({'name': code}, market, reviewed=reviewed)
            row['label'] = p['industry'] if p['source'] in ('toss', 'reviewed', 'unmapped', 'jpx', 'jpx_product', 'jpx_unmapped') else known.get(code, row['label'])
            row['labels'] = json.dumps(labels_from_profile(p), ensure_ascii=False)
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(fields + ['labels'])))
            writer.writeheader()
            writer.writerows(rows)
        records.extend(rows)
    from .newhigh_enrich import cumulative, CLUSTER_MIN
    for path, page in pages:
        today = page['day']
        # The stored page may exist without a corresponding CSV record.
        history = [r for r in records if r['date'] != today]
        history += [{'date': today, 'code': s['code'], 'label': s['label'], 'labels': s['labels']} for s in page['stocks']]
        cum = cumulative(history, today)
        groups = defaultdict(list)
        for s in page['stocks']:
            for label in s['labels']:
                groups[label].append(s)
        page['clusters'] = sorted([
            {'label': label, 'n': len(stocks), 'n5': len(cum[5].get(label, ())),
             'n20': len(cum[20].get(label, ())),
             'codes': [s['code'] for s in sorted(stocks, key=lambda x: -x['change'])]}
            for label, stocks in groups.items()
            if len(stocks) >= CLUSTER_MIN or len(cum[5].get(label, ())) >= CLUSTER_MIN * 2
        ], key=lambda c: (-c['n'], -c['n5']))
        for w in (5, 20):
            page[f'cum{w}'] = {k: len(v) for k, v in cum[w].items()}
        for row in page.get('follow', []):
            p = profile({'name': row['code']}, market, reviewed=reviewed)
            if p['source'] in ('toss', 'reviewed', 'unmapped', 'jpx', 'jpx_product', 'jpx_unmapped'):
                row['label'] = p['industry']
            else:
                row['label'] = known.get(row['code'], row['label'])
        perf = defaultdict(list)
        for row in page.get('follow', []):
            p = profile({'name': row['code']}, market, reviewed=reviewed)
            row['labels'] = labels_from_profile(p)
            for label in row['labels']:
                perf[label].append(row['ret'])
        page['perf'] = {k: {'n': len(v), 'med': round(statistics.median(v), 2),
                            'hit': round(sum(x > 0 for x in v) / len(v) * 100)}
                        for k, v in perf.items() if len(v) >= 2}
        page['classification_basis'] = '현재 분류 기준 재집계'
        path.write_text(json.dumps(page, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    ip = root / 'index.json'
    if ip.exists():
        idx = json.loads(ip.read_text(encoding='utf-8'))
        idx['counts'] = {p['day']: dict(Counter(label for s in p['stocks'] for label in s['labels'])) for _, p in pages}
        idx['classification_refreshed'] = datetime.now(timezone.utc).isoformat()
        ip.write_text(json.dumps(idx, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'[classification-site:{market}] pages={len(pages)} stock appearances={dict(counts)}')


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['jp'])
    args = parser.parse_args()
    if args.market == 'jp':
        from .jpx_classify import document
        if not document().get('securities'):
            raise SystemExit('JPX cache required; no files changed')
        refresh('jp')
        return
    markets, asof = toss_rows()
    if not markets:
        raise SystemExit('Fresh, complete Toss cache required; no files changed')
    print(f'[classification-site] Toss cache asof={asof}')
    for market in ('kr', 'us'):
        refresh(market)


if __name__ == '__main__':
    main()
