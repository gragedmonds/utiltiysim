"""Chained years (utilsim/m2c/yearclose.py): a year opens on the one before it closed. The dials go on, the money
owed and the work open carry, a service off stays off, the devices and technology on site stay, and the next year
draws its own events."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from api._m2c import _ops_town, load_snapshot
from utilsim.m2c import collections as colls
from utilsim.m2c import fieldwork as fwk
from utilsim.m2c import views, yearclose
from utilsim.m2c.base import M2CTown
from utilsim.m2c.run import OFF, M2CRun

TOWN = "village"
# Every account past the rule is disconnected (services off at the year's end), and too few meter technicians for the
# year's meter work (orders still open at the year's end).
SETTINGS = {"billing": {"disconnect_rule_share": 1.0}, "field": {"crew_meter": {"per_1000_premises": 0.1}}}


def _first(snap) -> M2CRun:
    return M2CRun(M2CTown.from_snapshot(snap), settings=SETTINGS, ops_factory=lambda: _ops_town(TOWN))


@pytest.fixture(scope="module")
def chain():
    snap = load_snapshot(TOWN)
    r26 = _first(snap)
    close = yearclose.close(r26)
    r27 = yearclose.next_year(r26, snap)
    return snap, r26, close, r27


def _dials(run, t: float) -> np.ndarray:
    return np.array([run.display(r, t) for r in range(run.town.n_registers)])


def test_the_dials_go_on(chain):
    _, r26, close, r27 = chain
    assert r27.cal.year == 2027 and r27.opening.totals == close.totals
    assert np.abs(_dials(r26, r26.cal.days) - _dials(r27, 0.0)).max() < 1e-3
    np.testing.assert_allclose(r27.town.base, close.base)
    assert (r27.town.read_day[:, 0] < 0).all() and (r27.town.read_day[:, 1:] >= 0).all()


def test_the_next_bill_runs_from_the_last_billed_read(chain):
    _, r26, close, r27 = chain
    bk26, bk27 = r26.books, r27.books
    n = 0
    for d in bk27.docs[len(close.docs):]:
        if d["from"] != 0 or d["version"] != 1:
            continue
        i = d["inst"]
        r = int(bk27.main[i])
        last = [x["month"] for x in bk26.docs if x["inst"] == i]
        if not last or r26.installs_of.get(r):
            continue
        n += 1
        assert r27.released[r, 0] == pytest.approx(r26.released[r, max(last)], abs=1e-6), r26.town.reg_ids[r]
        assert r27.town.read_day[r, 0] == r26.town.read_day[r, max(last)] - r26.cal.days
    assert n > 0.9 * len(r26.town.inst_ids)


def test_the_money_owed_carries(chain):
    _, r26, close, r27 = chain
    D = r26.cal.days
    assert close.invoices and close.totals["receivable"] > 0
    for a in r26.books.ledger:
        assert r27.books.balance(a, 0.0) == pytest.approx(r26.books.balance(a, D), abs=0.01), a
    carried = r27.books.invoices[:len(close.invoices)]
    assert [i["id"] for i in carried] == [i["id"] for i in close.invoices]
    owed26 = {i["id"]: colls.owed(i, D) for i in r26.books.invoices}
    assert all(colls.owed(i, 0.0) == pytest.approx(owed26[i["id"]], abs=0.01) for i in carried)
    # The new year collects on them: most are paid by its end.
    assert sum(1 for i in carried if i["out"] <= 0.005) > len(carried) / 2
    # The year's own invoices carry its year.
    assert all(i["id"].split("-")[-1].startswith("2027") for i in r27.books.invoices[len(carried):])


def test_the_open_work_carries_and_is_worked(chain):
    _, r26, close, r27 = chain
    open26 = [c for c in r26.cases if c.resolved is None and c.work not in ("order", "hold")]
    assert len(close.cases) == len(open26) > 0
    carried = r27.cases[:len(close.cases)]
    assert [c.id for c in carried] == [c.id for c in open26]
    assert all(c.created < 0 for c in carried)
    assert sum(1 for c in carried if c.resolved is not None) > len(carried) / 2
    assert all(c.id.startswith("CASE-27") for c in r27.cases[len(carried):])
    # Bills released but not invoiced at midnight go out on the year's first invoice run.
    unbilled = [d for d in r27.books.docs[:len(close.docs)] if d["invoice"] < 0 and d["released"] is not None
                and d["reversed"] is None]
    assert not unbilled


def test_the_winter_moratorium_releases_next_spring(chain):
    _, r26, close, r27 = chain
    D = r26.cal.days
    held = [i for i in close.invoices if i.get("moratorium") is not None and i["level"] == 2]
    assert held, "notices held over the winter at the year's end"
    may = r27.cal.day_of(date(2027, 5, 1))
    by_id = {i["id"]: i for i in r27.books.invoices}
    released = 0
    for inv in held:
        x = by_id[inv["id"]]
        notices = [t for t, kind in x["dunning"] if kind == "DISCONNECT_NOTICE"]
        assert -D < x["moratorium"] < 0 and (not notices or min(notices) >= may - 1e-9), inv["id"]
        released += bool(notices)
    assert released > 0  # still unpaid on 1 May: the notice goes out


def test_the_years_figures_are_its_own(chain):
    """Year to date counts the year's flows: a case, bill or invoice carried from last year was opened, made and
    costed then (it still shows open, owed and worked this year): the summary equals its own 1 January window."""
    _, _, close, r27 = chain
    s = views.summary(r27, "2027-12-31", since="2027-01-01")
    k, w = s["kpis"], s["window"]["kpis"]
    for key in ("casesOpened", "casesResolved", "fieldOrders", "truckRolls", "carry"):
        assert k[key] == pytest.approx(w[key], abs=0.01), key
    b, wb = s["billing"], s["window"]["billing"]
    for key in ("documents", "invoices", "invoiced", "collected", "dunning"):
        assert b[key] == pytest.approx(wb[key], abs=0.01), key
    assert k["casesOpened"] == sum(1 for c in r27.cases if c.created >= 0)
    assert w["casesOpenAtStart"] == len(close.cases)
    assert s["window"]["billing"]["receivableAtStart"] > 0


def test_a_service_off_stays_off(chain):
    _, r26, close, r27 = chain
    assert close.off_spans, "the settings disconnect some accounts"
    for r in close.off_spans:
        a, b, _ = r27.off_spans[r][0]
        assert a < 0
        if b == float("inf"):  # never reconnected in 2027: no reads flow, the dial does not move
            assert (r27.status[r, 1:] == OFF).all()
            assert r27.display(r, r27.cal.days) == pytest.approx(r27.display(r, 0.0), abs=1e-6)


def test_devices_and_technology_stay(chain):
    _, r26, close, r27 = chain
    tw = r26.town
    D = r26.cal.days
    assert (r27.town.meter_tech == r26.meter_tech_now).all()
    for m in range(len(tw.meter_ids)):
        assert r27.device_at(m, 0.0) == r26.device_at(m, D)
    changed = np.flatnonzero(close.device_count > 0)
    assert len(changed) > 0
    m = int(changed[0])
    assert r27.new_device_id(m).endswith(f"-X{int(close.device_count[m]) + 1 + sum(1 for x in r27.installs if x.meter == m)}")


def test_field_orders_carry_and_complete(chain):
    _, r26, close, r27 = chain
    fw27 = fwk.fieldwork(r27)
    ids26 = {o.id for o in fwk.fieldwork(r26).orders}
    carried = [o for o in fw27.orders if o.id in ids26]
    assert len(carried) == len(close.orders) > 0
    assert all(o.created < 0 and o.due < r27.cal.days for o in carried)
    assert any(o.end <= r27.cal.days and not o.cancelled for o in carried)  # the crews work last year's backlog
    assert any(o.then and o.then[0] == "lot" for o in carried) and close.lots  # a seal lot still being sampled
    assert all(o.id.startswith("WO-27-") for o in fw27.orders if o.id not in ids26)


def test_each_year_draws_its_own(chain):
    _, r26, _, r27 = chain
    assert r27.seed == r26.seed + ":2027"
    assert r27.simulation_id.startswith(f"m2c-{r26.town.id}-2027-") and r27.simulation_id != r26.simulation_id
    assert not np.array_equal(r26.read_t[:, 1:], r27.read_t[:, 1:])


def test_a_chain_is_deterministic(chain):
    snap, r26, close, r27 = chain
    again = yearclose.next_year(r26, snap)
    assert again.simulation_id == r27.simulation_id
    assert np.array_equal(again.obs, r27.obs, equal_nan=True) and np.array_equal(again.status, r27.status)
    assert [(i["id"], i["total"], i["out"]) for i in again.books.invoices] == \
        [(i["id"], i["total"], i["out"]) for i in r27.books.invoices]
    assert [(c.id, c.resolved) for c in again.cases] == [(c.id, c.resolved) for c in r27.cases]
    # The close is a value: closing twice gives the same opening.
    other = yearclose.close(r26)
    assert np.array_equal(other.base, close.base) and other.totals == close.totals


def test_a_close_opens_only_its_next_year(chain):
    snap, r26, close, _ = chain
    with pytest.raises(ValueError, match="2027"):
        yearclose.open_town(M2CTown.from_snapshot(snap, 2028), close)


def test_three_years_into_a_leap_year(chain):
    snap, _, _, r27 = chain
    r28 = yearclose.next_year(r27, snap)
    assert r28.cal.year == 2028 and r28.cal.days == 366
    assert np.abs(_dials(r27, r27.cal.days) - _dials(r28, 0.0)).max() < 1e-3
    for a in r27.books.ledger:
        assert r28.books.balance(a, 0.0) == pytest.approx(r27.books.balance(a, r27.cal.days), abs=0.01), a
    assert r28.simulation_id.startswith(f"m2c-{r27.town.id}-2028-") and r28.seed.endswith(":2028")
    assert all(o.id.startswith(("WO-27-", "WO-28-", "WO-0")) for o in fwk.fieldwork(r28).orders)
