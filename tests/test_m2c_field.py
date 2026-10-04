"""Field work on the meter-to-cash run, from a tester's month in the Workspace: structured field-order outcomes written
back to the case, device replacement (a backwards register stops recurring), escalations that supervisors work, one
visit per premise, orders that progress on their own, and missed reads that name their outage. Cases are found in
the run, never by id (the town packs may be regenerated)."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api._m2c import RunRequest, _town, run_for
from api.app import app
from utilsim.m2c import catalog as cat
from utilsim.m2c import lookups, views
from utilsim.m2c import orders as ords
from utilsim.m2c.calendar import calendar
from utilsim.m2c.run import ActionError, M2CRun

CAL = calendar(2026)
add_bdays = CAL.add_bdays
date_of = CAL.date_of

SLOW = {"process": {"analysts": 0, "rpa_coverage": 0}}  # nothing resolves cases but you (and supervisors, crews)


def iso(day: int) -> str:
    return date_of(day).isoformat()


def form(start: str, activity: str = "Special meter read", **kw) -> dict:
    return {"orderType": "FS01 · Field service", "shortText": "Check the meter", "plant": "SM01 · Small Town",
            "plannerGroup": "MR · Meter services", "workCenter": "METER-ELECTRIC", "activityType": activity,
            "startDate": start, "finishDate": start, "priority": "2 · Normal", "longText": "Read the meter.",
            "operation": "Read the register", "duration": 30, "accessNotes": "Front door", **kw}


def order(case_id: str, day: int, start: int, n: int = 1, cover: list[str] | None = None, **kw) -> tuple[str, list]:
    """Save, release and dispatch a field service order on ``day`` that starts on ``start``."""
    oid = f"WO-{date_of(day):%y%m%d}-{n:04d}"
    return oid, [{"day": iso(day), "type": "order_save", "sourceCaseId": case_id, "fields": form(iso(start), **kw),
                  **({"coverCaseIds": cover} if cover else {})},
                 {"day": iso(day), "type": "order_release", "orderId": oid},
                 {"day": iso(day), "type": "order_dispatch", "orderId": oid}]


@pytest.fixture(scope="module")
def town():
    return _town("small_town")


@pytest.fixture(scope="module")
def slow() -> M2CRun:
    return run_for(RunRequest(town="small_town", settings=SLOW))


@pytest.fixture(scope="module")
def missing(slow):
    """A missing-read case nobody works in the slow run (raised in spring, open all year)."""
    return next(c for c in slow.cases if c.type in ("COMM_FAIL", "NO_ACCESS") and 90 < c.created < 200
                and c.resolved is None and c.doc < 0)


@pytest.fixture(scope="module")
def crew(slow, missing):
    """An order on the missing read, dispatched two business days before its start, that nobody completes."""
    d0 = add_bdays(int(missing.created), 1)
    start = add_bdays(d0, 2)
    oid, actions = order(missing.id, d0, start)
    return {"d0": d0, "start": start, "oid": oid, "actions": actions,
            "run": run_for(RunRequest(town="small_town", settings=SLOW, actions=actions))}


# ---- orders progress on their own --------------------------------------------------------------------------------
def test_a_dispatched_order_rolls_on_its_start_date_and_the_crew_records_an_outcome(crew, missing):
    run, oid, start = crew["run"], crew["oid"], crew["start"]
    assert not run.warnings
    o = run.orders[oid]
    stages = [s for _, s, _, _ in o.stages]
    assert stages == list(ords.STAGES)  # Draft → Ready → Dispatched → En route → On site → Completed
    times = {s: t for t, s, _, _ in o.stages}
    assert int(times["En route"]) == start and 7 / 24 <= times["En route"] - start <= 9 / 24
    assert times["En route"] < times["On site"] < times["Completed"] < start + 1
    fw = o.case
    assert not [e for e in fw.events if e[1] == "TRUCK_ROLL" and e[0] < start]  # never before its basic start
    assert fw.resolved == pytest.approx(times["Completed"]) and fw.by.startswith("FIELD-")
    # The crew read the missing register: a read taken, by the crew, on the visit day.
    assert o.outcome["kind"] == "read_taken" and o.outcome["by"].startswith("FIELD-")
    assert o.outcome["date"] == iso(start) and o.outcome["value"] > 0
    view = views.order_view(run, order_id=oid, as_of=iso(start))["order"]
    assert view["stage"] == "Completed" and view["systemStatus"] == "TECO"
    assert view["outcome"]["text"].startswith("Read taken: ") and view["outcome"]["by"] == o.outcome["by"]
    assert [h["stage"] for h in view["history"]][-3:] == ["En route", "On site", "Completed"]
    assert views.order_view(run, order_id=oid, as_of=iso(start - 1))["order"]["stage"] == "Dispatched"


def test_the_outcome_is_written_back_to_the_case_and_its_check_read_releases_as_field_read(crew, missing, town):
    run, start = crew["run"], crew["start"]
    cv = views.case_view(run, missing.id, as_of=iso(start))
    out = cv["fieldOutcome"]
    assert out["kind"] == "read_taken" and out["orderId"] == crew["oid"] and out["registerId"] == town.reg_ids[missing.r]
    assert any(e["eventType"] == "ORDER_COMPLETED" for e in cv["events"])  # a field order completed step
    assert cv["orders"][0]["outcome"]["kind"] == "read_taken" and cv["resolvedAt"] is None  # the case stays open
    # The crew's outcome is final once its day is over: from the next day the check read is a decision.
    assert "check_read" not in cv["actions"]
    nxt = views.case_view(run, missing.id, as_of=iso(start + 1))
    assert "check_read" in nxt["actions"] and nxt["checkRead"]["orderId"] == crew["oid"]
    value = nxt["checkRead"]["value"]
    r, m = missing.r, missing.month
    assert value == pytest.approx(run.truth[r, m], abs=0.01)  # the visit's read, brought back to the read date
    done = M2CRun(town, SLOW, [*crew["actions"], {"day": iso(start + 1), "type": "check_read", "caseId": missing.id}])
    c = done.case_index[missing.id]
    assert c.outcome == "check_read" and done.released[r, m] == value
    rel = views.case_view(done, missing.id, as_of=iso(start + 1))["released"]
    assert rel["method"] == "field_read" and rel["by"] == "you" and rel["registerValue"] == value
    with pytest.raises(ActionError, match="no completed field order"):
        M2CRun(town, SLOW, [{"day": iso(start + 1), "type": "check_read", "caseId": missing.id}])


def test_your_outcome_replaces_the_crews_on_its_day_and_a_later_one_is_refused(crew, town):
    start, oid = crew["start"], crew["oid"]
    fw = crew["run"].orders[oid].case
    assert "order_complete" in views.case_view(crew["run"], fw.id, as_of=iso(start))["studioActions"]
    assert views.order_view(crew["run"], order_id=oid, as_of=iso(start))["order"]["completable"]
    mine = M2CRun(town, SLOW, [*crew["actions"], {"day": iso(start), "type": "order_complete", "orderId": oid,
                                                   "outcome": {"kind": "no_access"}, "note": "Locked gate"}])
    o = mine.orders[oid]
    assert o.outcome["kind"] == "no_access" and o.outcome["by"] == "you" and not mine.warnings
    assert [n for _, s, _, n in o.stages if s == "Completed"] == ["No access · Locked gate"]
    with pytest.raises(ActionError, match=r"already completed by field crew FIELD-\d at"):
        M2CRun(town, SLOW, [*crew["actions"], {"day": iso(start + 1), "type": "order_complete", "orderId": oid,
                                                "outcome": {"kind": "no_access"}}])
    assert not views.order_view(crew["run"], order_id=oid, as_of=iso(start + 1))["order"]["completable"]


@pytest.mark.parametrize(("outcome", "match"), [
    ({"kind": "fixed_it"}, "outcome.kind must be one of"),
    ({"kind": "read_taken", "date": "2026-05-06"}, r"outcome.value \(the read taken\)"),
    ({"kind": "read_taken", "value": -1, "date": "2026-05-06"}, "register value of 0 or more"),
    ({"kind": "read_taken", "value": 10, "date": "2026-05-01"}, "outcome.date .* must be from 2026-05-06"),
    ({"kind": "meter_exchanged", "installDate": "2026-05-06", "initialRead": 0}, "new device id"),
    ({"kind": "defect_found", "text": " "}, r"outcome.text \(the defect found\) is required"),
    ({"kind": "no_access", "value": 3}, "outcome no_access takes no other fields"),
])
def test_structured_outcomes_are_checked(town, outcome, match):
    oid, actions = "WO-260504-0001", [{"day": "2026-05-04", "type": "order_save", "sourceCaseId": "CASE-any",
                                       "fields": form("2026-05-06")}]
    actions += [{"day": "2026-05-04", "type": s, "orderId": oid} for s in ("order_release", "order_dispatch")]
    actions.append({"day": "2026-05-07", "type": "order_complete", "orderId": oid, "outcome": outcome})
    with pytest.raises(ActionError, match=match):
        M2CRun(town, SLOW, actions)  # checked before the year is simulated


def test_a_case_completed_while_its_order_is_open_says_so(crew, missing, town):
    d0 = crew["d0"]
    run = M2CRun(town, SLOW, [*crew["actions"], {"day": iso(d0), "type": "estimate", "caseId": missing.id}])
    assert [w for w in run.warnings if w.startswith("ACT-4 (notice): ") and crew["oid"] in w
            and "still Dispatched" in w]
    assert run.case_index[missing.id].outcome == "estimate"  # a warning, not a refusal
    assert run.orders[crew["oid"]].outcome is not None  # the crew still goes


def test_an_order_dispatched_today_is_a_crew_job_on_the_map_today(missing):
    d0 = add_bdays(int(missing.created), 1)
    oid, actions = order(missing.id, d0, d0)
    client = TestClient(app)
    tl = client.post("/api/sim/timeline", json={"town": "small_town", "date": iso(d0),
                                                "m2c": {"settings": SLOW, "actions": actions}}).json()
    job = next(j for j in tl["jobs"] if j.get("orderId") == oid)
    assert job["kind"] == "field_order" and job["requestedAt"] >= 9.5 * 3600  # 30 min after the 09:00 dispatch
    later = add_bdays(d0, 3)
    oid2, actions2 = order(missing.id, d0, later)
    for day, seen in ((d0, False), (later, True)):  # dispatched today for a later start: on the map that day only
        tl = client.post("/api/sim/timeline", json={"town": "small_town", "date": iso(day),
                                                    "m2c": {"settings": SLOW, "actions": actions2}}).json()
        assert any(j.get("orderId") == oid2 for j in tl["jobs"]) == seen


# ---- device replacement -------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def swapped(slow):
    """A backwards register from an exchange whose registration failed (a new meter the system does not know), with
    reads after it."""
    tw = slow.town
    return next(c for c in slow.cases if c.type == "REGISTER_REGRESSION" and 2 <= c.month < 10 and c.resolved is None
                and slow.fault_type[tw.meter_of[c.r]] == 3 and slow.obs[c.r, c.month] < 0.2 * slow.prev_at_read[c.r, c.month])


def test_a_device_replacement_stops_a_backwards_register_recurring(town, swapped):
    r, m = swapped.r, swapped.month
    mi = int(town.meter_of[r])
    d = add_bdays(int(swapped.created), 1)
    # Estimating it alone: the next read goes backwards again, so the case recurs every cycle.
    again = M2CRun(town, SLOW, [{"day": iso(d), "type": "estimate", "caseId": swapped.id}])
    assert any(c.r == r and c.month == m + 1 and c.type == "REGISTER_REGRESSION" for c in again.cases)
    # Registering the new device (its dial as the initial read), then estimating: later reads count from it.
    dial = again.display(r, d + 9 / 24)
    acts = [{"day": iso(d), "type": "device_replace", "meterId": town.meter_ids[mi], "deviceId": "SN-TEST-1",
             "installDate": iso(d), "initialRead": dial, "caseId": swapped.id},
            {"day": iso(d), "type": "estimate", "caseId": swapped.id}]
    fixed = M2CRun(town, SLOW, acts)
    assert not fixed.warnings
    assert not [c for c in fixed.cases if c.r == r and c.month > m and c.type == "REGISTER_REGRESSION"]
    rec = views.read_record(fixed, r, m + 1, 400.0)
    assert rec["deviceId"] == "SN-TEST-1" and rec["deviceChange"]["deviceId"] == "SN-TEST-1"
    assert rec["previousRegisterValue"] == pytest.approx(dial, abs=1e-3) and not rec["registerRegression"]
    assert rec["consumption"] == pytest.approx(fixed.truth[r, m + 1] - fixed.truth[r, m], rel=0.05, abs=1.0)
    events = views.case_view(fixed, swapped.id, as_of=iso(d))["events"]
    assert "DEVICE_REPLACED" in [e["eventType"] for e in events]
    # The installation shows the device history: the original device, then the new one (current).
    inst = lookups.installation(fixed, town.installation[r], as_of=iso(d))
    meter = next(x for x in inst["meters"] if x["meterId"] == town.meter_ids[mi])
    assert meter["deviceId"] == "SN-TEST-1" and [x["deviceId"] for x in meter["devices"]] == [town.meter_ids[mi],
                                                                                            "SN-TEST-1"]
    assert meter["devices"][-1]["current"] and meter["devices"][-1]["by"] == "you"
    assert meter["devices"][0]["removedAt"] == meter["devices"][1]["installedAt"]
    before = lookups.installation(fixed, town.installation[r], as_of=iso(d - 1))
    assert [x["deviceId"] for m_ in before["meters"] for x in m_["devices"] if m_["meterId"] == town.meter_ids[mi]] \
        == [town.meter_ids[mi]]


def test_installing_from_the_real_swap_date_makes_the_backwards_read_billable(town, swapped):
    r, m = swapped.r, swapped.month
    mi = int(town.meter_of[r])
    d = add_bdays(int(swapped.created), 1)
    with pytest.raises(ActionError, match="went backwards"):
        M2CRun(town, SLOW, [{"day": iso(d), "type": "accept", "caseId": swapped.id}])
    base = run_for(RunRequest(town="small_town", settings=SLOW))
    swap_day = int(base.fault_t[mi])
    acts = [{"day": iso(d), "type": "device_replace", "meterId": town.meter_ids[mi], "deviceId": "SN-TEST-2",
             "installDate": iso(swap_day), "initialRead": round(float(base.fault_k[mi]), 3)},
            {"day": iso(d), "type": "accept", "caseId": swapped.id}]
    run = M2CRun(town, SLOW, acts)
    c = run.case_index[swapped.id]
    assert c.outcome == "accept" and run.released[r, m] == run.obs[r, m]
    doc = run.books.docs[run.books.doc_of[town.inst_of[r], m]]
    assert doc["qImp"] == pytest.approx(run.truth[r, m] - run.truth[r, m - 1], rel=0.02, abs=1.0)
    assert not views.register_check(run, r, m, 400.0)["registerWentBackwards"]


def test_replacing_a_working_meter_swaps_it_and_bills_both_registers(town, slow, missing):
    r, m = missing.r, missing.month
    mi = int(town.meter_of[r])
    d = add_bdays(int(missing.created), 1)
    acts = [{"day": iso(d), "type": "device_replace", "meterId": town.meter_ids[mi], "deviceId": "SN-NEW-0",
             "installDate": iso(d), "initialRead": 0, "caseId": missing.id},
            {"day": iso(d), "type": "estimate", "caseId": missing.id}]
    run = M2CRun(town, SLOW, acts)
    x = next(x for x in run.installs if x.device == "SN-NEW-0")
    assert x.physical and x.previous == town.meter_ids[mi] and x.period[r] == m + 1
    assert run.display(r, d + 10 / 24) < 50  # the new dial starts near its initial read
    j = next(j for j in range(m + 1, 13) if not np.isnan(run.obs[r, j]))
    rec = views.read_record(run, r, j, 400.0)
    assert rec["deviceId"] == "SN-NEW-0" and not rec["registerRegression"]
    if j == m + 1:  # the period with the change bills the old register's last stretch and the new register's use
        assert rec["deviceChange"]["initialRead"] == 0 and rec["previousRegisterValue"] == 0
        assert rec["consumption"] == pytest.approx(run.truth[r, j] - run.truth[r, j - 1], rel=0.25, abs=2.0)
    assert not [c for c in run.cases if c.r == r and c.month > m and c.type == "REGISTER_REGRESSION"]


def test_device_replacements_are_refused_when_they_would_rewrite_billed_reads(town, swapped):
    r, m = swapped.r, swapped.month
    mi = int(town.meter_of[r])
    d = add_bdays(int(swapped.created), 1)
    early = int(town.read_day[r, m - 1]) - 1  # before a read already released on the old device
    with pytest.raises(ActionError, match="was already released on device"):
        M2CRun(town, SLOW, [{"day": iso(d), "type": "device_replace", "meterId": town.meter_ids[mi],
                             "deviceId": "SN-X", "installDate": iso(early), "initialRead": 0}])
    with pytest.raises(ActionError, match="already in use"):
        M2CRun(town, SLOW, [{"day": iso(d), "type": "device_replace", "meterId": town.meter_ids[mi],
                             "deviceId": town.meter_ids[mi + 1], "installDate": iso(d), "initialRead": 0}])
    with pytest.raises(ActionError, match="unknown meterId"):
        M2CRun(town, SLOW, [{"day": iso(d), "type": "device_replace", "meterId": "M-nope", "deviceId": "SN-X",
                             "installDate": iso(d), "initialRead": 0}])
    with pytest.raises(ActionError, match="installDate must be from"):
        M2CRun(town, SLOW, [{"day": iso(d), "type": "device_replace", "meterId": town.meter_ids[mi],
                             "deviceId": "SN-X", "installDate": iso(d + 1), "initialRead": 0}])


def test_a_meter_exchanged_outcome_installs_the_new_device(town, swapped):
    r, m = swapped.r, swapped.month
    d0 = add_bdays(int(swapped.created), 1)
    oid, acts = order(swapped.id, d0, d0, activity="Meter exchange")
    acts.append({"day": iso(d0), "type": "order_complete", "orderId": oid,
                 "outcome": {"kind": "meter_exchanged", "deviceId": "SN-NEW-9", "installDate": iso(d0),
                             "initialRead": 0}})
    d1 = add_bdays(d0, 1)
    run = M2CRun(town, SLOW, acts + [{"day": iso(d1), "type": "estimate", "caseId": swapped.id}])
    o = run.orders[oid]
    assert o.outcome["kind"] == "meter_exchanged" and o.outcome["by"] == "you"
    mine = [x for x in run.installs if x.meter == town.meter_of[r]]
    assert [x.device for x in mine] == ["SN-NEW-9"] and mine[0].order == oid
    assert not [c for c in run.cases if c.r == r and c.month > m and c.type == "REGISTER_REGRESSION"]
    assert views.read_record(run, r, m + 1, 400.0)["deviceId"] == "SN-NEW-9"
    # Without your outcome, the crew finds the unregistered meter on a meter exchange order and registers it.
    oid, acts = order(swapped.id, d0, d0, activity="Meter exchange")
    run = M2CRun(town, SLOW, acts + [{"day": iso(d1), "type": "estimate", "caseId": swapped.id}])
    out = run.orders[oid].outcome
    mine = [x for x in run.installs if x.meter == town.meter_of[r]]
    assert out["kind"] == "meter_exchanged" and out["by"].startswith("FIELD-") and mine[0].order == oid
    assert not [c for c in run.cases if c.r == r and c.month > m and c.type == "REGISTER_REGRESSION"]


def test_the_simulated_crews_register_the_meters_they_exchange():
    run = run_for(RunRequest(town="small_town"))
    exchanged = [(c, e) for c in run.cases for e in c.events if e[1] == "METER_EXCHANGE"]
    corrective = [x for x in run.installs if not x.planned]  # planned exchanges (seal, age, AMI) have no case
    assert exchanged and len(corrective) == len(exchanged)
    for _, e in exchanged:
        assert e[2]["deviceId"] in {x.device for x in corrective}
    # No register went backwards after its exchange: later reads are diffed against the new register.
    for x in run.installs:
        for r, m in x.period.items():
            for j in range(m, 13):
                if not np.isnan(run.obs[r, j]) and run.read_t[r, j] > x.t_reg:
                    assert run.case_of[r, j] < 0 or run.cases[run.case_of[r, j]].type != "REGISTER_REGRESSION"


# ---- escalations -----------------------------------------------------------------------------------------------
def test_escalations_are_worked_by_supervisors_even_after_you_note_them(town, slow):
    c = next(c for c in slow.cases if c.type not in cat.MISSING_TYPES and c.doc < 0 and 150 < c.created < 200
             and c.queue == "VEE_REVIEW" and c.resolved is None)
    d = add_bdays(int(c.created), 1)
    acts = [{"day": iso(d), "type": "escalate", "caseId": c.id},
            {"day": iso(d), "type": "note", "caseId": c.id, "text": "Supervisor please look at the history"}]
    run = M2CRun(town, SLOW, acts)
    done = run.case_index[c.id]
    assert done.resolved is not None and "SUPERVISOR_REVIEW" in [e[1] for e in done.events] and done.owner is None
    row = views.worklist(run, None, as_of=iso(d), search=c.id)["rows"][0]
    assert row["category"] == "Escalations" and row["queue"] == "SUPERVISOR" and row["owner"] is None
    esc = views.worklist(run, None, as_of=iso(d), category="Escalations")["rows"]
    assert c.id in [x["caseId"] for x in esc] and all(x["queue"] == "SUPERVISOR" for x in esc)
    # Workable by you: take it (assign) and decide it; the supervisors leave it to you.
    mine = M2CRun(town, SLOW, [*acts, {"day": iso(d), "type": "assign", "caseId": c.id, "assignee": "you"}])
    assert mine.case_index[c.id].resolved is None
    cv = views.case_view(mine, c.id, as_of=iso(d))
    assert "estimate" in cv["actions"] and "escalate" not in cv["actions"]
    took = M2CRun(town, SLOW, [*acts, {"day": iso(d), "type": "assign", "caseId": c.id, "assignee": "you"},
                                {"day": iso(add_bdays(d, 1)), "type": "estimate", "caseId": c.id}])
    assert took.case_index[c.id].by == "you" and took.case_index[c.id].outcome == "estimate"


def test_the_supervisor_pickup_lag_is_a_setting(town, slow):
    c = next(c for c in slow.cases if c.type not in cat.MISSING_TYPES and c.doc < 0 and 150 < c.created < 200
             and c.queue == "VEE_REVIEW" and c.resolved is None)
    d = add_bdays(int(c.created), 1)
    lag = {"process": {**SLOW["process"], "supervisor_queue_days_min": 6, "supervisor_queue_days_max": 6}}
    run = M2CRun(town, lag, [{"day": iso(d), "type": "escalate", "caseId": c.id}])
    review = next(e[0] for e in run.case_index[c.id].events if e[1] == "SUPERVISOR_REVIEW")
    assert int(review) >= add_bdays(d, 6)
    with pytest.raises(ValueError, match="supervisor_queue_days_max must be >= min"):
        M2CRun(town, {"process": {"supervisor_queue_days_min": 5, "supervisor_queue_days_max": 2}})


# ---- one visit per premise ----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pair(slow):
    """Two open read cases at one premise on the same day (nobody works them in the slow run)."""
    for c in slow.cases:
        if c.doc >= 0 or c.work is not None or not 60 < c.created < 250 or c.resolved is not None:
            continue
        d = add_bdays(int(c.created), 1)
        others = slow.related(c, d + 9 / 24, lambda x: x.resolved is None and x.queue in ("VEE_REVIEW", "ESTIMATION"))
        if others and c.queue in ("VEE_REVIEW", "ESTIMATION"):
            return c, others[0], d
    raise AssertionError("no premise with two open read cases")


def test_related_open_cases_show_on_the_case_and_the_list(slow, pair):
    a, b, d = pair
    cv = views.case_view(slow, a.id, as_of=iso(d))
    rel = {x["caseId"]: x for x in cv["relatedCases"]}
    assert b.id in rel and rel[b.id]["coverable"] and rel[b.id]["label"] == cat.EVENTS[b.type][0]
    row = views.worklist(slow, None, as_of=iso(d), search=a.id)["rows"][0]
    assert b.id in row["relatedCaseIds"] and a.id not in row["relatedCaseIds"]


def test_one_order_covers_the_premises_other_cases(town, pair):
    a, b, d = pair
    oid, acts = order(a.id, d, d, cover=[b.id])
    run = M2CRun(town, SLOW, acts)
    o = run.orders[oid]
    assert [c.id for c in o.covered] == [b.id] and run.case_index[b.id].orders == [oid]
    rolls = [e for c in run.cases for e in c.events if e[1] == "TRUCK_ROLL" and int(e[0]) == d
             and int(town.prem[c.r]) == int(town.prem[a.r])]
    assert len(rolls) == 1  # one truck roll for both cases
    for c in (a, b):  # the outcome is written back to each case the visit served
        cv = views.case_view(run, c.id, as_of=iso(d))
        assert cv["fieldOutcome"]["orderId"] == oid and cv["orders"][0]["coveredCaseIds"] == [b.id]
    with pytest.raises(ActionError, match="cannot cover"):
        M2CRun(town, SLOW, order(a.id, d, d, cover=["CASE-nope"])[1][:1])


def test_your_field_order_can_cover_them_and_the_crews_roll_once_per_premise(town, pair):
    a, b, d = pair
    run = M2CRun(town, SLOW, [{"day": iso(d), "type": "field_order", "caseId": a.id, "coverCaseIds": [b.id]}])
    ca, cb = run.case_index[a.id], run.case_index[b.id]
    assert ca.resolved is not None and cb.resolved is not None
    roll = next(e for e in ca.events if e[1] == "TRUCK_ROLL")
    assert roll[2]["caseIds"] == [a.id, b.id] and "VISIT_SHARED" in [e[1] for e in cb.events]
    assert not [e for e in cb.events if e[1] == "TRUCK_ROLL"]


def test_the_simulated_workforce_rolls_one_truck_per_premise_a_day():
    run = run_for(RunRequest(town="small_town"))
    tw = run.town
    rolls: dict[tuple[int, int], int] = {}
    for c in run.cases:
        for e in c.events:
            if e[1] == "TRUCK_ROLL" and c.work is None:
                key = (int(tw.prem[c.r]), int(e[0]))
                rolls[key] = rolls.get(key, 0) + 1
    assert rolls and max(rolls.values()) == 1
    shared = [c for c in run.cases if any(e[1] in ("VISIT_SHARED",) or (e[1] == "FIELD_ORDER" and e[2].get("with"))
                                          for e in c.events)]
    assert shared  # analysts and RPA send the premise's other open cases along with a field order


# ---- missed reads name their outage --------------------------------------------------------------------------------
def test_mr_results_name_the_outage_that_missed_a_read(town):
    base = run_for(RunRequest(town="small_town"))
    d, (_, rows) = next((d, b) for d, b in sorted(base.batches.items()) if 60 < d < 80)
    pid = next(town.premise_ids[town.prem[r]] for r in rows if town.tech[r] == "AMI" and town.commodity[r] == "electric")
    outages = [{"day": iso(d), "utility": "electric", "start": 0, "end": 4 * 3600, "premiseIds": [pid]}]
    run = run_for(RunRequest(town="small_town", outages=outages))
    r = next(int(r) for r in rows if town.premise_ids[town.prem[r]] == pid and town.commodity[r] == "electric"
             and town.direction[r] == "import")
    inst = lookups.installation(run, town.installation[r], as_of="2026-12-31")
    read = next(x for x in inst["reads"] if x["registerId"] == town.reg_ids[r]
                and x["scheduledReadAt"].startswith(iso(d)))
    assert read["reasonCode"] == "SIM_POWER_OUTAGE" and read["cause"]["code"] == "power_outage"
    assert read["cause"]["outageStart"] and read["cause"]["outageEnd"] and "lost power" in read["cause"]["reason"]
