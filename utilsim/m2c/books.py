"""Billing, invoicing, payments and collections for a meter-to-cash run.

The run calls in at fixed points of each business day:
- **19:30:** billing documents for installation periods whose reads are all released;
- **20:00:** invoices that consolidate an account's released documents.

Bill checks block a document into the ``BILLING`` queue:
- an estimate true-up (a negative period quantity) larger than ``trueup_max_ratio`` × the period's expected use;
- a wrong rate class in billing master data (seeded data errors);
- a high bill against the installation's recent history;
- a large credit.

RPA may release a high bill or a large credit only up to ``outsort_auto_release_max``; a larger outsort and every
true-up block wait for a person. A document says whether it was built on an estimated read (``estimated``).

Analysts work the queue: they release the bill, rebill it on an estimate, or fix the rate class. Payments, dunning and
collections step with the run's days (``collections.py``), so a disconnection can stop an account's later reads:
- payment timing comes from the account's payment method and its partner's payer profile;
- pre-authorized debits can be returned;
- unpaid invoices get reminders, overdue notices with late fees, and disconnection notices (held by the winter
  moratorium for electricity and water);
- your collections actions (arrangements, holds, referrals, budget billing, waivers, disconnections) and the call
  centre's referrals change them from their day on.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from utilsim.core.ids import str_key
from utilsim.core.rng import Purpose, hash_u01
from utilsim.m2c import billing as bl
from utilsim.m2c import catalog as cat
from utilsim.m2c.vee import MIN_EXPECTED

OFF = 6  # run.OFF: the service was off at the read

P_BILL = Purpose.M2C_BILL
INF = float("inf")
STATUS = ("created", "blocked", "released", "reversed")


def _swap(rate: str) -> str:
    return ("COM-" + rate[4:]) if rate.startswith("RES-") else ("RES-" + rate[4:]) if rate.startswith("COM-") else rate


def wrong_bill(doc: dict) -> bool:
    """The bill is off against the truth by more than $5 and 10% (what a check read would show)."""
    return abs(doc["total"] - doc["truthTotal"]) > max(5.0, 0.1 * abs(doc["truthTotal"]))


class Books:
    def __init__(self, run) -> None:
        self.run = run
        tw, b = run.town, run.cfg.billing
        n = len(tw.inst_ids)
        self.change = float(run.cal.parse_day(b.rate_change_date, 10 ** 6))
        self.inst_keys = np.array([str_key(x) for x in tw.inst_ids], dtype=np.int64)
        self.main = np.array([rows[np.argmax(tw.direction[rows] == "import")] if len(rows) else -1
                              for rows in tw.inst_rows], dtype=np.int64)
        self.export_row = np.array([next((int(r) for r in rows if tw.direction[r] == "export"), -1)
                                    for rows in tw.inst_rows], dtype=np.int64)
        months = np.arange(1, 13)
        p = run.month_rate("billing", "data_error_rate") / 1000.0 / 12.0 * bool(run.cfg.anomalies.enabled)
        hit = hash_u01(run.seed, P_BILL, self.inst_keys[:, None], 1, months[None, :]) < p[None, :]
        first = np.where(hit.any(1), hit.argmax(1) + 1, 0)
        self.rate_err_t = np.where(first > 0, run.cal.month_start[first] + 0.0, INF)
        self.rate_fix_t = np.full(n, INF)
        self.doc_of = np.full((n, 13), -1, dtype=np.int64)
        self.docs: list[dict] = []
        # Registers per installation and month still waiting for release; at zero the period is ready to bill.
        self.pending = np.repeat(np.array([len(r) for r in tw.inst_rows], dtype=np.int64)[:, None], 13, axis=1)
        self.ready: list[tuple[int, int]] = []
        self.to_invoice: dict[int, list[int]] = {}
        self.held: dict[str, list[int]] = {}  # account -> released documents held back by an invoice hold
        self.invoices: list[dict] = []
        self.ledger: dict[str, list[tuple]] = {}
        self.collections = None  # started by the run before its first day (start_collections)

    # ---- documents -------------------------------------------------------------------------------------------
    def rate_at(self, i: int, t: float) -> str:
        rate = self.run.town.inst_rate[i]
        return _swap(rate) if self.rate_err_t[i] <= t < self.rate_fix_t[i] else rate

    def starts(self, i: np.ndarray, m: np.ndarray) -> np.ndarray:
        """The read month each installation period ending at month ``m`` starts from: the previous month, or the
        last month read before its service was off (a disconnection: no read, so no bill for the months between)."""
        run = self.run
        rows = self.main[i]
        sm = np.asarray(m) - 1
        for k in np.flatnonzero(run.status[rows, sm] == OFF):
            sm[k] = run.period_start(int(rows[k]), int(m[k]))
        return sm

    def quantities(self, i: np.ndarray, m: np.ndarray, src: np.ndarray,
                   device: bool = False, sm: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Import and export quantities per installation period from register values ``src`` (released or truth),
        from start month ``sm`` (default the previous month). ``device``: a period with a device change bills the
        new register from its initial read, plus the old register's last stretch (``Install.carry``)."""
        run = self.run
        digits = run.town.digits
        sm = np.asarray(m) - 1 if sm is None else np.asarray(sm)
        out = []
        for rows in (self.main[i], self.export_row[i]):
            ok = rows >= 0
            rr = np.where(ok, rows, 0)
            mod = 10.0 ** digits[rr]
            prev = src[rr, sm].astype(float)
            if device:
                gap = sm != np.asarray(m) - 1
                for k in np.flatnonzero(ok & (gap | (run.dev_change[rr, m] != None))):  # noqa: E711 (objects)
                    r, mm, s0 = int(rr[k]), int(m[k]), int(sm[k])
                    x = run.dev_change[r, mm] if s0 == mm - 1 else run.change_between(
                        r, float(run.read_t[r, s0]), float(run.read_t[r, mm]))
                    if x is not None:
                        prev[k] = x.carry(r, float(src[r, s0]), float(run.normal_at[r, s0]))
            d = src[rr, m] - prev
            out.append(np.where(ok, np.where(d < -0.5 * mod, d + mod, d), 0.0))
        return out[0], out[1]

    def expected(self, i: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        exp = self.run.expected
        rows = self.export_row[i]
        return exp[self.main[i], m], np.where(rows >= 0, exp[np.maximum(rows, 0), m], 0.0)

    def compute(self, items: list[tuple]) -> list[tuple]:
        """[(inst, month, rate, q_imp, q_exp[, start month])] → [(subtotal, tax, total)] in the same order (vectorised
        per rate); the period runs from the start month's read (default the previous month's) to the month's."""
        run, tw = self.run, self.run.town
        out: list[tuple] = [None] * len(items)  # type: ignore[list-item]
        groups: dict[str, list[int]] = {}
        for k, item in enumerate(items):
            rate = item[2]
            groups.setdefault(rate, []).append(k)
        pct = run.cfg.billing.rate_change_pct
        for rate, ks in groups.items():
            tariff = tw.tariffs.get(rate, {})
            i = np.array([items[k][0] for k in ks])
            m = np.array([items[k][1] for k in ks])
            sm = np.array([items[k][5] if len(items[k]) > 5 else items[k][1] - 1 for k in ks])
            rows = self.main[i]
            comm = str(tw.commodity[rows[0]])
            t0, t1 = run.read_t[rows, sm], run.read_t[rows, m]
            if any(len(items[k]) > 6 for k in ks):  # a carried document: its own period
                t0 = np.array([items[k][6] if len(items[k]) > 6 else t0[j] for j, k in enumerate(ks)])
                t1 = np.array([items[k][7] if len(items[k]) > 6 else t1[j] for j, k in enumerate(ks)])
            _, sub, tax = bl.charges(tariff, comm, np.array([items[k][3] for k in ks]),
                                     np.array([items[k][4] for k in ks]), t0, t1, self.change, pct,
                                     self.export_row[i] >= 0)
            for j, k in enumerate(ks):
                out[k] = (float(sub[j]), float(tax[j]), round(float(sub[j] + tax[j]), 2))
        return out

    def lines(self, doc: dict) -> list[dict]:
        run, tw = self.run, self.run.town
        i = doc["inst"]
        rows = self.main[[i]]
        t0, t1 = self.period(doc)
        comps, _, _ = bl.charges(tw.tariffs.get(doc["rate"], {}), str(tw.commodity[rows[0]]), np.array([doc["qImp"]]),
                                 np.array([doc["qExp"]]), np.array([t0]), np.array([t1]), self.change,
                                 run.cfg.billing.rate_change_pct, np.array([self.export_row[i] >= 0]))
        return bl.lines(comps, 0)

    def period(self, doc: dict) -> tuple[float, float]:
        """When the document's period starts and ends (read times; a document carried from last year keeps its
        own)."""
        c = doc.get("carried")
        if c is not None:
            return c["t0"], c["t1"]
        r, m = int(self.main[doc["inst"]]), doc["month"]
        return float(self.run.read_t[r, doc.get("from", m - 1)]), float(self.run.read_t[r, m])

    def mark(self, rows, m: int) -> None:
        for i in self.run.town.inst_of[np.atleast_1d(rows)].tolist():
            self.pending[i, m] -= 1
            if self.pending[i, m] == 0:
                self.ready.append((i, m))

    def bill(self, day: int) -> None:
        """19:30: one billing document per installation period whose reads are all released."""
        run = self.run
        if not self.ready:
            return
        ready, self.ready = sorted(self.ready), []
        t = day + 19.5 / 24
        i = np.array([x[0] for x in ready])
        m = np.array([x[1] for x in ready])
        rates = [self.rate_at(a, t) for a in i.tolist()]
        right = [run.town.inst_rate[a] for a in i.tolist()]
        sm = self.starts(i, m)
        qi, qe = self.quantities(i, m, run.released, device=True, sm=sm)
        ti, te = self.quantities(i, m, run.truth, sm=sm)
        ei, ee = self.expected(i, m)
        il, ml, sl = i.tolist(), m.tolist(), sm.tolist()
        totals = self.compute(list(zip(il, ml, rates, qi.tolist(), qe.tolist(), sl, strict=True)))
        true_totals = self.compute(list(zip(il, ml, right, ti.tolist(), te.tolist(), sl, strict=True)))
        expected = self.compute(list(zip(il, ml, right, ei.tolist(), ee.tolist(), sl, strict=True)))
        b = run.cfg_at(day).billing
        tw = run.town
        for k, (a, mm) in enumerate(ready):
            sub, tax, total = totals[k]
            est = [int(r) for r in tw.inst_rows[a] if run.status[r, mm] == 2]  # registers billed on an estimate
            doc = {"k": len(self.docs), "inst": a, "month": mm, "rate": rates[k], "qImp": float(qi[k]),
                   "qExp": float(qe[k]), "subtotal": sub, "tax": tax, "total": total, "truthTotal": true_totals[k][2],
                   "expectedTotal": expected[k][2], "from": int(sm[k]), "created": t, "released": None,
                   "reversed": None, "version": 1,
                   "case": -1, "invoice": -1, "replaces": -1, "estimated": bool(est), "estRows": est}
            self.docs.append(doc)
            self.doc_of[a, mm] = doc["k"]
            exp = expected[k][2]
            kind = None
            floor = MIN_EXPECTED.get(str(tw.unit[self.main[a]]), 1.0)
            if qi[k] < 0 and -qi[k] > b.trueup_max_ratio * max(float(ei[k]), floor):
                kind = "TRUE_UP"  # more credit than the period could plausibly have been over-estimated by
            elif rates[k] != right[k]:
                kind = "RATE_CLASS"
            elif exp > 0 and total > max(b.high_bill_ratio * exp, exp + b.high_bill_min):
                kind = "HIGH_BILL"
            elif exp <= 0 and total > b.first_bill_limit:
                kind = "HIGH_BILL"
            elif total < -b.credit_review:
                kind = "BILL_CREDIT"
            if kind:
                self.block(doc, kind, t, abs(total - max(exp, 0.0)))
            else:
                self.release(doc, t + 0.003)

    def block(self, doc: dict, kind: str, t: float, impact: float) -> None:
        run = self.run
        i, m = doc["inst"], doc["month"]
        r = int(self.main[i])
        bad = int(np.max(run.truth_cls[run.town.inst_rows[i], m]))
        off = abs(doc["total"] - doc["truthTotal"]) > max(5.0, 0.1 * abs(doc["truthTotal"]))
        truth = cat.TRUTH[bad] if off and bad in (1, 2) else ("physics" if bad == 3 else "clean")
        # RPA releases small outsorts only; a large one (and any true-up block) needs a person. With the queue left to
        # you (billing_queue_worked_by), no automation touches it.
        b = run.cfg_at(t).billing
        rpa = b.billing_queue_worked_by == "analysts" and (kind not in cat.OUTSORTS or
                                                           abs(doc["total"]) <= b.outsort_auto_release_max)
        case = run.new_case(day=int(t), r=r, m=m, kind=kind, disposition=-1, impact=impact,
                            confidence=float("nan"), truth=truth, queue="BILLING", t=t, cause_payload={
                                "billingDocumentId": self.doc_id(doc), "total": doc["total"],
                                **({"quantity": doc["qImp"]} if kind == "TRUE_UP" else {})},
                            created_by="billing_run", rpa=rpa)
        case.doc = doc["k"]
        doc["case"] = case.idx

    def release(self, doc: dict, t: float) -> None:
        doc["released"] = t
        day = int(t)
        inv = day if (t - day) < 20.0 / 24 and day in self.run.bday_set else self.run.next_bday(day)
        self.to_invoice.setdefault(inv, []).append(doc["k"])

    def unhold(self, acct: str, t: float) -> None:
        """An invoice hold is removed at ``t``: the documents it held go to the next invoice run (20:00)."""
        docs = self.held.pop(acct, [])
        if docs:
            day = int(t)
            inv = day if (t - day) < 20.0 / 24 and day in self.run.bday_set else self.run.next_bday(day)
            self.to_invoice.setdefault(inv, []).extend(docs)

    def redo(self, doc: dict, t: float, *, rate: str | None = None, estimate: bool = False,
             checked: bool = False) -> dict:
        """Reverse ``doc`` and issue version 2 (estimated quantities, a corrected rate, or ``checked``: the quantities
        a check read finds), released at ``t``. A reversed document already invoiced is credited on the next
        invoice."""
        run = self.run
        i, m = doc["inst"], doc["month"]
        doc["reversed"] = t
        qi, qe = doc["qImp"], doc["qExp"]
        carried = doc.get("carried")
        if carried is not None:  # last year's bill: its truth and expected quantities came with it
            if checked:
                qi, qe = carried["qTruth"]
            elif estimate:
                qi, qe = carried["qExpected"]
            rate = rate or doc["rate"]
            ((sub, tax, total),) = self.compute([(i, m, rate, qi, qe, 0, carried["t0"], carried["t1"])])
            return self._reissue(doc, t, rate, qi, qe, sub, tax, total, estimate, checked)
        if checked:
            sm = np.array([doc.get("from", m - 1)])
            ti, te = self.quantities(np.array([i]), np.array([m]), run.truth, sm=sm)
            qi, qe = float(ti[0]), float(te[0])
        elif estimate:
            rows = [r for r in (self.main[i], self.export_row[i]) if r >= 0]
            est = [float(run.expected[r, m]) for r in rows]
            qi, qe = est[0], (est[1] if len(est) > 1 else 0.0)
        rate = rate or doc["rate"]
        ((sub, tax, total),) = self.compute([(i, m, rate, qi, qe, doc.get("from", m - 1))])
        return self._reissue(doc, t, rate, qi, qe, sub, tax, total, estimate, checked)

    def _reissue(self, doc: dict, t: float, rate: str, qi: float, qe: float, sub: float, tax: float, total: float,
                 estimate: bool, checked: bool) -> dict:
        i, m = doc["inst"], doc["month"]
        new = {**doc, "k": len(self.docs), "rate": rate, "qImp": qi, "qExp": qe, "subtotal": sub, "tax": tax,
               "total": total, "created": t, "released": None, "reversed": None, "version": doc["version"] + 1,
               "invoice": -1, "replaces": doc["k"], "estimated": bool(estimate or (doc.get("estimated") and not checked)),
               "rebilledOnEstimate": estimate, **({"checkRead": True} if checked else {})}
        self.docs.append(new)
        if doc.get("carried") is None or self.doc_of[i, m] == doc["k"]:
            self.doc_of[i, m] = new["k"]
        self.release(new, t + 0.001)
        return new

    def resolve(self, case, t: float, action: str, actor: str) -> None:
        doc = self.docs[case.doc]
        cause = len(case.events) - 1
        i = doc["inst"]
        if action in ("rebill", "estimate"):
            case.ev(t, "ANALYST_CANCEL" if actor not in ("RPA",) else "AUTO_OVERRIDE", {"action": "cancel bill"}, cause)
            case.ev(t + 0.0005, "BILL_REVERSED", {"billingDocumentId": self.doc_id(doc)})
            new = self.redo(doc, t + 0.001, estimate=True)
            case.ev(t + 0.001, "REBILL", {"billingDocumentId": self.doc_id(new), "total": new["total"]})
        elif action == "check_rebill":  # a disputed bill was wrong: a check read, then the bill again on it
            case.ev(t, "CHECK_READ", {"billingDocumentId": self.doc_id(doc)}, cause)
            case.ev(t + 0.0005, "BILL_REVERSED", {"billingDocumentId": self.doc_id(doc)})
            new = self.redo(doc, t + 0.001, checked=True)
            case.ev(t + 0.001, "REBILL", {"billingDocumentId": self.doc_id(new), "total": new["total"],
                                          "change": round(new["total"] - doc["total"], 2)})
        elif action == "explain":  # a disputed bill was right: the analyst explains it
            case.ev(t, "DISPUTE_EXPLAINED", {"billingDocumentId": self.doc_id(doc), "total": doc["total"]}, cause)
        elif action == "fix_rate":
            self.rate_fix_t[i] = t
            case.ev(t, "RATE_FIXED", {"from": doc["rate"], "to": self.run.town.inst_rate[i]}, cause)
            case.ev(t + 0.0005, "BILL_REVERSED", {"billingDocumentId": self.doc_id(doc)})
            new = self.redo(doc, t + 0.001, rate=self.run.town.inst_rate[i])
            case.ev(t + 0.001, "REBILL", {"billingDocumentId": self.doc_id(new), "total": new["total"]})
        else:
            if actor not in ("RPA", "you"):
                case.ev(t, "ANALYST_OVERRIDE", {"action": "release bill"}, cause)
            self.release(doc, t + 0.0005)
            case.ev(t + 0.0005, "BILL_RELEASED", {"billingDocumentId": self.doc_id(doc), "total": doc["total"]})
            if action == "release_callback":
                case.ev(t + 0.02, "CX_CALLBACK", {"reason": "high bill"}, cause)
        if case.type == "BILL_DISPUTE" and self.collections is not None:  # decided: dunning on the account goes on
            self.collections.dispute_done(case.ref or self.account(doc), case.id, t)

    def proposal(self, case) -> str:
        if case.type == "RATE_CLASS":
            return "fix_rate"
        if case.type == "BILL_DISPUTE":  # the customer is right when the bill is off against the truth
            doc = self.docs[case.doc]
            right = "check_rebill" if wrong_bill(doc) else "explain"
            u = float(hash_u01(self.run.seed, P_BILL, self.inst_keys[doc["inst"]], case.month, 5))
            return right if u < self.run.cfg.process.analyst_accuracy else "explain"
        right = "rebill" if case.truth in ("read_error", "meter_fault") else \
            ("release_callback" if case.truth == "physics" else "release")
        u = float(hash_u01(self.run.seed, P_BILL, self.inst_keys[self.docs[case.doc]["inst"]], case.month, 3))
        return right if u < self.run.cfg.process.analyst_accuracy else "release"

    # ---- invoices ----------------------------------------------------------------------------------------------
    def invoice(self, day: int) -> None:
        run = self.run
        ks = self.to_invoice.pop(day, [])
        if not ks:
            return
        by_acct: dict[str, list[int]] = {}
        for k in ks:
            doc = self.docs[k]
            if doc["reversed"] is not None:
                continue
            by_acct.setdefault(self.account(doc), []).append(k)
        b, due_days = run.cfg_at(day).billing, run.cfg.customers_billing.due_days
        issued = run.next_bday(day, b.print_lag_days) if b.print_lag_days else day
        new: list[dict] = []
        for acct, docs in sorted(by_acct.items()):
            hold = run.hold_on(acct, day + 20.0 / 24)
            if hold is not None:  # an invoice hold on the account: its documents wait for invoice_unhold
                self.held.setdefault(acct, []).extend(docs)
                hold[2].ev(day + 20.0 / 24, "INVOICE_DEFERRED",
                           {"billingDocumentIds": [self.doc_id(self.docs[k]) for k in docs]})
                continue
            n = len(self.invoices)
            # A rebill of a document already invoiced credits the reversed version on this invoice.
            credit = round(sum(self.docs[self.docs[k]["replaces"]]["total"] for k in docs
                               if self.docs[k].get("replaces", -1) >= 0
                               and self.docs[self.docs[k]["replaces"]]["invoice"] >= 0), 2)
            inv = {"n": n, "id": f"INV-{acct}-{run.date_of(day).strftime('%Y%m%d')}", "account": acct, "docs": docs,
                   "created": day + 20.0 / 24, "issued": issued, "due": issued + due_days,
                   "total": round(sum(self.docs[k]["total"] for k in docs) - credit, 2), "payments": [], "dunning": [],
                   **({"credited": credit} if credit else {})}
            self.invoices.append(inv)
            new.append(inv)
            for k in docs:
                self.docs[k]["invoice"] = n
        if self.collections is not None:
            self.collections.issue(new)

    def account(self, doc: dict) -> str:
        if doc.get("carried") is not None:
            return doc["carried"]["account"]
        return self.run.town.contract_at(int(self.main[doc["inst"]]), int(np.floor(self.run.read_t[
            self.main[doc["inst"]], doc.get("from", doc["month"] - 1)])))[1]

    def doc_id(self, doc: dict) -> str:
        c = doc.get("carried")
        if c is not None:
            return c["id"] + (f"-v{doc['version']}" if doc["version"] > 1 else "")
        tw = self.run.town
        stamp = self.run.date_of(int(tw.read_day[self.main[doc["inst"]], doc["month"]])).strftime("%Y%m")
        return f"BD-{tw.inst_ids[doc['inst']]}-{stamp}" + (f"-v{doc['version']}" if doc["version"] > 1 else "")

    # ---- payments and collections (day by day with the run) ------------------------------------------------------
    def start_collections(self, opening=None) -> None:
        """Payments, dunning and collections work per account (utilsim/m2c/collections.py), from the first day;
        ``opening(collections)`` first puts in a closed year's accounts and scheduled events."""
        from utilsim.m2c.collections import Collections

        self.collections = Collections(self.run)
        if opening is not None:
            opening(self.collections)
        self.collections.start()

    def collect(self) -> None:
        """After the last day: the rest of the year's collections events."""
        self.collections.finish()

    def balance(self, acct: str, T: float) -> float:
        return round(sum(a for t, _, a, _ in self.ledger.get(acct, []) if t <= T), 2)


def _winter(d: date) -> bool:
    return (d.month, d.day) >= (11, 15) or (d.month, d.day) <= (4, 30)
