# Customer cash and payment intentions

This opt-in world model owns simulated household/business cash, delivered-document
knowledge, reservations, and provider-confirmed cash movements. It owns no enterprise
invoice, collections queue, financial transaction or journal. Default screen values
are illustrative scenario controls, not calibrated behavior. Recipient references
identify simulated cohorts, never authenticated named people.

## Operational boundaries and integration

`utilsim.world.customer_finance` provides:

* `command(world, payload)` — local administrator `configure` or `credit` command.
  Both require model `world-customer-finance/1`, commandId, environmentId, runId,
  worldFingerprint, actorId `world-admin`, expectedRevision, effectiveDate, premiseId,
  reason and causalReference. Run ID equals environment ID. The server must restrict
  this control to the local administrator; actorId text is not authentication.
* `inspect(world, premise)` — administrator-only summary with identity, through,
  revision, policy, cash, reserved cash, net settled cash and known outstanding.
* `daily(world, db, meta)` — call inside each physical day transaction, after applied
  occupancy changes and `contacts.daily`, before advancing `meta.through`. The
  production hook is included in `World.advance`. Intents become available at the
  next midnight. Decisions and reservations commit or roll back with that day.
* `receive_delivery(world, message)` — trusted **actually delivered** document
  callback. No public HTTP ingestion route. The adapter must authenticate the
  permitted simulated delivery producer, prove durable delivery, and bind the
  delivered recipient, premise, run and document reference. A supplied `status`,
  actor field or timestamp alone is not proof. Transport acceptance is insufficient.
* `ready(world, after=0, limit=25)` — versioned filtered payment-intent feed with
  integer sequence cursors and only currently available committed messages.
* `relay(world, send, limit=25)` — callback delivery without a database lock across
  the call. The recipient deduplicates by runId/id and compares `stable(intent)`.
  Return exactly `{id, runId, fingerprint, status: "accepted", receiptId}`.
  This confirms transport acceptance only; it does not spend cash or post anything.
* `provider_receipt(world, receipt)` — trusted simulated provider callback for full
  settlement/full return, plus terminal failure in receipt version 2. Authenticate the permitted provider outside this
  module and validate the original intent fingerprint. No public HTTP route.

Parent server integration for the standalone administrator screen:

* `/customer-finance` serves `customer-finance.html`; `/customer-finance.js` serves
  its script.
* `GET /api/customer-finance?premise=<id>` calls `inspect(world, premise)`.
* `POST /api/customer-finance` calls `command(world, payload)` using the same local
  origin/content-type restrictions as the existing world administrator controls.
* Do not expose the delivered-document or provider-receipt callbacks through this
  screen or through an unauthenticated ingestion route. It intentionally has no
  invoice creation or settlement buttons. It explains missing delivery evidence.

## Administrator commands

Configure additionally requires active (boolean), customerKind (`household` or
`business`), recipientRef (opaque cohort reference), cashCents,
essentialReserveCents, maxPaymentCents and paymentProbability (0–1).
All money is integer USD cents, bounded to 10^12; maxPaymentCents is positive.
After initial configuration cashCents must match current cash and recipientRef
cannot change. Credit instead adds a positive amountCents, with its own durable
command identity and causal reason. Reconfiguration cannot silently refill cash.
Commands reject stale world/run identity, date or revision. Exact retries return
their committed result even after a subsequent revision; changed retries fail.

## Knowledge and behavior

The delivery contract is `schemas/customer-finance-delivery-1.schema.json`.
Only a configured occupied cohort can learn an invoice. The immutable original
positive invoice amount and due date are supplied by actual delivered evidence;
the world cannot look into private billing tables. A notice must match an already
delivered invoice. Duplicate deliveries/notices cannot multiply the amount owed.
Future timestamps are rejected against committed world midnight, and older evidence
is learned at the current clock rather than replaying past decisions. Each invoice
ID is unique within the pinned run. No delivered document means no known debt and
no payment intention, regardless of cash or physical observations.

Each active occupied cohort considers due invoices in due-date/ID order once per
day. Its independent random stream uses seed, model version, recipient, invoice,
day and decision kind. An installment is bounded by known unpaid amount, maximum
installment and cash minus existing reservations minus essential reserve. Only
one reserved intention per invoice can be in flight. A confirmed settlement allows
a later installment; a lost acknowledgment cannot generate another reservation.

The filtered `payment-intent/1` contract is in `schemas/payment-intent-1.schema.json`.
It contains run/premise/recipient references, invoice and delivered-document IDs,
amount, currency and availability. It excludes cash, essential reserves, policy
probabilities, occupancy stamps and private enterprise truth. Causal events retain
configuration and delivery lineage in the administrator-owned world event log.

## Cash conservation and explicit limits

`cashCents` includes reserved cash. `reservedCashCents` is the subset held for
intentions; `netSettledCashCents` is confirmed cash spent less confirmed returns.
`knownOutstandingCents` is delivered original invoice amounts minus confirmed net
settlements. It is customer knowledge, not an enterprise accounts-receivable
balance. An intention or accepted delivery never reduces it.

Full settlement decreases cash and reservation by exactly the intention amount,
increasing net settlements. A full return reverses that settlement and restores
known outstanding; it does not retain a reservation. The original settlement
receipt must be referenced. Returned money may be reconsidered on a later day.
Original receipt retries are no-ops; distinct receipt IDs attempting the same
transition are rejected without any cash movement. The provider contract is
`schemas/customer-finance-provider-receipt-1.schema.json`. Provider timestamps must
follow intent availability and not exceed the committed clock. A return cannot
predate its referenced settlement. A valid provider settlement can arrive before
the transport acknowledgment, supporting an acknowledgment lost after processing.

Partial settlements/returns, provider cancellation, fees, other currencies,
invoice balance revisions, credit notes, invoice generation and enterprise posting
are explicitly unsupported. Optional recurring income and essential expenses are
configured separately through [household cashflow](WORLD_CUSTOMER_CASHFLOW.md)
within this same finance owner. They never spend provider-reserved funds or create
debt from unfunded necessities. A reserved intention
with no supported provider confirmation remains reserved; the model never guesses
a failure or releases funds silently. Cohort migration is unsupported: vacancy or
applied occupancy changes freeze new behavior, while previous intentions can still
settle or return. New occupants cannot inherit predecessor invoice knowledge.

### Terminal provider failure

`schemas/customer-finance-provider-receipt-2.schema.json` adds `status: failed`
to the same exact receipt fields. Version 1 remains unchanged and rejects failure.
Version 2 also accepts full settlement and full return with the existing rules.
A failed receipt must match the complete original intent amount and fingerprint,
use `settlementReceiptId: null`, and refer to a currently reserved intention.
Its timestamp must follow availability and cannot exceed the committed world clock.

Failure is an authenticated provider's durable terminal decision that the intent
has never settled and will never settle. It releases only that intent's cash
reservation; cash, settled money and known invoice debt do not change. An atomic
`CustomerPaymentFailed` event and receipt retain the evidence. Identical retries
return the original result, including after another intention has reserved cash.
Different receipt IDs cannot repeat the failure, and settlement or return of the
failed intent is rejected. Failure cannot refund a previously settled intention.
On a later processed day, the existing customer policy may generate a new payment
intention with a new ID; the failed intention is never revived or silently retried.

A timeout, exception, lost acknowledgment or unconfirmed processing delay is not
terminal evidence and never releases cash. The old intention remains in the
immutable feed, and its delivery acknowledgment may still be pending. Providers
must retain their original terminal decision and deduplicate any transport replay;
they must never process that replay as a new payment. Receiving failure evidence
does not manufacture transport acceptance. No public HTTP endpoint or settlement
button is added, and the caller remains responsible for authenticating the provider.
There is no enterprise posting, payment reversal or collections-queue change.

Focused failure checks: `pytest tests/test_world_customer_finance_failures.py`.
They cover conservation, exact retries/conflicts, lost acknowledgment, independent
new intentions, timestamp/identity validation, rollback, competing provider decisions
and unchanged version-1 behavior.

## Durability, scale and checks

Activation creates additive finance tables plus a unique rollback backup. Reads
do not activate the feature. Inbox results, commands, decisions, reservations and
outbox envelopes are durable. Unknown recipient acknowledgments retain the exact
message for retry; stored errors include only exception class. Recovery uses the
same world database and stable IDs. No live payment network sender is provided.

Daily processing decodes the town snapshot once, overlays applied occupancy once,
and uses `(premise,due,id)` indexed invoice lookups. Feed/admin metadata reads select
only small identity/clock keys, excluding saved physical-network catalogs.

Focused tests: `pytest tests/test_world_customer_finance.py`. The suite covers
cash conservation, retries, interruption/rollback, seeded reopen/chunking, future
evidence, unsupported receipts, multiple invoices, schema filtering, occupancy
changes, and a 300-profile snapshot/index work bound.

Fresh-database acceptance: `python scripts/check_world_customer_finance.py`. Its
explicit synthetic delivery/provider fixtures demonstrate 10000 cash -> 4000
reserved -> 6000 cash after settlement -> 10000 after return, with no enterprise
posting. It deletes only its temporary test directory via the standard temporary
directory lifecycle; it never reads or writes a saved live run.
