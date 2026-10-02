"""Billing, invoicing, payments and collections for a meter-to-cash run.

The run calls in at fixed points of each business day:
- **19:30:** billing documents for installation periods whose reads are all released;
- **20:00:** invoices that consolidate an account's released documents.

Bill checks block a document into the ``BILLING`` queue:
- a high bill against the installation's recent history;
- a large credit;
- a wrong rate class in billing master data (seeded data errors).

Analysts work the queue: they release the bill, rebill it on an estimate, or fix the rate class. Payments and dunning
run after the year, because nothing upstream depends on them:
- payment timing comes from the account's payment method and its partner's payer profile;
- pre-authorized debits can be returned;
- unpaid invoices get reminders, overdue notices with late fees, and disconnection notices (held by the winter
  moratorium for electricity and water).
"""

from __future__ import annotations

from datetime import date

import numpy as np

from utilsim.core.ids import str_key
from utilsim.core.rng import hash_u01
from utilsim.m2c import billing as bl
from utilsim.m2c import catalog as cat
from utilsim.m2c import registers as regs

P_BILL = 36
INF = float("inf")
STATUS = ("created", "blocked", "released", "reversed")


def _swap(rate: str) -> str:
    return ("COM-" + rate[4:]) if rate.startswith("RES-") else ("RES-" + rate[4:]) if rate.startswith("COM-") else rate


class Books:
    def __init__(self, run) -> None:
        from utilsim.m2c.run import parse_day

        self.run = run
        tw, b = run.town, run.cfg.billing
        n = len(tw.inst_ids)
        self.change = float(parse_day(b.rate_change_date, 10 ** 6))
        self.inst_keys = np.array([str_key(x) for x in tw.inst_ids], dtype=np.int64)
        self.main = np.array([rows[np.argmax(tw.direction[rows] == "import")] if len(rows) else -1
                              for rows in tw.inst_rows], dtype=np.int64)
        self.export_row = np.array([next((int(r) for r in rows if tw.direction[r] == "export"), -1)
                                    for rows in tw.inst_rows], dtype=np.int64)
        months = np.arange(1, 13)
        p = b.data_error_rate / 1000.0 / 12.0 * bool(run.cfg.anomalies.enabled)
        hit = hash_u01(run.seed, P_BILL, self.inst_keys[:, None], 1, months[None, :]) < p
        first = np.where(hit.any(1), hit.argmax(1) + 1, 0)
        self.rate_err_t = np.where(first > 0, regs.MONTH_START[first] + 0.0, INF)
        self.rate_fix_t = np.full(n, INF)
        self.doc_of = np.full((n, 13), -1, dtype=np.int64)
        self.docs: list[dict] = []
        # Registers per installation and month still waiting for release; at zero the period is ready to bill.
        self.pending = np.repeat(np.array([len(r) for r in tw.inst_rows], dtype=np.int64)[:, None], 13, axis=1)
        self.ready: list[tuple[int, int]] = []
        self.to_invoice: dict[int, list[int]] = {}
        self.invoices: list[dict] = []
        self.ledger: dict[str, list[tuple]] = {}

    # ---- documents -------------------------------------------------------------------------------------------
    def rate_at(self, i: int, t: float) -> str:
        rate = self.run.town.inst_rate[i]
        return _swap(rate) if self.rate_err_t[i] <= t < self.rate_fix_t[i] else rate

    def quantities(self, i: np.ndarray, m: np.ndarray, src: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Import and export quantities per installation period from register values ``src`` (released or truth)."""
        digits = self.run.town.digits
        out = []
        for rows in (self.main[i], self.export_row[i]):
            ok = rows >= 0
            rr = np.where(ok, rows, 0)
            mod = 10.0 ** digits[rr]
            d = src[rr, m] - src[rr, m - 1]
            out.append(np.where(ok, np.where(d < -0.5 * mod, d + mod, d), 0.0))
        return out[0], out[1]

    def expected(self, i: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        exp = self.run.expected
        rows = self.export_row[i]
        return exp[self.main[i], m], np.where(rows >= 0, exp[np.maximum(rows, 0), m], 0.0)

    def compute(self, items: list[tuple[int, int, str, float, float]]) -> list[tuple]:
        """[(inst, month, rate, q_imp, q_exp)] → [(subtotal, tax, total)] in the same order (vectorised per rate)."""
        run, tw = self.run, self.run.town
        out: list[tuple] = [None] * len(items)  # type: ignore[list-item]
        groups: dict[str, list[int]] = {}
        for k, (_, _, rate, _, _) in enumerate(items):
            groups.setdefault(rate, []).append(k)
        pct = run.cfg.billing.rate_change_pct
        for rate, ks in groups.items():
            tariff = tw.tariffs.get(rate, {})
            i = np.array([items[k][0] for k in ks])
            m = np.array([items[k][1] for k in ks])
            rows = self.main[i]
            comm = str(tw.commodity[rows[0]])
            _, sub, tax = bl.charges(tariff, comm, np.array([items[k][3] for k in ks]),
                                     np.array([items[k][4] for k in ks]), run.read_t[rows, m - 1], run.read_t[rows, m],
                                     self.change, pct, self.export_row[i] >= 0)
            for j, k in enumerate(ks):
                out[k] = (float(sub[j]), float(tax[j]), round(float(sub[j] + tax[j]), 2))
        return out

    def lines(self, doc: dict) -> list[dict]:
        run, tw = self.run, self.run.town
        i, m = doc["inst"], doc["month"]
        rows = self.main[[i]]
        comps, _, _ = bl.charges(tw.tariffs.get(doc["rate"], {}), str(tw.commodity[rows[0]]), np.array([doc["qImp"]]),
                                 np.array([doc["qExp"]]), run.read_t[rows, m - 1], run.read_t[rows, m], self.change,
                                 run.cfg.billing.rate_change_pct, np.array([self.export_row[i] >= 0]))
        return bl.lines(comps, 0)

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
        qi, qe = self.quantities(i, m, run.released)
        ti, te = self.quantities(i, m, run.truth)
        ei, ee = self.expected(i, m)
        totals = self.compute(list(zip(i.tolist(), m.tolist(), rates, qi.tolist(), qe.tolist(), strict=True)))
        true_totals = self.compute(list(zip(i.tolist(), m.tolist(), right, ti.tolist(), te.tolist(), strict=True)))
        expected = self.compute(list(zip(i.tolist(), m.tolist(), right, ei.tolist(), ee.tolist(), strict=True)))
        b = run.cfg.billing
        for k, (a, mm) in enumerate(ready):
            sub, tax, total = totals[k]
            doc = {"k": len(self.docs), "inst": a, "month": mm, "rate": rates[k], "qImp": float(qi[k]),
                   "qExp": float(qe[k]), "subtotal": sub, "tax": tax, "total": total, "truthTotal": true_totals[k][2],
                   "expectedTotal": expected[k][2], "created": t, "released": None, "reversed": None, "version": 1,
                   "case": -1, "invoice": -1, "replaces": -1}
            self.docs.append(doc)
            self.doc_of[a, mm] = doc["k"]
            exp = expected[k][2]
            kind = None
            if rates[k] != right[k]:
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
        case = run.new_case(day=int(t), r=r, m=m, kind=kind, disposition=-1, impact=impact,
                            confidence=float("nan"), truth=truth, queue="BILLING", t=t, cause_payload={
                                "billingDocumentId": self.doc_id(doc), "total": doc["total"]})
        case.doc = doc["k"]
        doc["case"] = case.idx

    def release(self, doc: dict, t: float) -> None:
        doc["released"] = t
        day = int(t)
        inv = day if (t - day) < 20.0 / 24 and day in self.run.bday_set else self.run.next_bday(day)
        self.to_invoice.setdefault(inv, []).append(doc["k"])

    def redo(self, doc: dict, t: float, *, rate: str | None = None, estimate: bool = False) -> dict:
        """Reverse ``doc`` and issue version 2 (estimated quantities or a corrected rate), released at ``t``."""
        run = self.run
        i, m = doc["inst"], doc["month"]
        doc["reversed"] = t
        qi, qe = doc["qImp"], doc["qExp"]
        if estimate:
            rows = [r for r in (self.main[i], self.export_row[i]) if r >= 0]
            est = [float(run.expected[r, m]) for r in rows]
            qi, qe = est[0], (est[1] if len(est) > 1 else 0.0)
        rate = rate or doc["rate"]
        ((sub, tax, total),) = self.compute([(i, m, rate, qi, qe)])
        new = {**doc, "k": len(self.docs), "rate": rate, "qImp": qi, "qExp": qe, "subtotal": sub, "tax": tax,
               "total": total, "created": t, "released": None, "reversed": None, "version": doc["version"] + 1,
               "invoice": -1, "replaces": doc["k"], "estimated": estimate}
        self.docs.append(new)
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

    def proposal(self, case) -> str:
        if case.type == "RATE_CLASS":
            return "fix_rate"
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
        b, due_days = run.cfg.billing, run.cfg.customers_billing.due_days
        issued = run.next_bday(day, b.print_lag_days) if b.print_lag_days else day
        for acct, docs in sorted(by_acct.items()):
            n = len(self.invoices)
            inv = {"n": n, "id": f"INV-{acct}-{run.date_of(day).strftime('%Y%m%d')}", "account": acct, "docs": docs,
                   "created": day + 20.0 / 24, "issued": issued, "due": issued + due_days,
                   "total": round(sum(self.docs[k]["total"] for k in docs), 2), "payments": [], "dunning": []}
            self.invoices.append(inv)
            for k in docs:
                self.docs[k]["invoice"] = n

    def account(self, doc: dict) -> str:
        return self.run.town.contract_at(int(self.main[doc["inst"]]), int(np.floor(self.run.read_t[
            self.main[doc["inst"]], doc["month"] - 1])))[1]

    def doc_id(self, doc: dict) -> str:
        tw = self.run.town
        stamp = self.run.date_of(int(tw.read_day[self.main[doc["inst"]], doc["month"]])).strftime("%Y%m")
        return f"BD-{tw.inst_ids[doc['inst']]}-{stamp}" + (f"-v{doc['version']}" if doc["version"] > 1 else "")

    # ---- payments and collections (after the year) -------------------------------------------------------------
    def collect(self) -> None:
        run, b = self.run, self.run.cfg.billing
        tw = run.town
        keys = np.array([str_key(inv["id"]) for inv in self.invoices], dtype=np.int64)
        draws = hash_u01(run.seed, P_BILL, keys[:, None], np.arange(2, 6)[None, :]) if len(keys) else np.zeros((0, 4))
        for inv, u in zip(self.invoices, draws, strict=True):
            acct = inv["account"]
            led = self.ledger.setdefault(acct, [])
            led.append((float(inv["issued"]), "invoice", inv["total"], inv["id"]))
            if inv["total"] <= 0:
                inv["paid"] = float(inv["issued"])
                continue
            method = tw.account_method.get(acct, "online")
            profile = tw.account_profile.get(acct, "on_time")
            due = float(inv["due"])
            paid: float | None
            if method == "pre_authorized_debit":
                paid = due + 0.3
                if u[0] < b.pad_reject_rate:
                    inv["payments"].append({"at": paid, "amount": inv["total"], "status": "rejected"})
                    led.append((paid + 2, "nsf_fee", b.nsf_fee, inv["id"]))
                    inv["dunning"].append((paid + 2, "PAYMENT_REJECTED"))
                    paid = due + 10 + float(u[1]) * 10
            elif profile == "on_time":
                paid = float(inv["issued"]) + 2 + float(u[1]) * max(1.0, due - inv["issued"] - 2) + \
                    (3 if method == "cheque" else 0)
            elif profile == "late":
                paid = due + 3 + float(u[1]) * 37
            else:
                paid = due + 20 + float(u[2]) * 60 if u[3] < 0.5 else None
            inv["paid"] = paid
            if paid is not None:
                inv["payments"].append({"at": paid, "amount": inv["total"], "status": "received"})
                led.append((paid, "payment", -inv["total"], inv["id"]))
            for days, kind in ((b.reminder_days, "DUNNING_REMINDER"), (b.notice_days, "DUNNING_NOTICE"),
                               (b.disconnect_days, "DISCONNECT_NOTICE")):
                at = due + days
                if (paid is not None and paid <= at) or at >= 365:
                    break
                if kind == "DUNNING_NOTICE":
                    led.append((at, "late_fee", round(inv["total"] * b.late_fee_pct / 100.0, 2), inv["id"]))
                if kind == "DISCONNECT_NOTICE" and b.winter_moratorium and _winter(run.date_of(int(at))) and any(
                        str(tw.commodity[self.main[self.docs[k]["inst"]]]) in ("electric", "water")
                        for k in inv["docs"]):
                    kind = "MORATORIUM_HOLD"
                inv["dunning"].append((at, kind))
        for led in self.ledger.values():
            led.sort(key=lambda e: e[0])

    def balance(self, acct: str, T: float) -> float:
        return round(sum(a for t, _, a, _ in self.ledger.get(acct, []) if t <= T), 2)


def _winter(d: date) -> bool:
    return (d.month, d.day) >= (11, 15) or (d.month, d.day) <= (4, 30)
