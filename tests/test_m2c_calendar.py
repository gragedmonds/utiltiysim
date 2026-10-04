"""The run's calendar year (utilsim/m2c/calendar.py): Ontario holidays by rule, business days and month starts per
year, leap years, and no part of the engine left on a fixed year."""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import numpy as np
import orjson
import pytest

from api._m2c import _ops_town, load_snapshot
from utilsim.customers.calendar import business_days, holidays
from utilsim.m2c import contact, trend, views
from utilsim.m2c import fieldwork as fwk
from utilsim.m2c.base import M2CTown
from utilsim.m2c.calendar import FIRST_YEAR, LAST_YEAR, calendar
from utilsim.m2c.run import M2CRun

ROOT = Path(__file__).resolve().parents[1]
# The holidays the engine shipped with as a fixed list (2025-2027): the rules must give exactly these.
PUBLISHED = {
    date(2025, 1, 1), date(2025, 2, 17), date(2025, 4, 18), date(2025, 5, 19), date(2025, 7, 1), date(2025, 8, 4),
    date(2025, 9, 1), date(2025, 10, 13), date(2025, 12, 25), date(2025, 12, 26),
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 18), date(2026, 7, 1), date(2026, 8, 3),
    date(2026, 9, 7), date(2026, 10, 12), date(2026, 12, 25), date(2026, 12, 28),
    date(2027, 1, 1), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 24), date(2027, 7, 1), date(2027, 8, 2),
    date(2027, 9, 6), date(2027, 10, 11), date(2027, 12, 27), date(2027, 12, 28),
}


def test_holidays_follow_ontarios_rules():
    assert set().union(*(holidays(y) for y in (2025, 2026, 2027))) == PUBLISHED
    h28 = holidays(2028)
    assert date(2028, 4, 14) in h28  # Good Friday (Easter 16 April)
    assert date(2028, 1, 3) in h28 and date(2028, 7, 3) in h28  # New Year's and Canada Day on a Saturday: Monday
    assert date(2028, 5, 22) in h28  # Victoria Day: the Monday before 25 May
    for y in range(2025, LAST_YEAR + 2):
        assert len(holidays(y)) == 10 and all(d.weekday() < 5 for d in holidays(y))


def test_a_calendar_year():
    c = calendar(FIRST_YEAR)
    assert (c.year, c.days, c.start, c.end) == (2026, 365, "2026-01-01", "2026-12-31")
    assert c.month_start.tolist() == [-31, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365]
    days = [d for y, m in [(2025, 12), *((2026, k) for k in range(1, 13)), (2027, 1), (2027, 2)]
            for d in business_days(y, m)]
    assert list(c.bdays) == [c.day_of(d) for d in days]
    assert c.date_of(c.add_bdays(c.day_of(date(2026, 12, 24)), 1)) == date(2026, 12, 29)  # over Christmas
    assert c.parse_day("2026-03-01", -1) == 59 and c.parse_day(None, 7) == 7
    leap = calendar(2028)
    assert leap.days == 366 and leap.month_days()[1] == 29 and leap.end == "2028-12-31"
    assert calendar(2027).month_start[0] == -31 and calendar(2027).day_of(date(2027, 1, 1)) == 0
    with pytest.raises(ValueError):
        calendar(LAST_YEAR + 1)
    with pytest.raises(ValueError):
        c.parse_day("01/03/2026", 0)


BANNED = {"date_of", "parse_day", "add_bdays", "bdays_between", "YEAR_DAYS", "MONTH_START", "EPOCH", "_BDAYS",
          "_BSET"}
MODULES = {"ords", "orders", "regs", "registers", "views", "base", "colls", "contact", "fwk", "fieldwork",
           "trend", "tables", "books", "incidents"}  # module names: their bare-year helpers are gone
DATED = re.compile(r"(?<![/\w])20[23]\d-\d\d")


def _docstrings(tree) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def test_no_engine_code_is_left_on_a_fixed_year():
    """Every date in the engine comes from the run's calendar (``run.cal``, ``town.cal``): no bare 2026 helpers, no
    year numbers, no dated strings outside docstrings (only the calendar itself names its years)."""
    files = [*sorted((ROOT / "utilsim/m2c").glob("*.py")), ROOT / "api/_m2c.py", ROOT / "utilsim/io/run_bundle.py"]
    found = []
    for path in files:
        if path.name in ("calendar.py", "guide.py"):
            continue
        tree = ast.parse(path.read_text())
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            where = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Name) and node.id in BANNED:
                found.append(f"{where} {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in BANNED | {"day_of"} and \
                    isinstance(node.value, ast.Name) and node.value.id in MODULES:
                found.append(f"{where} {node.value.id}.{node.attr}")
            elif isinstance(node, ast.ImportFrom) and any(a.name in BANNED for a in node.names):
                found.append(f"{where} import {[a.name for a in node.names if a.name in BANNED]}")
            elif isinstance(node, ast.Constant) and id(node) not in docs:
                if isinstance(node.value, int) and not isinstance(node.value, bool) and 2024 <= node.value <= 2035:
                    found.append(f"{where} {node.value}")
                elif isinstance(node.value, str) and DATED.search(node.value) and path.name != "_m2c.py":
                    found.append(f"{where} {node.value[:40]!r}")
    assert not found, "\n".join(found)


@pytest.fixture(scope="module")
def year_2029():
    snap = load_snapshot("village")
    return M2CRun(M2CTown.from_snapshot(snap, 2029), ops_factory=lambda: _ops_town("village"))


def test_a_later_year_runs_in_its_own_calendar(year_2029):
    run = year_2029
    cal = run.cal
    assert cal.year == 2029 and run.town.read_day[:, 1:].min() >= 0 and run.town.read_day[:, 0].max() < 0
    # Reads on the year's business days; usage and weather of the year (not 2026's again).
    days = np.unique(run.town.read_day[:, 1:])
    assert all(cal.is_bday(int(d)) for d in days)
    base = M2CTown.from_snapshot(load_snapshot("village"))
    assert not np.array_equal(run.town.normal["electric_import"], base.normal["electric_import"])
    assert len(run.town.temps) == len(base.temps) and not np.array_equal(run.town.temps, base.temps)
    # Every view dates itself in 2029 (bills due in early 2030, the December before is 2028).
    fwk.fieldwork(run)
    payload = orjson.dumps([views.summary(run, "2029-12-31"), trend.trend(run, "2029-12-31"),
                            views.worklist(run, as_of="2029-12-31", status="all", page_size=200),
                            views.scorecard(run, as_of="2029-12-31"), contact.summary(run, "2029-12-31"),
                            fwk.summary(run, "2029-12-31")], option=orjson.OPT_SERIALIZE_NUMPY).decode()
    payload = payload.replace(f'"date":"{run.cfg.billing.rate_change_date}"', "")  # a setting, not a run date
    years = {int(m[:4]) for m in re.findall(r"\b20\d\d-\d\d-\d\d", payload)}
    assert 2029 in years and years <= {2028, 2029, 2030}, years
    assert run.books.invoices and all(i["id"].split("-")[-1].startswith("2029") for i in run.books.invoices)
    assert all(c.id.startswith("CASE-29") for c in run.cases)
    with pytest.raises(ValueError, match="2029"):
        views.as_of_t(run, "2026-06-30")


def test_a_leap_year_runs():
    snap = load_snapshot("village")
    run = M2CRun(M2CTown.from_snapshot(snap, 2028))
    assert run.cal.days == 366 and len(run.series["VEE_REVIEW"]) == 366
    months = trend.trend(run, "2028-12-31")["months"]
    assert months[1]["end"] == "2028-02-29" and months[-1]["end"] == "2028-12-31"
    assert views.summary(run, "2028-12-31")["asOf"] == "2028-12-31"
