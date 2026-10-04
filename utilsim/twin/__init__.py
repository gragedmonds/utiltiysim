"""The digital twin: start from the outcomes a utility knows and let the engine fill in the rest.

The forward path builds a town and a utility from settings and reads the year's KPIs off the replay. The twin runs
the other way: given what is known (customers, billers, services) and what was observed (invoice timeliness,
exceptions, estimated bills, backlog, before and after a change), it searches a small set of named levers (missed
reads, anomalies, VEE strictness, automation, pickup lag, analyst hours, field capacity) until the replayed year
reproduces the observed figures, then reports every KPI the twin shows, the levers it moved, and a setup proposal
the Studio opens like any other. See docs/TWIN.md.

- ``kpis``: the KPI dictionary, each figure pinned to one measure of a run over a window of days.
- ``levers``: the named levers and the run settings each one sets.
- ``fit``: the specification, sizing (customers to homes and districts, billers to analysts), the search, the report
  and the proposal.
"""

from utilsim.twin.fit import (
    DISTRICT_HOMES,
    HOME_LIMIT,
    TWIN_VERSION,
    KpiTarget,
    TwinSpec,
    calibration_town,
    dictionary,
    fit,
    sizing,
    staffing,
)
from utilsim.twin.kpis import KPI_BY_ID, KPIS, Kpi, Window, measure, window
from utilsim.twin.levers import LEVERS, Lever, patches

__all__ = ["DISTRICT_HOMES", "HOME_LIMIT", "KPIS", "KPI_BY_ID", "LEVERS", "TWIN_VERSION", "Kpi", "KpiTarget",
           "Lever", "TwinSpec", "Window", "calibration_town", "dictionary", "fit", "measure", "patches", "sizing",
           "staffing", "window"]
