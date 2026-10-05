"""The Studio's explanatory dependency map. This describes the engine, never runs it.

Settings and KPI influences come from their existing catalogues. FLOW records the intermediate
calculations and conditional feedback between them. Related KPIs are deliberately NOT causal edges.
This is a subsystem-level model map, not an exhaustive static call graph or a sensitivity estimate.
"""
from __future__ import annotations

from functools import lru_cache

from utilsim.config.dependency_explanations import explain
from utilsim.config.impact import IMPACT, REACHES
from utilsim.config.model import RUN_GROUPS, SimConfig, config_schema
from utilsim.m2c.kpis import KPIS
from utilsim.ops.settings_schema import settings_schema

GROUPS = [('environment', 'Environment', 'The place, customers and weather'),
          ('operations', 'Operations', 'Teams, rules and engine calculations'),
          ('data', 'Data', 'The records those calculations produce'),
          ('metrics', 'Metrics', 'How outcomes are counted')]

# id, title, lane, topic, explanation, implementation reference
STAGES = [
    ('layout', 'Town layout', 'environment', 'Town', 'Streets, lots, buildings and construction eras.', 'utilsim/gen/pipeline.py'),
    ('households', 'Households & buildings', 'environment', 'Households', 'Occupancy, floor area, heating, solar, vehicles and appliances.', 'utilsim/gen/buildings.py'),
    ('weather', 'Daily weather', 'environment', 'Weather', 'Temperatures and storms drawn for the simulated year.', 'utilsim/sim/weather.py'),
    ('accounts', 'Customers & accounts', 'environment', 'Customers', 'Premises, service contracts, payer profiles and customer accounts.', 'utilsim/customers/generate.py'),
    ('meters', 'Meters & registers', 'environment', 'Meters', 'Service points, technologies, registers and their installation history.', 'utilsim/m2c/base.py'),
    ('usage', 'Underlying consumption', 'environment', 'Consumption', 'Energy and water demand before reading errors, estimates or billing.', 'utilsim/sim/usage.py'),
    ('network', 'Utility networks', 'operations', 'Network operations', 'Equipment, pressure, voltage and loading on the operations map.', 'utilsim/sim/flows.py'),
    ('map_incidents', 'Incidents & day crews', 'operations', 'Network operations', 'Failures, dispatch, restoration and reading rounds on the map.', 'utilsim/ops/timeline.py'),
    ('annual_outages', 'Annual interruptions', 'operations', 'Interruptions', 'The year’s storm and incident interruption model.', 'utilsim/m2c/incidents.py'),
    ('reading', 'Meter reading', 'operations', 'Meter reading', 'Scheduled reads, missed reads, no-access patterns and technology effects.', 'utilsim/m2c/run.py'),
    ('anomalies', 'Reading anomalies', 'operations', 'Anomalies', 'Synthetic leaks, meter faults and observation errors.', 'utilsim/m2c/run.py'),
    ('vee', 'Validation & estimation', 'operations', 'VEE', 'Validation thresholds, confidence, exceptions and estimation methods.', 'utilsim/m2c/run.py'),
    ('review', 'Casework & automation', 'operations', 'Casework', 'Analysts, supervisors, automation coverage, accuracy and waiting times.', 'utilsim/m2c/run.py'),
    ('billing', 'Billing & outsorts', 'operations', 'Billing', 'Tariffs, bill checks, holds, corrections and invoice creation.', 'utilsim/m2c/billing.py'),
    ('collections', 'Payments & collections', 'operations', 'Collections', 'Payer behaviour, due dates, reminders, arrangements and disconnection rules.', 'utilsim/m2c/collections.py'),
    ('contact', 'Contact centre', 'operations', 'Contact centre', 'Contact demand, channels, staffing, waits and case referrals.', 'utilsim/m2c/contact.py'),
    ('field', 'Field work', 'operations', 'Field work', 'Maintenance, field capacity, travel, emergency response and device work.', 'utilsim/m2c/fieldwork.py'),
    ('display', 'Labels & display', 'operations', 'Display', 'Presentation and default clock settings; these have no causal link to annual KPI outcomes.', 'utilsim/config/impact.py'),
    ('schedule', 'Read schedules', 'data', 'Meter reading', 'Which registers are read on each billing cycle and day.', 'utilsim/m2c/base.py'),
    ('map_interruptions', 'Map interruptions', 'data', 'Interruptions', 'The premises and time without service on an operations day.', 'utilsim/ops/timeline.py'),
    ('interruptions', 'Run interruptions', 'data', 'Interruptions', 'Customer minutes lost and service interruptions included in the annual run.', 'utilsim/m2c/run.py'),
    ('reads', 'Actual & missed reads', 'data', 'Meter reading', 'Scheduled observations, read values, missed reads and the simulation’s underlying truth.', 'utilsim/m2c/run.py'),
    ('decisions', 'VEE decisions', 'data', 'VEE', 'Flags, confidence, acceptance, estimates and classifications against truth.', 'utilsim/m2c/views.py'),
    ('cases', 'Cases & backlog', 'data', 'Casework', 'Created, assigned, resolved and outstanding clarification cases, with activity histories.', 'utilsim/m2c/views.py'),
    ('released', 'Released reads', 'data', 'Meter reading', 'Reads and estimates available for billing, including their release dates.', 'utilsim/m2c/run.py'),
    ('bills', 'Billing documents', 'data', 'Billing', 'Bill amounts, holds, rates, corrections and release dates.', 'utilsim/m2c/books.py'),
    ('invoices', 'Invoices & receivables', 'data', 'Billing', 'Issued invoices, due dates, amounts and the customer balance.', 'utilsim/m2c/books.py'),
    ('payments', 'Payments & collections records', 'data', 'Collections', 'Receipts, overdue amounts, collection stages and service disconnections.', 'utilsim/m2c/collections.py'),
    ('contacts', 'Contacts & waits', 'data', 'Contact centre', 'Answered and abandoned contacts, channels, waits, callbacks and outcomes.', 'utilsim/m2c/contact.py'),
    ('orders', 'Field orders & completions', 'data', 'Field work', 'Created work, dispatch, arrival, completion, due dates and maintenance effects.', 'utilsim/m2c/fieldwork.py'),
    ('costs', 'Meter-to-cash process cost', 'data', 'Cost', 'Recorded clarification and billing activity costs, plus read costs. Contact-centre and field-work cost breakdowns are reported separately.', 'utilsim/m2c/views.py'),
    ('carry', 'Delayed-work & receivable carry', 'data', 'Cost', 'Read and billing delays and unpaid invoices, priced at the configured carry rates.', 'utilsim/m2c/views.py'),
    ('contact_costs', 'Contact-centre cost', 'data', 'Cost', 'Staff hours, self-service and abandoned-contact costs in the contact-centre statistics.', 'utilsim/m2c/contact.py'),
    ('field_costs', 'Field labour & materials cost', 'data', 'Cost', 'Regular and overtime labour and materials in field-work statistics.', 'utilsim/m2c/fieldwork.py'),
    ('day_metrics', 'Operations-day outcomes', 'metrics', 'Operations day', 'Restoration times, response targets and customer minutes lost on the operations map. These remain separate from annual run measures until interruptions are carried into the run.', 'utilsim/ops/timeline.py'),
]

# Conditional links remain explicit: without the bridge, map operations do not silently change the year.
FLOW = [
    ('layout', 'households', 'Regenerating the town redraws households; geometry is not a calibrated usage lever.'),
    ('households', 'accounts', ''), ('households', 'usage', ''), ('households', 'network', ''),
    ('weather', 'usage', ''), ('weather', 'reading', ''), ('weather', 'annual_outages', ''),
    ('accounts', 'meters', ''), ('accounts', 'schedule', ''), ('accounts', 'collections', ''),
    ('meters', 'schedule', ''), ('meters', 'reading', ''), ('meters', 'field', ''),
    ('network', 'map_incidents', ''), ('map_incidents', 'map_interruptions', ''),
    ('map_interruptions', 'day_metrics', ''), ('map_incidents', 'day_metrics', ''),
    ('map_interruptions', 'interruptions', 'Only interruptions carried from the operations day into the run.'),
    ('annual_outages', 'interruptions', ''), ('interruptions', 'reading', ''),
    ('interruptions', 'contact', ''), ('interruptions', 'field', ''),
    ('schedule', 'reading', ''), ('usage', 'reading', ''), ('usage', 'anomalies', ''),
    ('reading', 'reads', ''), ('anomalies', 'reads', ''), ('reads', 'vee', ''),
    ('vee', 'decisions', ''), ('vee', 'cases', ''), ('decisions', 'released', ''),
    ('cases', 'review', ''), ('review', 'released', ''), ('review', 'field', 'Cases sent for field investigation.'),
    ('released', 'billing', ''), ('billing', 'bills', ''), ('bills', 'invoices', ''),
    ('billing', 'cases', 'A billing check or outsort raises a clarification case.'),
    ('invoices', 'collections', ''), ('collections', 'payments', ''),
    ('invoices', 'contact', ''), ('contact', 'contacts', ''),
    ('contacts', 'cases', 'Dispute or complaint referrals are enabled and triggered.'),
    ('contacts', 'collections', 'Contact outcomes trigger payment delay, arrangements or autopay cancellation.'),
    ('field', 'orders', ''), ('orders', 'released', 'A completed check read or meter investigation releases held work.'),
    ('orders', 'meters', 'Device work changes later reads; for example, a meter exchange or AMI conversion.'),
    ('reading', 'costs', ''), ('cases', 'costs', ''), ('bills', 'costs', ''),
    ('contacts', 'contact_costs', ''), ('orders', 'field_costs', ''),
    ('cases', 'carry', ''), ('bills', 'carry', ''), ('invoices', 'carry', ''), ('payments', 'carry', ''),
]

KPI_DATA = {
    'missed_read_share': ['reads'], 'estimated_read_share': ['released'], 'reads_released_promptly': ['cases', 'released'],
    'auto_accept_share': ['reads', 'decisions'], 'exceptions_vee': ['cases'],
    'vee_precision': ['reads', 'decisions'], 'vee_recall': ['reads', 'decisions'],
    'exceptions_all': ['cases'], 'exceptions_worked': ['cases'], 'case_backlog': ['cases'],
    'days_to_release': ['cases', 'released'], 'cases_resolved_in_time': ['cases'], 'truck_rolls_per_1000': ['cases'],
    'bills_on_time': ['bills', 'schedule'], 'invoice_timeliness': ['invoices', 'schedule'],
    'blocked_bill_share': ['bills'], 'billing_error_share': ['bills', 'usage'], 'days_to_invoice': ['invoices', 'schedule'],
    'days_to_pay': ['payments', 'invoices'], 'paid_on_time': ['payments', 'invoices'],
    'collected_share': ['payments', 'invoices'], 'overdue_share': ['payments', 'invoices'],
    'disconnections_per_1000': ['payments'], 'contact_service_level': ['contacts'], 'abandoned_share': ['contacts'],
    'contacts_per_1000': ['contacts'], 'first_contact_resolution': ['contacts'],
    'field_on_time': ['orders'], 'field_backlog_per_1000': ['orders'], 'emergency_response_min': ['orders'],
    'customer_minutes_lost': ['interruptions'], 'cost_per_account': ['costs'], 'carry_per_account': ['carry'],
}


def consumers(path, reach):
    """Owning calculation for a setting. KPI-specific influence signs are added separately."""
    group, key, *_ = path.split('.')
    if reach == 'display':
        return ['display']
    if reach == 'shape':
        return ['layout']
    if group == 'kpi':
        return []  # definition windows connect only to their own KPI, below
    if path == 'contact.service_target_s':
        return []  # counts answered calls against a target, without changing waits
    if path == 'operations.gas_response_target_min':
        return ['day_metrics']
    if cost_only(path):
        return ['contact_costs'] if group == 'contact' else ['field_costs']
    if group == 'seeds':
        return {'master': ['layout', 'households', 'weather', 'map_incidents', 'reading'], 'town': ['layout'],
                'households': ['households'], 'weather': ['weather'], 'incidents': ['map_incidents', 'annual_outages'],
                'anomalies': ['anomalies', 'reading', 'review', 'billing']}[key]
    if group == 'town':
        return ['network'] if reach == 'operations' else ['layout', 'accounts', 'households']
    if group == 'housing':
        return ['households']
    if group in ('electric', 'gas', 'water'):
        if path in ('water.lpcd', 'water.irrigation_m3_per_day'):
            return ['usage']
        if path == 'gas.all_electric_district_share':
            return ['households', 'accounts']
        if reach == 'town':
            return ['meters', 'billing']
        return ['network']
    if group == 'ami':
        return ['meters', 'reading']
    if group == 'weather':
        return ['usage'] if key in ('heating_base_c', 'cooling_base_c') else ['weather']
    if group == 'incidents':
        return ['map_incidents'] if reach == 'operations' else ['map_incidents', 'annual_outages']
    if group in ('operations', 'scenario'):
        return ['map_incidents']
    if group == 'customers_billing':
        if key in ('bill_cycles', 'mru_target_meters'):
            return ['schedule']
        if key in ('on_time_payer_share', 'late_payer_share', 'pre_authorized_share', 'due_days'):
            return ['collections']
        return ['accounts', 'meters'] if key == 'services' else ['billing']
    if group == 'process':
        if key in ('carry_rate_per_day', 'receivable_carry_ratio'):
            return ['carry']
        return ['field'] if key.startswith('field_') else ['review']
    if group == 'billing':
        return ['billing'] if key in ('rate_change_date', 'rate_change_pct', 'high_bill_ratio', 'high_bill_min',
               'first_bill_limit', 'credit_review', 'outsort_auto_release_max', 'billing_queue_worked_by',
               'trueup_max_ratio', 'data_error_rate', 'print_lag_days') else ['collections']
    if group == 'reading' and key.startswith('read_cost_'):
        return ['costs']
    return [{'anomalies': 'anomalies', 'reading': 'reading', 'vee': 'vee', 'contact': 'contact',
             'field': 'field', 'outages': 'annual_outages'}[group]]


def cost_only(path):
    return (path in ('contact.agent_cost_per_hour', 'contact.self_serve_cost', 'contact.abandon_cx_cost')
            or (path.startswith('field.') and path.rsplit('.', 1)[-1] in ('cost_per_hour', 'overtime_factor', 'materials')))


@lru_cache(maxsize=1)
def dependency_graph():
    schema = config_schema()
    defaults = SimConfig().model_dump(mode='json')
    nodes, edges = [], {}

    def add(source, target, kind, note='', reference='', direction=None):
        edges[(source, target, kind)] = {'source': source, 'target': target, 'kind': kind, 'note': note,
                                        'reference': reference, **({'direction': direction} if direction else {})}

    def resolve(prop):
        return {**schema['$defs'][prop['$ref'].split('/')[-1]], **prop} if '$ref' in prop else prop

    def setting(path, prop, default, root, parent=None):
        prop = resolve(prop)
        reach, impact = IMPACT[root]
        group = path.split('.')[0]
        lane = 'operations' if group in RUN_GROUPS or group in ('operations', 'incidents') else 'environment'
        if group == 'kpi':
            lane = 'metrics'
        node = {'id': path, 'title': prop.get('title') or path.rsplit('.', 1)[-1].replace('_', ' ').capitalize(),
                'lane': lane, 'topic': resolve(schema['properties'][group]).get('title', group), 'kind': 'setting',
                'description': prop.get('description', ''), 'impact': impact, 'reach': reach,
                'unit': prop.get('x-unit', ''), 'default': default, 'reference': 'utilsim/config/impact.py · ' + root}
        if parent:
            node['parent'] = parent
            if cost_only(path):
                node['impact'] = 'Prices this activity without changing the underlying work or its timing.'
                add(path, 'engine:field_costs', 'uses', node['impact'], 'utilsim/m2c/fieldwork.py')
            else:
                add(path, parent, 'component', 'Part of this configuration object.', 'utilsim/config/model.py')
        nodes.append(node)
        children = prop.get('properties', {})
        for key, child in children.items():
            setting(path + '.' + key, child, (default or {}).get(key), root, path)
        # Object settings are expandable; leaves reach their owning object, which reaches the calculation.
        if not parent:
            for target in consumers(path, reach):
                add(path, 'engine:' + target, 'uses', impact, 'utilsim/config/impact.py · ' + root)

    for group, prop in schema['properties'].items():
        for key, field in resolve(prop).get('properties', {}).items():
            path = group + '.' + key
            setting(path, field, defaults[group].get(key), path)
    # Day settings are separate run overrides; preserve their real request keys and the town default bridge.
    for group, prop in settings_schema()['properties'].items():
        for key, field in prop['properties'].items():
            path = 'ops.' + (key if prop.get('x-flat') else group + '.' + key)
            title = field['title'] if prop.get('x-flat') else prop['title'] + ' · ' + field['title']
            nodes.append({'id': path, 'title': title, 'lane': 'operations', 'topic': 'Operations-day settings',
                          'kind': 'setting', 'description': field.get('description') or prop.get('description', ''),
                          'impact': 'A per-day override. Annual outcomes change only through an explicit operations-to-run bridge.',
                          'default': field['default'], 'unit': field.get('x-unit', ''), 'reach': 'operations',
                          'reference': 'utilsim/ops/settings_schema.py · ' + path[4:]})
            target = 'day_metrics' if key == 'gasResponseTargetMinutes' else 'map_incidents'
            add(path, 'engine:' + target, 'definition' if target == 'day_metrics' else 'uses',
                field.get('description', ''), 'utilsim/ops/timeline.py')
            if field.get('x-town'):
                add(field['x-town'], path, 'conditional', 'Supplies the default unless overridden for this operations day.',
                    'utilsim/ops/timeline.py · TOWN_SETTINGS')
    refs = {}
    for key, title, lane, topic, description, reference in STAGES:
        refs[key] = reference
        nodes.append({'id': 'engine:' + key, 'title': title, 'lane': lane, 'topic': topic, 'kind': 'calculation' if lane == 'operations' else 'data',
                      'description': description, 'reference': reference})
    for source, target, condition in FLOW:
        add('engine:' + source, 'engine:' + target, 'conditional' if condition else 'flow', condition,
            refs[target])
    for kpi in KPIS:
        kid = 'kpi:' + kpi.id
        nodes.append({'id': kid, 'title': kpi.title, 'lane': 'metrics', 'topic': kpi.family, 'kind': 'metric',
                      'description': kpi.definition, 'formula': kpi.formula, 'unit': kpi.unit, 'better': kpi.better,
                      'related': ['kpi:' + k for k in kpi.related], 'reference': 'utilsim/m2c/kpis.py · ' + kpi.id})
        for path, direction in kpi.settings:
            add(path, kid, 'influence', 'A setting listed as influencing this KPI in the engine catalogue. The connection is not a numerical prediction of impact.',
                'utilsim/m2c/kpis.py · ' + kpi.id, direction)
        for path in kpi.thresholds:
            add(path, kid, 'definition', 'Defines this KPI’s counting window; does not change the underlying events.',
                'utilsim/m2c/kpis.py · ' + kpi.id)
        for source in KPI_DATA[kpi.id]:
            add('engine:' + source, kid, 'measure', kpi.formula, 'utilsim/m2c/kpis.py · measure')
        if 'account' in kpi.unit or 'accounts' in kpi.formula or kpi.id == 'customer_minutes_lost':
            add('engine:accounts', kid, 'measure', 'Accounts supply the denominator.', 'utilsim/m2c/kpis.py · measure')
    by_id = {node['id']: node for node in nodes}
    for edge in edges.values():
        edge['explanation'] = explain(edge, by_id)
    return {'schemaVersion': 'utility-dependencies/1.0', 'groups': [{'id': k, 'title': t, 'description': d} for k, t, d in GROUPS],
            'nodes': nodes, 'edges': list(edges.values()), 'reaches': REACHES,
            'description': 'An explanatory map of the engine’s settings, calculations, records and KPIs. Connections describe model relationships, not a measured prediction of impact. Conditional links show optional bridges and feedback. Related KPIs are not treated as causal dependencies.'}
