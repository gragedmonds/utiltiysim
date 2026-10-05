"""One interactive workspace over a local utility's checkpointed runs.

Checkpoints are storage and memory boundaries, not separate user workspaces. Record ids carry their
checkpoint identity, so two P-00001 records can never be joined or acted on accidentally. All decisions
and dated changes are replayed by the existing engine; this module only combines its views.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import math
import re
import secrets
import threading
import time
from collections import OrderedDict
from typing import get_type_hints

import numpy as np
import orjson
from fastapi import HTTPException

from utilsim.m2c import pooling
from utilsim.worker.contracts import digest

REF = re.compile(r"^local-run-([a-f0-9]{64})$")
QUALIFIED = re.compile(r"^(district-\d{4,5})::(.+)$")
RECORD = re.compile(r"^[A-Z][A-Z0-9_]*-")
AVERAGES = {'avgDaysToRelease', 'avgDaysToInvoice', 'avgDaysToPay', 'medianDaysToFlag',
            'asaS', 'avgHandleMin', 'occupancyPct', 'onTimePct', 'responseMin', 'responseP90Min',
            'daysToComplete', 'utilisationPct', 'serviceLevelPct'}
IDENTITY = {'schemaVersion', 'simulationId', 'townId', 'year', 'month', 'label', 'start', 'end',
            'asOf', 'scenarioDate', 'settingsHash', 'seed', 'thresholds', 'episodes', 'weather',
            'period', 'rateChange', 'opening', 'rpaTypes', 'legend', 'page', 'pageSize'}
IDENTITY |= {'settings', 'class', 'carryRatePerDay', 'unit', 'priority', 'groups', 'labels', 'columns', 'filters'}


def qualify(value, district, key=''):
    if isinstance(value, dict):
        return {k: qualify(v, district, k) for k, v in value.items()}
    if isinstance(value, list):
        return [qualify(v, district, key) for v in value]
    if isinstance(value, str) and RECORD.match(value) and not value.startswith(('ACT-', 'EP-')) and (
            key in ('id', 'ids', 'ref', 'record', 'source', 'target', 'from', 'to', 'seriesKey') or key.endswith(('Id', 'Ids'))):
        return district + '::' + value
    return value


def unqualify(value, district):
    if isinstance(value, dict):
        return {k: unqualify(v, district) for k, v in value.items()}
    if isinstance(value, list):
        return [unqualify(v, district) for v in value]
    if isinstance(value, str) and (match := QUALIFIED.match(value)):
        if match[1] != district:
            raise ValueError('Records from different parts of the utility cannot be used in one action.')
        return match[2]
    return value


def scopes(value):
    if isinstance(value, dict):
        return set().union(*(scopes(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(scopes(v) for v in value))
    match = QUALIFIED.match(value) if isinstance(value, str) else None
    return {match[1]} if match else set()


def actions_for(actions, district):
    return [unqualify(a, district) for a in actions if scopes(a) == {district}]


def combine(values, key=''):
    """Add counts and amounts. Never add rates, dates, ids, percentiles or averages."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    first = values[0]
    if len(values) == 1 or key in IDENTITY:
        return copy.deepcopy(first)
    if key in AVERAGES:
        return None  # a distribution is required; displaying an average of averages would be false
    if isinstance(first, bool) or isinstance(first, str):
        return first
    if isinstance(first, (int, float)):
        if key in ('oldestDays',):
            return max(values)
        if key in ('precision', 'recall') or key.endswith('Pct'):
            return None
        return sum(values)
    if isinstance(first, dict):
        result = {k: combine([v.get(k) for v in values], k) for k in dict.fromkeys(k for v in values for k in v)
                  if k not in ('_pool', '_samples')}
        if 'truePositives' in result:
            tp, fp, fn = (result.get(k, 0) for k in ('truePositives', 'falsePositives', 'falseNegatives'))
            result['precision'] = tp / (tp + fp) if tp + fp else None
            result['recall'] = tp / (tp + fn) if tp + fn else None
        if 'scheduled' in result:
            for name in ('missed', 'estimated'):
                result[name + 'Pct'] = result.get(name, 0) / result['scheduled'] if result['scheduled'] else 0
        if 'anomaly' in result:
            result['recall'] = result['flagged'] / result['reads'] if result['reads'] else None
        if 'exception' in result:
            result['precision'] = result['real'] / result['cases'] if result['cases'] else None
        if 'abandonedPct' in result:
            denominator = result['abandoned'] + result['answered']
            result['abandonedPct'] = result['abandoned'] / denominator if denominator else 0
        if 'compliancePct' in result:
            result['compliancePct'] = result['onTime'] / result['dueByNow'] if result['dueByNow'] else None
        if 'availableHours' in result:
            result['utilisationPct'] = result['busyHours'] / result['availableHours'] if result['availableHours'] else None
        for field in {k for v in values for k in v.get('_pool', {})}:
            pairs = [v['_pool'][field] for v in values if field in v.get('_pool', {})]
            denominator = sum(n for _, n in pairs)
            result[field] = sum(s for s, _ in pairs) / denominator if denominator else None
        for field in {k for v in values for k in v.get('_samples', {})}:
            samples = [s for v in values for s in v.get('_samples', {}).get(field, [])]
            result[field] = round(float(np.percentile(samples, 90 if field == 'responseP90Min' else 50)), 1) if samples else None
        return result
    if isinstance(first, list):
        flat = [x for v in values for x in v]
        if not flat:
            return []
        if isinstance(flat[0], dict):
            field = next((k for k in ('month', 'id', 'anomaly', 'exception', 'date', 'type') if k in flat[0]), None)
            if field:
                groups = {}
                for row in flat:
                    groups.setdefault(row[field], []).append(row)
                return [combine(group) for group in groups.values()]
        if key == 'status':
            return flat
        if all(isinstance(x, (int, float)) for x in flat) and len({len(v) for v in values}) == 1:
            return [sum(items) for items in zip(*values, strict=True)]
        return list(dict.fromkeys(flat)) if all(isinstance(x, str) for x in flat) else flat
    return first


class UtilityWorkspace:
    def __init__(self, jobs):
        self.jobs = jobs
        self.lock = threading.RLock()
        self.cache = OrderedDict()
        self.progress = None
        self.control_lock = threading.Lock()
        self.requests = {}
        self.active_request = None
        self.analysis_timings = []
        self.analysis_path = jobs.store / 'analysis-timings.json'
        try:
            saved = orjson.loads(self.analysis_path.read_bytes())
            if isinstance(saved, list):
                self.analysis_timings = [s for s in saved if isinstance(s, dict) and isinstance(s.get('key'), str) and
                                        all(isinstance(s.get(k), (int, float)) and math.isfinite(s[k]) and s[k] > 0
                                            for k in ('seconds', 'homes', 'months'))][-100:]
        except (OSError, ValueError):
            pass

    def status(self):
        from utilsim.worker.estimates import progress_estimate
        current = self.progress
        if current is None:
            return None
        elapsed = max(0, time.monotonic() - self.part_started)
        active = self.active_request
        progress = {**current, 'activeSeconds': round(elapsed),
                    'analysisId': active[0] if active else None,
                    'stopping': active[2].is_set() if active else False}
        if self.seconds_per_home is not None:
            remaining = self.seconds_per_home * (progress['totalHomes'] - progress['completedHomes']) - elapsed
            progress.update(etaSeconds=round(remaining) if remaining > 0 else None,
                            overrun=remaining <= 0, etaSource='live')
        return progress_estimate(progress, self.analysis_initial)

    def link(self, job_id, params):
        from utilsim.batch import write_json
        selection = {k: v for k, v in params.items() if k not in ('page', 'pageSize')}
        data = self.query(job_id, '/m2c/table', {**selection, 'pageSize': 1})
        token = secrets.token_hex(32)
        directory = self.jobs.store / 'export-links'
        directory.mkdir(exist_ok=True)
        write_json(directory / (token + '.json'), {'job': job_id, 'params': selection})
        return {'total': data['total'], 'pageSize': {'csv': 5000, 'json': 1000},
                'pages': {k: max(1, (data['total'] + n - 1) // n) for k, n in [('csv', 5000), ('json', 1000)]},
                'paths': {k: '../utility-export/' + token + '.' + k + '?page=1' for k in ('csv', 'json')}}

    def export(self, token, format, page):
        if not re.fullmatch(r'[a-f0-9]{64}', token) or format not in ('csv', 'json') or page < 1:
            raise HTTPException(404, 'No such export.')
        file = self.jobs.store / 'export-links' / (token + '.json')
        if not file.is_file():
            raise HTTPException(404, 'No such export.')
        link = orjson.loads(file.read_bytes())
        return self.query(link['job'], '/m2c/table', {**link['params'], 'page': page, 'pageSize': 5000 if format == 'csv' else 1000})

    def snapshot(self, ref):
        match = REF.fullmatch(ref)
        if not match:
            return None
        path = self.jobs.store / 'runs' / match[1] / 'snapshot.json.gz'
        if not path.is_file():
            raise HTTPException(404, 'This local run is no longer in the library.')
        return orjson.loads(gzip.decompress(path.read_bytes()))

    def call(self, path, data):
        from api import _kpis, _m2c

        routes = [r for r in (*_m2c.router.routes, *_kpis.router.routes)
                  if r.path == '/api' + path and 'POST' in r.methods]
        if len(routes) != 1 or path.endswith(('/link', '.csv', '/dispositions', '/export')):
            raise ValueError('This workspace query is not supported.')
        route = routes[0]
        req = get_type_hints(route.endpoint)['req'].model_validate(data)
        if path == '/m2c/kpis':
            from utilsim.m2c.kpis import KPI_IDS, measure
            if set(req.kpis or []) - KPI_IDS:
                raise ValueError('Unknown KPI.')
            stats = {}
            result = measure(_m2c.run_for(req), req.asOf, req.kpis, statistics=stats)
            return {**result, '_statistics': stats}
        response = route.endpoint(req)
        result = orjson.loads(response.body)
        if path in ('/m2c/trend', '/m2c/contact', '/m2c/fieldwork', '/m2c/summary', '/vee/scorecard', '/process/costs'):
            result = pooling.attach(path, result, _m2c.run_for(req), data)
        return result

    def stop(self, analysis_id):
        """Cancel the visible analysis and requests already waiting for the same utility.

        The control lock is separate from the engine lock so Stop never waits for a run.
        A stale button cannot cancel a later analysis.
        """
        with self.control_lock:
            active = self.active_request
            if not active or active[0] != analysis_id:
                return False
            for job_id, signal in self.requests.values():
                if job_id == active[1]:
                    signal.set()
            return True

    def query(self, job_id, path, params):
        from utilsim.cancellation import cancellable, check_cancelled
        request_id, signal = secrets.token_hex(16), threading.Event()
        with self.control_lock:
            self.requests[request_id] = (job_id, signal)
        try:
            with self.lock, cancellable(signal):
                with self.control_lock:
                    self.active_request = (request_id, job_id, signal)
                check_cancelled()
                return self._query_request(job_id, path, params)
        finally:
            with self.control_lock:
                self.requests.pop(request_id, None)
                if self.active_request and self.active_request[0] == request_id:
                    self.active_request = None

    def _query_request(self, job_id, path, params):
        if not isinstance(params, dict):
            raise ValueError('Expected workspace query parameters.')
        with self.lock:
            job = self.jobs.find(job_id)
            if not job or job['status'] != 'complete':
                raise HTTPException(409, 'Finish the first run to open its interactive results.')
            key = digest([job_id, path, params])
            if key in self.cache:
                self.cache.move_to_end(key)
                return copy.deepcopy(self.cache[key])
            try:
                started = time.monotonic()
                profile = digest([path, job['recipeKey'], {k: v for k, v in params.items()
                                 if k not in ('page', 'pageSize', 'asOf')}])
                self.analysis_recipe = {**job['recipe'], 'request': {**job['recipe']['request'], **params}}
                from utilsim.worker.estimates import analysis_estimate, months_in
                self.analysis_initial = analysis_estimate(self.analysis_recipe, profile, self.analysis_timings)
                result = pooling.strip(self._query(job, path, params))
                from utilsim.cancellation import check_cancelled
                check_cancelled()  # Never cache a partial/cancelled response or learn its duration.
                self.analysis_timings.append({'key': profile, 'seconds': time.monotonic() - started,
                                             'homes': self.analysis_recipe['homes'],
                                             'months': months_in(self.analysis_recipe['request'])})
                self.analysis_timings = self.analysis_timings[-100:]
                try:
                    from utilsim.batch import write_json
                    write_json(self.analysis_path, self.analysis_timings)
                except OSError:
                    pass  # An optional timing cache must never lose a completed analysis.
                self.cache[key] = result
                while len(self.cache) > 12:
                    self.cache.popitem(last=False)
                return copy.deepcopy(result)
            finally:
                self.progress = None

    def _query(self, job, path, params):
        from utilsim.worker.prepare import seeded_episodes

        if not isinstance(params, dict):
            raise ValueError('Expected workspace query parameters.')
        params = copy.deepcopy(params)
        params = seeded_episodes(params, job['recipe']['modelId'])
        explicit_actions = 'actions' in params
        actions = params.pop('actions', [])
        for action in actions:
            if len(scopes(action)) != 1:
                raise ValueError('Each decision must identify a record in this utility.')
        scope = scopes({k: v for k, v in params.items() if k not in ('previous', 'outages')})
        parts = job['result']['districts']
        if scope:
            parts = [p for p in parts if p['id'] in scope]
            if len(parts) != 1 or len(scope) != 1:
                raise ValueError('Select records from one part of this utility.')
        known = {p['id'] for p in job['result']['districts']}
        if any(not scopes(a) <= known for a in actions):
            raise ValueError('A decision refers to a different utility.')
        outputs = []
        page, size = max(1, int(params.get('page', 1))), min(5000, max(1, int(params.get('pageSize', 50))))
        list_paths = {'/process/queue', '/m2c/table', '/m2c/collections', '/m2c/outage-followup',
                      '/m2c/collector-groups', '/m2c/possible-entries'}
        paged = path in list_paths
        audit = path == '/m2c/table' and params.get('table') == 'billingAudit'
        total_homes = sum(p['homes'] for p in parts)
        self.analysis_recipe['homes'] = total_homes
        self.analysis_initial['estimatedTotalSeconds'] *= total_homes / self.analysis_initial['totalHomes']
        self.analysis_initial['totalHomes'] = total_homes
        began, done_homes = time.monotonic(), 0
        for index, part in enumerate(parts):
            from utilsim.cancellation import check_cancelled
            check_cancelled()
            self.part_started = time.monotonic()
            self.seconds_per_home = (self.part_started - began) / done_homes if done_homes else None
            self.progress = {'name': job['recipe']['name'], 'modelId': job['recipe']['modelId'],
                             'stage': 'Replaying your changes' if actions else 'Reading utility results',
                             'completed': index, 'total': len(parts), 'totalHomes': total_homes,
                             'completedHomes': done_homes}
            done_homes += part['homes']
            folder = self.jobs.store / 'runs' / part['runKey']
            inputs = orjson.loads((folder / 'inputs.json').read_bytes())
            request = {k: v for k, v in inputs.items() if k not in ('snapshotSha256',)}
            local = copy.deepcopy(params)
            if 'previous' in local:
                local['previous'] = [{**p, 'actions': actions_for(p.get('actions', []), part['id']),
                                      'outages': self.outages_for(p.get('outages', []), part['id'])}
                                     for p in local['previous'] or []]
            if 'outages' in local:
                local['outages'] = self.outages_for(local['outages'], part['id'])
            request.update(unqualify(local, part['id']))
            if audit:
                # Select whole-utility totals, never partition-local amounts, before filtering/projection.
                request.update(columns=None, filters=None, search=None)
            if path == '/m2c/table' and request.get('columns') and request.get('sort') and request['sort'] not in request['columns']:
                request['columns'] = [*request['columns'], request['sort']]
            request['town'] = 'local-run-' + part['runKey']
            request['actions'] = actions_for(actions, part['id']) if explicit_actions else inputs.get('actions', [])
            # The run seed is already derived for each checkpoint. Never re-roll it while changing a date or action.
            source_seed = params.get('seed', job['recipe']['request'].get('seed'))
            request['seed'] = (inputs['seed'] if (source_seed or None) == (job['recipe']['request'].get('seed') or None)
                               else hashlib.sha256(f"{source_seed}:{part['id']}".encode()).hexdigest()[:32] if source_seed else None)
            from api._m2c import RunRequest
            normalized = RunRequest.model_validate(request).model_dump(by_alias=True)
            original = RunRequest.model_validate(inputs).model_dump(by_alias=True)
            from utilsim.config.model import SimConfig
            from utilsim.m2c.run import M2C_GROUPS, resolve_settings
            cfg = resolve_settings(SimConfig.model_validate(job['recipe']['config']), normalized['settings'])
            normalized['settings'] = {g: getattr(cfg, g).model_dump(mode='json') for g in M2C_GROUPS}
            for value in (normalized, original):
                value['year'] = value['year'] or 2026
                value['previous'] = value['previous'] or []
            unchanged = all(normalized[k] == original[k] for k in normalized if k != 'town')
            from utilsim.worker import archive_views
            archived = None
            if unchanged and path in ('/m2c/table', '/process/queue'):
                selector = archive_views.table_page if path == '/m2c/table' else archive_views.worklist_page
                archived = selector(folder, {**request, 'asOf': normalized['asOf']}, 12 if audit else page * size)
            saved = {'/m2c/trend': 'trend.json', '/vee/scorecard': 'scorecard.json',
                     '/m2c/summary': 'summaries/' + str(request.get('asOf')) + '.json'}.get(path)
            pooled_file = folder / 'utility-views.json.gz'
            if archived is not None:
                result = archived
            elif unchanged and path in ('/m2c/trend', '/m2c/summary', '/vee/scorecard', '/m2c/kpis') and pooled_file.is_file() and not params.get('since'):
                result = orjson.loads(gzip.decompress(pooled_file.read_bytes()))[path]
                if path == '/m2c/summary' and 'invoiceError' not in result.get('billing', {}):
                    result = self.call(path, request)
                if path == '/m2c/kpis':
                    from utilsim.m2c.kpis import KPI_IDS, KPIS_VERSION
                    wanted = set(params.get('kpis') or KPI_IDS)
                    if (result.get('schemaVersion') != KPIS_VERSION or not wanted <= result['values'].keys()
                            or not wanted <= result.get('_statistics', {}).keys()):
                        result = self.call(path, request)  # Older archives predate newly added figures.
                    else:
                        result['values'] = {k: v for k, v in result['values'].items() if k in wanted}
            elif len(parts) == 1 and unchanged and saved and (folder / saved).is_file() and not params.get('since'):
                result = orjson.loads((folder / saved).read_bytes())
            else:
                if paged:
                    # Only the top page*size rows of each sorted partition can reach that page globally.
                    request.update(page=1, pageSize=12 if audit else min(200, page * size))
                result = self.call(path, request)
                if paged:
                    row_key = next((k for k in ('rows', 'groups', 'entries') if isinstance(result.get(k), list)), 'rows')
                    while len(result.get(row_key, [])) < min(result.get('total', 0), page * size):
                        request['page'] += 1
                        more = self.call(path, request).get(row_key, [])
                        if not more:
                            break
                        result[row_key].extend(more)
            result = qualify(result, part['id'])
            if path == '/m2c/table':
                for row in result['rows']:
                    for i, col in enumerate(result['columns']):
                        if col.get('kind') == 'id' and isinstance(row[i], str) and RECORD.match(row[i]):
                            row[i] = part['id'] + '::' + row[i]
            outputs.append(result)
        if not outputs:
            raise ValueError('No results are available for this utility.')
        if paged:
            return self.page(outputs, path, params, page, size)
        if len(parts) == 1 and scope:
            return outputs[0]
        if path == '/m2c/kpis':
            from utilsim.m2c.kpis import KPI_BY_ID
            result = {**outputs[0], 'accounts': sum(o['accounts'] for o in outputs)}
            result['values'] = {}
            for name in outputs[0]['values']:
                vals = [o['_statistics'][name] for o in outputs]
                denominator = sum(n for _, n in vals)
                numerator = sum(v for v, _ in vals)
                result['values'][name] = (numerator if KPI_BY_ID[name].unit == 'count' else
                                          numerator / denominator if denominator else None)
            result.pop('_statistics', None)
            return result
        result = combine(outputs)
        result['simulationId'] = job['recipe']['modelId']
        return result

    @staticmethod
    def outages_for(outages, district):
        return [{**o, 'premiseIds': [unqualify(p, district) for p in o['premiseIds'] if scopes(p) == {district}]}
                for o in outages if any(scopes(p) == {district} for p in o['premiseIds'])]

    @staticmethod
    def page(outputs, path, params, page, size):
        result = copy.deepcopy(outputs[0])
        row_key = next((k for k in ('rows', 'groups', 'entries') if isinstance(result.get(k), list)), 'rows')
        rows = [r for o in outputs for r in o.get(row_key, [])]
        audit = path == '/m2c/table' and params.get('table') == 'billingAudit'
        if audit:
            month_col = next(i for i, c in enumerate(result['columns']) if c['key'] == 'month')
            months = {}
            for row in rows:
                key = row[month_col]
                if key not in months:
                    months[key] = list(row)
                else:
                    months[key] = [v if i == month_col else round(v + row[i], 2) for i, v in enumerate(months[key])]
            rows = [months[m] for m in sorted(months)]
            audit_rows = len(rows)
            from utilsim.m2c.tables import BILLING_AUDIT, Table, select
            data = [list(col) for col in zip(*rows, strict=True)] if rows else [[] for _ in BILLING_AUDIT]
            table = Table(BILLING_AUDIT, data, {}, [''] * len(rows))
            rows = [rows[i] for i in select(table, search=params.get('search'), filters=params.get('filters'))]
            result.update(search=params.get('search') or '', filters=params.get('filters') or {})
        audit_total = len(rows) if audit else None
        if path == '/m2c/table':
            col = next((i for i, c in enumerate(result['columns']) if c['key'] == params.get('sort')), None)
            if col is not None:
                from utilsim.m2c.tables import _sort_key
                sort_key = _sort_key(result['columns'][col]['kind'])
                rows = sorted([r for r in rows if r[col] is not None], key=lambda r: sort_key(r[col]),
                              reverse=bool(params.get('desc'))) + [r for r in rows if r[col] is None]
            result['rowsInTable'] = sum(o.get('rowsInTable', 0) for o in outputs)
            result['facets'] = {}
            for name in {k for o in outputs for k in o.get('facets', {})}:
                counts = {}
                for output in outputs:
                    for facet in output.get('facets', {}).get(name, []):
                        counts[facet['value']] = counts.get(facet['value'], 0) + facet['count']
                result['facets'][name] = [{'value': v, 'count': n} for v, n in sorted(counts.items(), key=lambda x: (-x[1], str(x[0])))]
        elif path == '/process/queue':
            field = {'age': 'ageDays', 'impact': 'impact', 'confidence': 'confidence', 'created': 'createdAt'}.get(params.get('sort', 'age'), 'ageDays')
            if field == 'createdAt':
                rows.sort(key=lambda r: r.get('caseId', ''))
                rows.sort(key=lambda r: r.get('createdAt', ''), reverse=True)
            else:
                rows.sort(key=lambda r: ((r.get(field) if r.get(field) is not None else -1)
                                         * (1 if field == 'confidence' else -1), r.get('caseId', '')))
        elif path == '/m2c/collections':
            date = {'overdue': 'oldestDueAt', 'disconnect': 'noticeAt', 'moratorium': 'heldAt', 'rejected': 'rejectedAt'}.get(params.get('list'), 'createdAt')
            rows.sort(key=lambda r: (r.get('invoiceId', ''), r.get('accountId', '')))
            if params.get('sort') == 'amount':
                rows.sort(key=lambda r: r.get('overdue', r.get('amount', r.get('outstanding', 0))), reverse=True)
            else:
                rows.sort(key=lambda r: r.get(date) or '', reverse=params.get('sort') == 'created')
        elif path == '/m2c/collector-groups':
            rows.sort(key=lambda r: (r['day'], r['cases'], r['collectorId']), reverse=True)
            result['collectors'] = [c for o in outputs for c in o.get('collectors', [])]
        elif path == '/m2c/outage-followup':
            rows.sort(key=lambda r: r.get('outageId', ''))
            rows.sort(key=lambda r: r.get('start') or '', reverse=True)
            result['groups'] = [g for o in outputs for g in o.get('groups', [])]
        result.update({row_key: rows[(page-1)*size:page*size], 'page': page, 'pageSize': size,
                       'total': audit_total if audit else sum(o.get('total', len(o.get(row_key, []))) for o in outputs)})
        if audit:
            result['rowsInTable'] = audit_rows
        if path == '/m2c/table' and params.get('columns'):
            columns = [next(i for i, c in enumerate(result['columns']) if c['key'] == k) for k in params['columns']]
            result['columns'] = [result['columns'][i] for i in columns]
            result['rows'] = [[r[i] for i in columns] for r in result['rows']]
        return result
