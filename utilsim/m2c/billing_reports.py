"""Crosswalk of the user's billing report inventory to engine measures and data.

Report titles were supplied, not the Word specifications. Definitions here are explicit
model definitions; partial coverage is never presented as an exact external report replica.
"""


def report(code, title, kpis=(), table=None, status='available', note=''):
    return {'code': code, 'title': title, 'kpis': list(kpis), 'table': table, 'status': status, 'note': note}


REPORTS = (
    report('BR-ACC-01', 'Active Services', ('active_services',), 'contracts'),
    report('BR-ACC-03', 'Active MultiService Setup Improperly', ('service_setup_defects',), 'contracts', 'partial', 'Checks references, premise consistency and duplicate active contracts; organisation-specific multi-service rules are not supplied.'),
    report('BR-ACC-04', 'Move In Reporting', ('move_ins',), 'accounts'),
    report('BR-ACC-05', 'Move Out Reporting', ('move_outs',), 'accounts'),
    report('BR-ACC-06', 'Net Term Mismatch', ('net_terms_mismatch_share',), 'invoices'),
    report('BR-ACC-07', 'eBill Adoption', status='needs_data', note='Requires an account delivery preference or e-bill enrolment event. Payment method does not establish e-bill adoption.'),
    report('BR-BIL-01', 'Schedule v Actual Invoicing', ('invoice_timeliness', 'days_to_invoice', 'bills_on_time'), 'invoices'),
    report('BR-BIL-02', 'Delayed Invoices', ('delayed_bill_share',), 'invoices'),
    report('BR-BIL-03', 'Cycle Schedule', ('early_read_share', 'late_read_share'), 'readSchedules'),
    report('BR-BIL-04', 'Monthly Audit File', table='billingAudit', note='Monthly document, invoice, estimate, reversal and amount totals; downloadable through Data.'),
    report('BR-BIL-05', 'Estimated Invoices', ('estimated_bill_share',), 'invoices'),
    report('BR-BIL-06', 'First & Final Invoice Estimates', ('move_boundary_estimate_share',), 'invoices', 'partial', 'Uses issued invoices spanning recorded move boundaries. A separate first/final customer settlement process is not modelled.'),
    report('BR-BIL-07', 'Consecutively Estimated Invoices', ('consecutive_estimated_bill_share',), 'invoices'),
    report('BR-BIL-08', 'Consecutively Zero Consumption Invoices', ('consecutive_zero_bill_share',), 'invoices'),
    report('BR-BIL-09', 'Invoice Period Defects', ('bill_period_defect_share',), 'invoices'),
    report('BR-BIL-10', 'Due Date Defects', ('due_date_defect_share',), 'invoices'),
    report('BR-BIL-11', 'Corrective Invoices', ('rebill_share',), 'invoices'),
    report('BR-BIL-12', 'Multi Invoice Issuance', ('multiple_invoice_cycle_share',), 'invoices', note='Multiple invoices can be legitimate; this indicator identifies account/cycle combinations to review.'),
    report('BR-BIL-13', 'Invoices Issued without Customer Charge', ('zero_customer_charge_share',), 'invoices', 'partial', 'Audits the engine-computed fixed charge; external line-item or print omissions require the actual issued document.'),
    report('BR-BIL-14', 'Prorated Customer Charge (on MIMO)', ('move_prorated_charge_count',), 'invoices', 'partial', 'Fixed charges use actual read-period days; move-specific settlement proration is not separately modelled.'),
    report('BR-BIL-15', 'Invoices Issued without Print Date', ('invoices_pending_issue',), 'invoices', 'needs_data', 'Planned issue dates and print-lag workload are available. Actual print-completion timestamps are not recorded.'),
    report('BR-BIL-16', 'Outsorts', ('blocked_bill_share', 'active_billing_blocks'), 'billingDocuments'),
    report('BR-BIL-17', 'Exceptions (BPEMs)', ('billing_exceptions',), 'cases', 'partial', 'Uses the simulation billing-check/dispute cases, not external SAP BPEM records.'),
    report('BR-BIL-18', 'Active Billing Blocks', ('active_billing_blocks', 'active_invoice_holds'), 'billingDocuments'),
    report('BR-BIL-19', 'Accounts Invoiced without Usage (Meterless)', ('meterless_billed_accounts', 'consecutive_zero_bill_share'), 'accounts', note='Meterless account associations and zero recorded consumption are separate checks.'),
    report('BR-BIL-20', 'Active Meter Reading Blocks', ('active_reading_blocks',), 'reads', 'partial', 'Counts VEE/review holds on read release. Administrative meter-reading block flags need additional source data.'),
    report('BR-MTR-01', 'Open & Outstanding Reads', ('outstanding_reads',), 'reads'),
    report('BR-MTR-02', 'Early & Late Reads', ('early_read_share', 'late_read_share'), 'reads'),
    report('BR-MTR-03', 'Active Implausibles', ('active_implausibles',), 'cases'),
    report('BR-MTR-04', 'Active Meterless Accounts', ('active_meterless_accounts',), 'accounts'),
    report('BR-MTR-05', 'Orphaned Meters without Accounts', ('orphaned_meters',), 'meters'),
)
