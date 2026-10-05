"""Link-level documentation for the dependency atlas.

These are explanations of engine rules, not evaluated expressions or sensitivity
coefficients. Keep arithmetic alongside the implementation references, and distinguish
record inputs, configuration inputs, and indirect catalogue influences.
"""
from __future__ import annotations

from utilsim.m2c.billing_quality import METRICS as BILLING_METRICS


def rule(summary, formula='', *, steps=(), conditions=(), example='', references=(), basis='Engine rule'):
    return dict(summary=summary, formula=formula, steps=list(steps), conditions=list(conditions),
                example=example, references=list(references), basis=basis)


# Every intermediate connection is documented independently, including feedback.
FLOW_RULES = {
    ('layout', 'households'): rule('The generated lots and buildings become the premises on which household attributes are drawn.',
        steps=('Building type and construction era constrain the household and building attributes.',
               'Regenerating the town redraws these records; changing geometry is not a calibrated consumption adjustment.'),
        references=('utilsim/gen/buildings.py',)),
    ('households', 'accounts'): rule('Premises supply the service locations for customers, accounts and utility contracts.',
        steps=('Customer generation attaches the applicable services and contracts to those premises.',
               'An account can cover more than one service; homes and accounts are not interchangeable counts.'),
        references=('utilsim/customers/generate.py',)),
    ('households', 'usage'): rule('Occupants, floor area, heating type, appliances and occupancy determine the baseline demand profile.',
        'base electricity (kWh/day) = (4 + 0.03 × floor area + 1.5 × occupants) × occupancy factor',
        steps=('The occupancy factor is 1 when occupied and 0.12 otherwise for this electric base load.',
               'Heating, cooling, EVs, pools and solar add their own terms. Water and gas have separate equations.'),
        references=('utilsim/sim/usage.py · monthly_typical_day',)),
    ('households', 'network'): rule('The connected premises and their estimated loads feed the network flow model.',
        steps=('Loads are aggregated onto connected electrical, gas and water equipment.',
               'The model uses these demands to calculate loading, service voltage and pressure on the operations map.'),
        references=('utilsim/sim/flows.py',)),
    ('weather', 'usage'): rule('Temperature drives heating and cooling demand before the meter observes consumption.',
        'daily heating demand = building heat-loss coefficient × monthly mean heating degrees per day',
        steps=('Building heat loss uses floor area and construction era.',
               'Heating technology converts heat demand to electricity or gas; cooling demand uses the monthly mean cooling degrees per day.'),
        references=('utilsim/sim/usage.py · monthly_typical_day',)),
    ('weather', 'reading'): rule('Cold weather increases the probability that a scheduled read is missed.',
        'cold = clamp((−10 − temperature °C) / 10, 0, 1.5)\nmiss probability = min(1, base miss probability × (1 + cold))',
        steps=('The base probability depends on AMI, AMR or manual reading and repeat no-access history.',
               'A deterministic draw is compared with this probability; outages, dead batteries and episodes can also force a miss.'),
        references=('utilsim/m2c/run.py · _evening',)),
    ('weather', 'annual_outages'): rule('Storm-day assumptions change the annual incident draws and the interruptions they produce.',
        steps=('Storms create opportunities for overhead line faults.',
               'The annual outage model applies its storm and incident factors to the background hazard model.'),
        conditions=('Annual outages must be enabled.',), references=('utilsim/m2c/incidents.py',)),
    ('accounts', 'meters'): rule('Service contracts link customer accounts to the installations and registers they are billed for.',
        steps=('The run builds account/contract/installation mappings from the town snapshot.',
               'Service and contract dates determine the applicable account for a billing period.'),
        references=('utilsim/m2c/base.py · M2CTown.from_snapshot',)),
    ('accounts', 'schedule'): rule('A premise’s billing-cycle portion supplies its scheduled business day in each month.',
        'scheduled date = business_days_in_month[min(max(portion, 1), number_of_business_days) − 1]',
        steps=('The run carries the premise billing cycle onto its meter registers.',
               'The business-day calendar excludes weekends and Ontario holidays; an oversized portion uses the last business day.'),
        references=('utilsim/customers/calendar.py · scheduled_read_date', 'utilsim/m2c/base.py · M2CTown.from_snapshot')),
    ('accounts', 'collections'): rule('The account’s payer profile and payment method determine how its invoices enter payment and collection processing.',
        steps=('On-time, late and non-paying behaviour is assigned to customers when the town is built.',
               'Due dates and the collections rules then determine receipts, reminders, arrangements and possible disconnection.'),
        references=('utilsim/m2c/collections.py',)),
    ('meters', 'schedule'): rule('Each register inherits its premise’s read date; its technology determines the time of the read attempt.',
        'read timestamp = scheduled read day + technology-specific read hour / 24',
        steps=('The technology’s base hour is spread using a deterministic household hash.',),
        references=('utilsim/m2c/base.py', 'utilsim/m2c/run.py · _setup')),
    ('meters', 'reading'): rule('Technology and register characteristics control how consumption becomes an observed reading.',
        steps=('AMI, drive-by AMR and manual meters use different miss probabilities and attempt times.',
               'Register modulus controls rollover; device faults, batteries and communications can alter or suppress the observation.'),
        references=('utilsim/m2c/run.py · _evening',)),
    ('meters', 'field'): rule('The installed device population supplies the meters eligible for checks, exchanges and technology conversion.',
        steps=('Field-work types select eligible devices and create dated work orders.',
               'A completed device change affects later readings through the device-work feedback link.'),
        references=('utilsim/m2c/fieldwork.py',)),
    ('network', 'map_incidents'): rule('Equipment, connectivity and loading determine where failures can occur and which premises are affected.',
        steps=('Hazards use asset counts or lengths, with equipment-specific adjustments.',
               'Dispatch and restoration use network connectivity; back-feed checks use loading and voltage limits.'),
        references=('utilsim/ops/hazards.py', 'utilsim/ops/timeline.py')),
    ('map_incidents', 'map_interruptions'): rule('Fault, isolation and restoration events create service-loss intervals for the affected premises.',
        steps=('Dispatch, travel, repair and switching determine the interval boundaries.',
               'A tie restoration can end some customers’ interruptions before the original repair finishes.'),
        references=('utilsim/ops/timeline.py',)),
    ('map_interruptions', 'day_metrics'): rule('The operations-day summaries total the duration and customer impact of the day’s service interruptions.',
        'customer-minutes = Σ(affected customers × interruption minutes)',
        conditions=('These are operations-day results. They are not automatically annual-run results.',),
        references=('utilsim/ops/timeline.py',)),
    ('map_incidents', 'day_metrics'): rule('Dispatch and incident timestamps supply response and restoration measures for the operations day.',
        steps=('Gas incidents compare crew response time with the configured response target.',
               'Incident summaries also record detection, isolation, repair and restoration events.'),
        references=('utilsim/ops/timeline.py',)),
    ('map_interruptions', 'interruptions'): rule('An explicitly carried operations day contributes its service-loss intervals to the annual run.',
        steps=('The annual run consumes the carried intervals for the affected premises.',
               'Carried days replace the corresponding background outage day, avoiding duplicate incident generation.'),
        conditions=('Requires carrying the operations day into the run; merely viewing or editing the map does not do this.',),
        references=('utilsim/m2c/run.py · _setup_outages',)),
    ('annual_outages', 'interruptions'): rule('The annual hazard model converts daily incidents into dated service-loss intervals.',
        steps=('Asset type and location determine the affected premises; restoration assumptions determine duration.',
               'Annual incident consequences use their own travel/restoration model, not the map’s live crew queue.'),
        conditions=('Annual outages must be enabled. Carried operations days replace background days.',),
        references=('utilsim/m2c/incidents.py', 'utilsim/m2c/run.py · _setup_outages')),
    ('interruptions', 'reading'): rule('Service interruptions reduce delivered consumption; electricity or collector outages can also prevent an AMI read.',
        steps=('Lost service subtracts the corresponding consumption from the register advance.',
               'A dark electric AMI meter or muted collector can force a missing observation at the scheduled attempt.'),
        references=('utilsim/m2c/run.py · incident_outage', 'utilsim/m2c/run.py · _evening')),
    ('interruptions', 'contact'): rule('An incident can generate contacts from affected customers using its contact-reason probability.',
        'contact probability = min(1, reason.per_event × context multiplier × contact.volume_factor)',
        steps=('The reason and incident context determine the multiplier; the contact model then selects channel and handles the queue.',),
        references=('utilsim/m2c/contact.py',)),
    ('interruptions', 'field'): rule('Incident consequences can request emergency field response for affected premises.',
        steps=('The field model creates work with an emergency type, location and due time.',
               'Available crews and travel determine arrival; arrival is the emergency service-target milestone.'),
        references=('utilsim/m2c/fieldwork.py',)),
    ('schedule', 'reading'): rule('The read schedule decides when the engine attempts each register’s monthly reading.',
        'read timestamp = scheduled read day + read hour / 24',
        steps=('The premise billing cycle selects a business day in the month.',
               'Consumption is accumulated to that timestamp, then technology, weather, access and device conditions decide the observation.'),
        conditions=('A scheduled attempt does not guarantee a successful or released read.',),
        references=('utilsim/customers/calendar.py · scheduled_read_date', 'utilsim/m2c/run.py · _evening')),
    ('usage', 'reading'): rule('Underlying consumption supplies the true cumulative register before observation errors and misses.',
        'true register = initial register + normal consumption advance + consumption adjustments',
        steps=('Adjustments include consumption lost during interruptions and extra consumption such as leaks.',
               'The observation then applies meter behaviour, rollover and reading errors; a miss is stored as a missing value.'),
        references=('utilsim/m2c/run.py · _evening',)),
    ('usage', 'anomalies'): rule('The consumption baseline is the quantity on which injected leaks and meter faults act.',
        steps=('Physical extra usage changes truth; observation faults can change what the meter reports without making the same change to truth.',
               'The engine retains that distinction to assess VEE detection and billing error.'),
        references=('utilsim/m2c/run.py',)),
    ('reading', 'reads'): rule('Each attempted read writes the observed value and the attempt’s status into the period’s register records.',
        steps=('Successful attempts store a numeric observation; missed attempts store a missing observation.',
               'Scheduled time and true consumption remain available for validation and measurement.'),
        references=('utilsim/m2c/run.py · _evening',)),
    ('anomalies', 'reads'): rule('Injected anomalies modify the physical advance, the meter observation, or its availability.',
        steps=('Leaks affect actual usage; meter and manual-reading errors affect the observation according to their fault type.',
               'Truth labels are retained for precision/recall evaluation instead of treating every validation flag as a genuine error.'),
        references=('utilsim/m2c/run.py · _evening',)),
    ('reads', 'vee'): rule('Validation compares observed consumption with expected consumption and checks plausibility and reading history.',
        'observed consumption = current observation − previous register\nif rollover is recognised: consumption += register modulus',
        steps=('The batch supplies days, expected usage, units, occupancy, moves, prior exceptions and manual-reading status.',
               'VEE rules produce reason codes, confidence and a disposition; a missing observation follows the missing-read/estimate path.'),
        references=('utilsim/m2c/run.py · _evening', 'utilsim/m2c/vee.py')),
    ('vee', 'decisions'): rule('Validation records its reason codes, confidence and disposition for each evaluated read.',
        'confidence = clamp(1 − 2 × sum(test risks), 0, 1)',
        steps=('Register regression is rejected. Otherwise confidence at/above accept_confidence is accepted; below reject_confidence is rejected.',
               'Remaining reads escalate when impact reaches escalate_impact, or go to review otherwise.',
               'Evaluation against injected truth identifies true positives, false positives and false negatives.'),
        references=('utilsim/m2c/vee.py · run', 'utilsim/m2c/run.py · _evening')),
    ('vee', 'cases'): rule('A read that cannot pass directly opens a clarification case or joins existing held work.',
        steps=('The case stores the read period, reason, confidence and required disposition.',
               'Existing open work can keep later reads held on the same register.'),
        references=('utilsim/m2c/run.py · _evening',)),
    ('decisions', 'released'): rule('A clean accepted observation is made available to billing without analyst work.',
        'direct release: observation present AND disposition = accept AND no open case',
        steps=('This clean-read path records release at day + 18.5/24.',
               'Held reads require resolution through automation, casework or a field outcome before billing can use them.'),
        references=('utilsim/m2c/run.py · _evening',)),
    ('cases', 'review'): rule('Open, eligible cases enter the analyst, supervisor or automation workflow.',
        'analyst capacity (minutes/business day) = analysts × analyst_hours_per_day × 60',
        steps=('Assignment consumes case review time from daily capacity.',
               'Ownership, automation status, billing-queue rules and escalation determine which cases each workflow can take.'),
        references=('utilsim/m2c/run.py · _analysts',)),
    ('review', 'released'): rule('Resolving held read work writes the accepted or estimated value and its release timestamp.',
        steps=('The resolution method determines the value: accept, correct, estimate or a field-confirmed reading.',
               'Billing can proceed once all required registers for an installation’s period are released.'),
        references=('utilsim/m2c/run.py',)),
    ('review', 'field'): rule('An escalated clarification case can request a field investigation instead of being resolved at the desk.',
        steps=('Disposition and financial impact help determine escalation.',
               'The request waits for field capacity; related read cases at one premise can share a visit.'),
        conditions=('Only cases actually referred to field investigation take this path.',),
        references=('utilsim/m2c/run.py · _analysts', 'utilsim/m2c/run.py · _field')),
    ('released', 'billing'): rule('Released register values supply billable consumption for the installation and period.',
        steps=('Billing waits until every required register for the period is ready.',
               'Register differences and device adjustments produce import/export quantities; the applicable tariff prices them.'),
        references=('utilsim/m2c/books.py · bill', 'utilsim/m2c/billing.py')),
    ('billing', 'bills'): rule('Tariff calculation creates a billing document, then billing checks decide whether to release or hold it.',
        'high-bill check: total > max(high_bill_ratio × expected total, expected total + high_bill_min)',
        steps=('Other checks include true-up, rate class, first-bill limits and large credits.',
               'The document records billed, expected and true totals, its creation time, and any case/release time.'),
        references=('utilsim/m2c/books.py · bill',)),
    ('bills', 'invoices'): rule('Released, uninvoiced billing documents are grouped by account into an invoice.',
        'invoice total = Σ included document totals − applicable reversal credits',
        steps=('Invoice processing runs at 20:00 on the queued business day and respects account invoice holds.',
               'The invoice creation timestamp differs from its issue date: print lag delays issue; due days are added to issue.'),
        references=('utilsim/m2c/books.py · invoice',)),
    ('billing', 'cases'): rule('A failed billing check creates a billing clarification case and holds the document.',
        steps=('True-up, rate-class, high-bill and credit checks can trigger this path.',
               'A later release can unblock invoicing, but the document still counts as having raised a billing case.'),
        conditions=('Only documents that fail a billing check take this path.',),
        references=('utilsim/m2c/books.py · bill',)),
    ('invoices', 'collections'): rule('Invoice amount, issue date, due date and account identity start the payment and collection lifecycle.',
        'due date = issue date + customers_billing.due_days',
        steps=('Payer behaviour schedules payment; outstanding balances progress through configured reminders and collection stages.',),
        references=('utilsim/m2c/books.py · invoice', 'utilsim/m2c/collections.py')),
    ('collections', 'payments'): rule('Payment and collection events update receipts, outstanding balances and service status.',
        steps=('Records distinguish payment in full, notices, arrangements and disconnection activity.',
               'Their timestamps allow cash measures to be evaluated at the selected view date.'),
        references=('utilsim/m2c/collections.py',)),
    ('invoices', 'contact'): rule('Invoice events can generate billing-related customer contacts.',
        'contact probability = min(1, reason.per_event × context multiplier × contact.volume_factor)',
        steps=('Invoice amount and billing context select reasons such as a high bill or a billing question.',
               'The contact model samples whether the customer contacts the utility, then applies channel and queue rules.'),
        references=('utilsim/m2c/contact.py',)),
    ('contact', 'contacts'): rule('Contact demand is turned into dated self-service, answered, abandoned and repeat-contact records.',
        steps=('Self-service attempts can resolve a contact before it reaches an agent.',
               'Staffing, opening hours, handling time and customer patience determine queue wait and abandonment; outcomes can schedule callbacks or repeats.'),
        references=('utilsim/m2c/contact.py',)),
    ('contacts', 'cases'): rule('Eligible dispute and complaint outcomes create follow-up clarification cases.',
        steps=('Dispute referral uses its configured probability; repeated unresolved interactions can produce a complaint.',),
        conditions=('The corresponding dispute/complaint referrals must be enabled and their trigger must occur.',),
        references=('utilsim/m2c/contact.py',)),
    ('contacts', 'collections'): rule('Contact outcomes can change collection handling and future payment behaviour.',
        steps=('A dispute can hold collections; a resolved interaction may establish a payment arrangement.',
               'Bad experiences can trigger the configured payment-delay or autopay-cancellation feedback.'),
        conditions=('Only outcomes that trigger the enabled feedback rules change the collection path.',),
        references=('utilsim/m2c/contact.py', 'utilsim/m2c/collections.py')),
    ('field', 'orders'): rule('The field engine schedules work against crew availability and records dispatch, arrival and completion.',
        steps=('Work type supplies service duration and target; travel and available crew time determine timing.',
               'Order records retain release, creation, due, arrival and completion timestamps for service and backlog measures.'),
        references=('utilsim/m2c/fieldwork.py',)),
    ('orders', 'released'): rule('A completed check read or investigation can resolve the read work that caused the visit.',
        steps=('The field-confirmed result supplies the correction or release for held work.',
               'Other order types do not automatically release reads.'),
        conditions=('Requires a completed visit connected to held read work.',),
        references=('utilsim/m2c/run.py · _field', 'utilsim/m2c/fieldwork.py')),
    ('orders', 'meters'): rule('Completed device work changes the device state used by later readings.',
        steps=('An exchange repairs/replaces the device; an AMI conversion changes the reading technology.',
               'The change takes effect from the work outcome, not retrospectively across the whole year.'),
        conditions=('Only work types with a device effect update the meter.',),
        references=('utilsim/m2c/fieldwork.py',)),
    ('reading', 'costs'): rule('Recorded reads are priced with the cost for their reading technology.',
        'read cost = Σ(read count by technology × configured cost per read)',
        references=('utilsim/m2c/views.py',)),
    ('cases', 'costs'): rule('Case activity events accumulate the engine’s people, system and customer-effect costs.',
        'case process cost = Σ(cost of recorded case events)',
        steps=('Cost follows recorded work; analyst headcount is not simply multiplied by an annual salary in this measure.',),
        references=('utilsim/m2c/views.py',)),
    ('bills', 'costs'): rule('Billing, invoice and payment activities contribute their recorded event costs to the meter-to-cash total.',
        'process cost = case activity cost + billing/payment activity cost + read cost',
        conditions=('Contact-centre and field labour/materials are reported separately from this total.',),
        references=('utilsim/m2c/views.py',)),
    ('contacts', 'contact_costs'): rule('Contact statistics price staff time, self-service and abandoned contacts separately.',
        'contact cost = staff hours × hourly cost + self-served count × self-serve cost + abandoned count × abandonment cost + dispatch handling cost',
        steps=('Dispatch handling time is converted from seconds to hours before applying the hourly rate.',),
        references=('utilsim/m2c/contact.py · _stats',)),
    ('orders', 'field_costs'): rule('Field statistics price recorded labour and materials by crew and work type.',
        'field cost = regular labour cost + overtime labour cost + materials',
        steps=('Crew hourly rates and overtime factors price labour; the work type supplies materials per order.',),
        references=('utilsim/m2c/fieldwork.py',)),
    ('cases', 'carry'): rule('Unreleased read work accumulates delay cost from its scheduled day until resolution or the view date.',
        'case carry = Σ(max(0, end − max(scheduled day, 0)) × carry_rate_per_day)',
        steps=('End is resolution by the view date, otherwise the view date.',
               'This applies to read-holding cases, not every work-order case.'),
        references=('utilsim/m2c/views.py',)),
    ('bills', 'carry'): rule('The read periods covered by invoiced documents supply the start of the billing-delay cost.',
        'billing carry per invoice = max(0, invoice created − last scheduled read day) × carry_rate_per_day',
        steps=('The last scheduled day is taken across that invoice’s billing documents.',),
        references=('utilsim/m2c/views.py',)),
    ('invoices', 'carry'): rule('Invoice creation and issue dates mark billing delay and the start of receivable delay.',
        'receivable carry = Σ(max(0, end − max(issue date, 0)) × carry_rate_per_day × receivable_carry_ratio)',
        steps=('End is payment by the view date, otherwise the view date.',
               'This engine applies a daily cost per invoice; it does not multiply this term by the invoice balance.'),
        references=('utilsim/m2c/views.py',)),
    ('payments', 'carry'): rule('Payment in full stops the invoice’s receivable-delay clock.',
        'end of receivable delay = payment time if paid by view date; otherwise view date',
        steps=('The resulting elapsed days are priced at carry_rate_per_day × receivable_carry_ratio.',),
        references=('utilsim/m2c/views.py',)),
}


# formula, population/window detail. Measure explanations additionally name the source's role.
KPI_RULES = {
    'missed_read_share': ('missing observations ÷ scheduled attempts', 'Counts scheduled, active registers attempted by the view date; service-off periods are excluded.'),
    'estimated_read_share': ('released estimated reads ÷ scheduled attempts', 'The numerator requires estimated status and release by the view date; the denominator is the scheduled active read population.'),
    'reads_released_promptly': ('held reads released within the day window ÷ held reads released', 'Only held reads that have been released by the view date are counted. Compare floor(release timestamp) − scheduled day with kpi.read_release_days.'),
    'auto_accept_share': ('auto-accepted actual reads ÷ actual reads', 'Missing observations are excluded from the actual-read denominator.'),
    'exceptions_vee': ('VEE cases opened ÷ accounts × 1,000 × year_days / elapsed_days', 'Counts VEE cases opened year to date; the rate is annualised.'),
    'vee_precision': ('true positives ÷ (true positives + false positives)', 'Compares flagged actual reads with injected truth. A flag is not itself proof that the read was truly faulty.'),
    'vee_recall': ('true positives ÷ (true positives + false negatives)', 'Measures detection among actually faulty observed reads using injected truth.'),
    'exceptions_all': ('cases opened ÷ accounts × 1,000 × year_days / elapsed_days', 'Counts cases opened year to date and annualises the rate.'),
    'exceptions_worked': ('cases a person touched ÷ accounts × 1,000 × year_days / elapsed_days', 'Counts cases opened in the reporting window with a person-work event by the view date. Automation-only resolutions are excluded; the rate is annualised.'),
    'case_backlog': ('cases open at view date ÷ accounts × 1,000', 'An open-case snapshot, not an annualised flow. Cases resolved later still count as open at this view date.'),
    'days_to_release': ('mean(case resolved timestamp − scheduled read day)', 'Uses read-holding cases resolved in the reporting window; work-order cases are excluded. Elapsed time can include fractions of a day.'),
    'cases_resolved_in_time': ('cases resolved within the business-day window ÷ cases opened', 'Counts cases opened year to date, including unresolved cases in the denominator. The window is kpi.case_resolution_days.'),
    'truck_rolls_per_1000': ('recorded truck rolls ÷ accounts × 1,000 × year_days / elapsed_days', 'Uses the casework truck-roll count; related cases at a premise can share a visit.'),
    'bills_on_time': ('count(released by view date AND floor(released) − scheduled day ≤ kpi.on_time_bill_days) ÷ bills created', 'Counts documents created this year through the view date. Unreleased documents remain in the denominator. This uses whole calendar days.'),
    'invoice_timeliness': ('count(invoice created − last scheduled read day ≤ kpi.timely_invoice_days) ÷ invoices created', 'Counts invoices created this year through the view date. Uses elapsed calendar days, including the time of day; estimated billing can still be timely.'),
    'blocked_bill_share': ('documents with a billing case ÷ documents created', 'Counts whether a check ever raised a billing case, even if that document was subsequently released.'),
    'billing_error_share': ('Σ|released bill total − true bill total| ÷ Σ released bill total', 'True totals apply the billing calculation to underlying consumption; only bills released in the reporting window are used.'),
    'days_to_invoice': ('mean(invoice created − max(scheduled read day of each included document))', 'Counts invoices created this year through the view date. Uses elapsed calendar days, including time of day; rounds the reported mean to two decimals.'),
    'days_to_pay': ('mean(paid timestamp − issue date)', 'Uses invoices created in the reporting window and paid in full by the view date. Issue date can differ from creation because of print lag.'),
    'paid_on_time': ('invoices paid in full by deadline ÷ invoices whose deadline has passed\ndeadline = due day + kpi.payment_grace_days + 1', 'The extra day is the end-of-day boundary. Invoices not yet past that boundary are excluded from the denominator.'),
    'collected_share': ('payments received in reporting window ÷ amount invoiced in reporting window', 'Compares cash receipts with invoice amounts, not the count of paid invoices.'),
    'overdue_share': ('overdue balance at view date ÷ total receivable at view date', 'Uses outstanding money, not invoice count or total historical invoicing.'),
    'disconnections_per_1000': ('completed disconnections ÷ accounts × 1,000 × year_days / elapsed_days', 'Counts non-payment disconnections through the view date; notices alone are not disconnections.'),
    'contact_service_level': ('answered contacts with wait ≤ day’s service target ÷ answered contacts', 'Uses the target applicable on the contact’s arrival day. Abandoned contacts do not enter this denominator.'),
    'abandoned_share': ('abandoned contacts ÷ (abandoned + answered contacts)', 'Self-service contacts do not enter the queue denominator.'),
    'contacts_per_1000': ('contacts ÷ accounts × 1,000 × year_days / elapsed_days', 'Includes all recorded contact kinds, including self-service, callbacks and abandonment; the rate is annualised.'),
    'first_contact_resolution': ('contacts resolved on first attempt ÷ contacts', 'Includes self-served or answered first-time resolutions; repeat contacts are not first-time resolutions.'),
    'field_on_time': ('completed orders meeting their due time ÷ completed orders', 'Emergency orders use arrival as the milestone; other orders use completion. Open orders are outside this denominator.'),
    'field_backlog_per_1000': ('released orders not completed at view date ÷ accounts × 1,000', 'A backlog snapshot, not an annualised rate.'),
    'emergency_response_min': ('mean((crew arrival − order created) × 1,440)', 'Uses completed emergency orders. Engine timestamps are days; multiplying by 1,440 converts to minutes.'),
    'customer_minutes_lost': ('Σ interrupted customer-minutes across utilities ÷ accounts', 'Adds the run’s utility interruption totals and divides by its account count. This is not a separate per-utility average.'),
    'cost_per_account': ('meter-to-cash process cost ÷ accounts', 'Includes case/billing/payment activities and reads. Contact-centre and field labour/materials are separate reported costs.'),
    'carry_per_account': ('(case carry + billing carry + receivable carry) ÷ accounts', 'Delay days are priced by the configured carry rates; see each carry input for its start and end dates.'),
}


KPI_RULES.update({m['id']: (m['formula'], m['definition']) for m in BILLING_METRICS})

SOURCE_ROLES = {
    'accounts': 'Supplies account and supply-contract records, move dates, associations, and account-count denominators as defined by the measure.',
    'meters': 'Supplies meter, installation and service-point associations used for service setup and meter/account integrity checks.',
    'schedule': 'Supplies the scheduled read day used as the time baseline; it does not supply the eventual release or invoice timestamp.',
    'reads': 'Supplies observed/missing readings and their underlying truth and attempt status.',
    'released': 'Supplies released values, estimated status and the timestamp at which billing could use the read.',
    'decisions': 'Supplies validation acceptance/flagging and its classification against injected truth.',
    'cases': 'Supplies case type, creation, work, resolution and open/closed status at the view date.',
    'bills': 'Supplies billing-document totals, creation/release timestamps and billing-case links.',
    'usage': 'Supplies the underlying consumption used to calculate the true bill total for comparison.',
    'invoices': 'Supplies invoice amounts, included documents, creation/issue dates and due dates.',
    'payments': 'Supplies receipts, full-payment timing, collection status and remaining balances.',
    'contacts': 'Supplies contact counts, waits, channel and resolution/abandonment outcomes.',
    'orders': 'Supplies work-order creation, release, due, arrival and completion timestamps.',
    'interruptions': 'Supplies the annual run’s interrupted customer-minute totals across utilities.',
    'costs': 'Supplies the recorded meter-to-cash process-cost total.',
    'carry': 'Supplies the sum of read, billing and receivable delay costs.',
}


def explain(edge, nodes):
    """Return a complete explanation without inventing a coefficient for indirect links."""
    source, target = nodes[edge['source']], nodes[edge['target']]
    sid, tid, kind = source['id'], target['id'], edge['kind']
    pair = (sid.removeprefix('engine:'), tid.removeprefix('engine:'))
    if sid.startswith('engine:') and tid.startswith('engine:'):
        return FLOW_RULES[pair]
    if tid.startswith('kpi:'):
        kid = tid[4:]
        formula, population = KPI_RULES[kid]
        refs = ['utilsim/m2c/kpis.py · measure']
        if kid == 'invoice_timeliness':
            refs.append('utilsim/twin/kpis.py · measure')
        if kid in ('days_to_invoice', 'days_to_pay', 'paid_on_time', 'collected_share', 'overdue_share'):
            refs.append('utilsim/m2c/views.py · billing_kpis')
        if kid in {m['id'] for m in BILLING_METRICS}:
            refs.append('utilsim/m2c/billing_quality.py · measure_quality')
        if kind == 'measure':
            role = SOURCE_ROLES[sid[7:]]
            if sid == 'engine:schedule':
                role = ('Supplies each bill’s scheduled read day from its installation’s main register. The bill’s release date is compared with this baseline.'
                        if kid in ('bills_on_time', 'delayed_bill_share') else
                        'Supplies each register period’s scheduled day for identifying due reads and comparing actual observation dates.'
                        if kid in ('early_read_share', 'late_read_share', 'outstanding_reads') else
                        'Supplies the read periods used to check billing period boundaries.' if kid == 'bill_period_defect_share' else
                        'Supplies the latest scheduled read day across all documents included in the invoice. Invoice creation is measured from that baseline.')
            elif sid == 'engine:accounts' and kid not in {m['id'] for m in BILLING_METRICS}:
                role = 'Supplies the account-count denominator for the measure.'
            elif sid == 'engine:invoices' and kid in ('days_to_invoice', 'invoice_timeliness'):
                role = 'Supplies the invoice creation timestamp and its list of billing documents. The calculation compares creation with the latest scheduled read those documents cover, not with the issue date.'
            elif sid == 'engine:bills' and kid == 'bills_on_time':
                role = 'Supplies the release timestamp for each bill and the created-bill population. Bills still unreleased at the view date count as not on time.'
            example = ''
            if kid == 'bills_on_time':
                example = 'Illustration: scheduled 10 January, released 13 January at 20:00, window 3 days → on time (13 − 10 = 3 whole days).'
            elif kid in ('days_to_invoice', 'invoice_timeliness'):
                example = 'Illustration: last scheduled read 10 January, invoice created 13 January at 20:00 → 3 + 20/24 = 3.83 elapsed days.'
                example += ' A 3-day target is missed.' if kid == 'invoice_timeliness' else ' If this is the only invoice, the reported mean is 3.83 days.'
            return rule(role, formula, steps=(population,), example=example, references=refs,
                        conditions=('Measured through the selected view date. An empty share/average population is reported as no value, not zero.',)
                        if ('÷' in formula and 'accounts' not in formula) or formula.startswith('mean') else (), basis='KPI calculation')
        if kind == 'definition':
            return rule(f'{sid} supplies the comparison window or target for {target["title"]}.', formula,
                        steps=(population, 'Changing this target changes how the recorded events are counted; it does not reschedule those events.'),
                        references=refs, basis='Measurement definition')
        # The catalogue declares these as influences, not executable source-to-KPI equations.
        steps = [source.get('description', ''), source.get('impact', ''), population]
        if sid == 'billing.print_lag_days' and kid == 'days_to_invoice':
            steps = ['Print lag changes invoice issue and due dates. This KPI uses invoice creation, so print lag is not directly added to its elapsed days.', population]
        return rule(f'{source["title"]} is listed as an indirect influence on {target["title"]}.', formula,
                    steps=tuple(dict.fromkeys(s for s in steps if s)),
                    conditions=('This is a catalogue relationship, not a one-to-one arithmetic effect or a guaranteed direction of change.',),
                    references=(source['reference'], *refs), basis='Indirect influence · downstream KPI formula')
    if tid.startswith('ops.'):
        return rule(f'{sid} supplies the operations-day default for {tid[4:]}.',
                    'effective value = explicit day override, if provided; otherwise the town-derived default',
                    steps=('The default conversion is defined in TOWN_SETTINGS/run_defaults.',
                           'For tieMinVoltage the default is the town’s lower voltage limit minus 4 V.' if tid == 'ops.tieMinVoltage'
                           else 'A day override takes precedence without changing the saved town setting.'),
                    conditions=('The day’s results affect the annual run only through an explicit carried-interruption bridge.',),
                    references=('utilsim/ops/timeline.py · TOWN_SETTINGS',), basis='Default / override')
    if kind == 'component':
        detail = source.get('description') or source.get('impact', '')
        formula = ''
        refs = ['utilsim/config/model.py', source['reference']]
        if sid.startswith('contact.'):
            refs.append('utilsim/m2c/contact.py')
            formula = {'per_event': 'contact probability = min(1, reason.per_event × context multiplier × volume_factor)',
                       'per_1000': 'annual background contact rate = reason.per_1000 × volume_factor × accounts / 1,000 × 12',
                       'handle_min': 'mean handle time (seconds) = reason.handle_min × handle_factor × 60',
                       'self_serve': 'first-attempt self-service probability = min(1, reason.self_serve × self_serve_factor)'}.get(sid.rsplit('.', 1)[-1], '')
        elif sid.startswith('field.') and sid.endswith('.per_1000_premises'):
            formula = 'crew capacity = per_1000_premises × premises / 1,000'
            detail += ' Business-day crews may be fractional; on-call responders are rounded to whole crews, at least one when capacity is positive.'
            refs.append('utilsim/m2c/fieldwork.py · crews_on')
        return rule(f'{source["title"]} configures {target["title"]} through {sid}.',
                    formula,
                    steps=(detail, f'This is one field of {tid}; the containing configuration is passed to its owning engine calculation.'),
                    references=refs, basis='Configuration component')
    # Input edges retain each field's authored description AND impact, not a generic group label.
    steps = list(dict.fromkeys(s for s in (source.get('description'), source.get('impact')) if s))
    conditions = []
    formula = ''
    if sid in ('process.analysts', 'process.analyst_hours_per_day'):
        formula = 'daily analyst capacity (minutes) = process.analysts × process.analyst_hours_per_day × 60'
    elif sid in ('reading.ami_missed_read', 'reading.amr_missed_read', 'reading.manual_no_access', 'reading.no_access_repeat'):
        formula = 'miss probability = min(1, base probability × (1 + clamp((−10 − temperature °C) / 10, 0, 1.5)))'
        steps.append('This setting supplies the relevant technology/access base probability. A deterministic draw decides the miss; outages and device faults can force additional misses.')
    elif sid in ('vee.accept_confidence', 'vee.reject_confidence', 'vee.escalate_impact'):
        formula = 'confidence = clamp(1 − 2 × sum(test risks), 0, 1)'
        steps.extend(FLOW_RULES[('vee', 'decisions')]['steps'][:2])
    elif sid in ('water.lpcd', 'water.irrigation_m3_per_day'):
        formula = 'residential water m³/day = (occupants × lpcd / 1,000 + irrigation flag × irrigation rate × irrigation season + pool flag × 0.15 × pool season) × occupancy factor'
        steps.append('Flags are 0 or 1. The water occupancy factor is 1 when occupied and 0.03 otherwise; non-residential premises use separate demand assumptions.')
    elif sid.startswith('reading.read_cost_'):
        formula = 'technology read cost = recorded read count × cost per read'
    elif sid == 'contact.agent_cost_per_hour':
        formula = 'staff cost = staffed hours × agent_cost_per_hour'
    elif sid == 'contact.self_serve_cost':
        formula = 'self-service cost = self-served count × self_serve_cost'
    elif sid == 'contact.abandon_cx_cost':
        formula = 'abandonment cost = abandoned count × abandon_cx_cost'
    elif sid.endswith('.materials') and sid.startswith('field.'):
        formula = 'reported materials cost = Σ materials assigned to completed orders'
        steps.append('The work type supplies materials per order; programme bundles can scale that amount.')
    elif sid.startswith('field.') and sid.endswith(('.cost_per_hour', '.overtime_factor')):
        formula = 'labour cost = (regular minutes + overtime minutes × overtime_factor) / 60 × cost_per_hour'
    elif sid == 'contact.handle_factor':
        formula = 'mean handle time (seconds) = reason.handle_min × handle_factor × 60'
    elif sid == 'contact.self_serve_factor':
        formula = 'first-attempt self-service probability = min(1, reason.self_serve × self_serve_factor)'
    elif sid.startswith('ops.'):
        conditions.append('This override applies to the operations day. It does not directly change annual-run records.')
    if source.get('reach') == 'shape':
        conditions.append('Takes effect when the town is regenerated.')
    if tid in ('engine:costs', 'engine:contact_costs', 'engine:field_costs'):
        conditions.append('This connection prices recorded activity; the price itself does not create work or change its timing.')
    return rule(f'{sid} is read by {target["title"]}.', formula, steps=steps, conditions=conditions,
                references=(source['reference'], target['reference']), basis='Configuration input')
