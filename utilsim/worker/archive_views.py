"""Select finished tables and worklists without replaying their simulation."""
from __future__ import annotations

import gzip

import orjson

from utilsim.m2c import catalog, tables, views


def read(path):
    return orjson.loads(gzip.decompress(path.read_bytes()))


def table_page(folder, request, limit):
    name = request.get('table')
    if name not in tables.BY_NAME:
        raise ValueError('Unknown table.')
    path = folder / 'tables' / (name + '.json.gz')
    if not path.is_file():
        return None
    saved = read(path)
    if saved['asOf'] != request['asOf']:
        return None
    cols = [tables.Col(**c, search=i in saved['searchColumns']) for i, c in enumerate(saved['columns'])]
    data = [list(col) for col in zip(*saved['rows'])] if saved['rows'] else [[] for _ in cols]
    search_cols = [data[j] for j, c in enumerate(cols) if c.search]
    blob = [' '.join(tables._text(v) for v in row).lower() for row in zip(*search_cols)] if search_cols else [''] * len(saved['rows'])
    table = tables.Table(cols, data, saved['facets'], blob)
    idx = tables.select(table, **{k: request.get(k) for k in ('search', 'filters', 'sort', 'desc')})
    js = tables._columns(table, request.get('columns'))
    return {**{k: saved[k] for k in ('simulationId', 'asOf', 'table', 'title', 'group', 'source', 'description')},
            'schemaVersion': tables.TABLE_VERSION, 'columns': [cols[j].json() for j in js],
            'rows': [[data[j][i] for j in js] for i in idx[:limit]], 'total': len(idx), 'rowsInTable': table.n,
            'page': 1, 'pageSize': limit, 'facets': table.facets, 'sort': request.get('sort'),
            'desc': bool(request.get('desc')), 'search': request.get('search') or '', 'filters': request.get('filters') or {}}


def worklist_page(folder, request, limit):
    status, sort = request.get('status', 'open'), request.get('sort', 'age')
    queue, category, assignee = (request.get(k) for k in ('queue', 'category', 'assignee'))
    if status not in ('open', 'resolved', 'all') or sort not in views.SORTS:
        raise ValueError('Unknown worklist status or sort.')
    if queue is not None and queue not in catalog.QUEUES:
        raise ValueError('Unknown queue.')
    if category is not None and category not in (*catalog.CATEGORIES, *catalog.NO_ENGINE_CATEGORIES, catalog.MY_CASES):
        raise ValueError('Unknown category.')
    asked = category
    if category == catalog.MY_CASES:
        category, assignee = None, assignee or 'you'
    date = request['asOf']
    # Dates come from the validated RunRequest, never a raw filename.
    path = folder / 'worklists' / (date + '.all.json.gz')
    if not path.is_file():
        if status != 'open':
            return None
        path = folder / 'worklists' / (date + '.json.gz')
    if not path.is_file():
        return None
    saved = read(path)
    rows = []
    needle = (request.get('search') or '').strip().lower()
    for row in saved['rows']:
        if category in catalog.NO_ENGINE_CATEGORIES:
            break
        done = row['resolvedAt'] is not None
        if (status == 'open' and done) or (status == 'resolved' and not done):
            continue
        if any(want and row.get(key) != want for key, want in (
                ('queue', queue), ('category', category), ('assignee', assignee), ('type', request.get('type')),
                ('commodity', request.get('commodity')), ('collectorId', request.get('collector')))):
            continue
        if request.get('createdOn') and row['createdAt'][:10] != request['createdOn']:
            continue
        if needle and needle not in ' '.join(str(row.get(k, '')) for k in ('caseId', 'address', 'premiseId', 'accountId', 'meterId', 'orderId')).lower():
            continue
        rows.append(row)
    rows.sort(key=lambda r: r['caseId'])
    field = {'age': 'ageDays', 'impact': 'impact', 'confidence': 'confidence', 'created': 'createdAt'}[sort]
    rows.sort(key=lambda r: r[field] if r[field] is not None else -1, reverse=sort != 'confidence')
    return {'schemaVersion': 'm2c-worklist/1.0', 'simulationId': saved['simulationId'], 'asOf': date,
            'queue': queue, 'category': asked, 'status': status, 'sort': sort, 'total': len(rows),
            'page': 1, 'pageSize': limit, 'rows': rows[:limit],
            **{k: request[k] for k in ('collector', 'createdOn') if request.get(k)}}
