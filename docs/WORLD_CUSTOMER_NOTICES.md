# Delivered notices and payment-help contacts

The optional `world-customer-notices/1` model generates simulated customer
requests for payment help from customer-known evidence. It creates no invoice,
arrangement, enterprise case, queue work, balance adjustment, or settlement.
Its explicit administrator assumptions are illustrative, not calibrated behavior.

## Eligibility and ownership

A reaction requires an actually delivered notice accepted through the existing
trusted `customer_finance.receive_delivery` callback. That callback requires an
already delivered matching invoice, current occupied recipient/cohort, pinned
world/run identity and a nonfuture delivery timestamp. Merely creating a document
or receiving its transport acknowledgment does not establish customer knowledge.
There is no public ingestion route or administrator button to invent evidence.

On each physical UTC day, after recurring income/essential expenses and before
new utility payment reservations, a matching occupied cohort can react when:

* The delivered invoice is due and has customer-known unpaid value.
* The portion not already reserved for that invoice exceeds available cash after
  **all** pending reservations and the essential payment reserve.
* Notice reactions are active and the episode's noticing/repeat rules allow it.

Concretely, compare `max(0, original amount - confirmed net settlements - this
invoice's pending reservations)` with `max(0, cash - all pending reservations -
essentialReserveCents)`. An entirely reserved invoice is pending provider
processing, not a new financial shortfall. A partial reservation reduces both
the unfunded obligation and spendable cash; it is never counted twice.

Cashflow can remove a shortfall before evaluation. Payment-policy activity is
independent of notice activity. A random decision not to pay does not itself
prove inability to pay. The model reads only the world finance owner's delivered
knowledge and cash; it does not inspect private enterprise receivables.

## Configure and inspect

Open **Payment-help contacts** from Customer cash and payments. The policy is
world-wide and applies only to configured finance profiles with qualifying
evidence. `POST /api/customer-notices` calls `customer_notices.command` with
exactly:

```json
{
  "schemaVersion": "world-customer-notices/1",
  "commandId": "notice-policy-1",
  "environmentId": "EXAMPLE",
  "runId": "EXAMPLE",
  "worldFingerprint": "current-world-fingerprint",
  "actorId": "world-admin",
  "expectedRevision": 0,
  "effectiveDate": "2026-01-01",
  "action": "configure",
  "active": true,
  "noticeProbabilityPerDay": 0.5,
  "deliveryDelaySeconds": 86400,
  "repeatAfterDays": 3,
  "maxContacts": 3,
  "reason": "Explicit scenario assumptions",
  "causalReference": "scenario-1"
}
```

The defaults are inactive, probability 0.5, one-day delivery delay, three days
between contacts and three contacts per episode. Probability is 0–1; delay is
0–2,592,000 whole seconds; repeat interval is 1–365 whole days; maximum contacts
is 1–10. Identity, current physical date and policy revision must match. Unknown
fields and invalid values fail before migration. Exact command retries return
their original result after time/configuration changes; changed retries fail.

Noticing uses an independent seeded episode/day draw until first noticed. Once
noticed, continuing eligible conditions permit bounded repeats. One episode is
retained per original recipient/cohort/invoice. Additional notice deliveries,
temporary funding, settlement, return or pause never reset its attempt count.
The first delivered notice remains the source reference. An administrator may
explicitly raise the configured maximum; previously consumed attempts still count.
After settlement or sufficient funding new contacts stop; a later genuine
shortfall may resume within the same remaining attempt budget. Acceptance by a
recipient alone is not resolution. Cohort changes permanently stop the old
profile's new reactions; existing delayed intentions remain immutable.

`GET /api/customer-notices?after=0&limit=25` is administrator history, including
delayed messages, transport receipts/errors, counts, policy and revision.
`customer_notices.inspect` uses the same integer sequence cursor, default 25,
maximum 100. This administrator surface is not an authenticated worker sandbox.
The local server retains its origin/content-type checks and cruise ownership
guard. Managed worlds retain shared clock ownership; configuration does not
advance them. Lost command responses retain the exact command across reloads.

## Separate recipient boundary

Existing `customer-contact-intent/1` physical symptom messages are unchanged.
Financial requests use `schemas/financial-contact-intent-1.schema.json` and
`GET /api/financial-contact-intents`, backed by `customer_notices.ready`.
The feed contains only committed messages available at the committed clock and
includes accepted messages for independent replay. It takes no future `asOf`.

Messages contain run, premise, simulated recipient, invoice and delivered-notice
references; document delivery/knowledge/noticing/creation/availability timestamps;
episode, attempt, previous-contact ID; and `payment_help` or
`repeat_payment_help`. They contain no cash balance, reserved amounts, policy,
private receivable truth, hidden cause, service-point fiction or commodity guess.
These are simulated cohort references, not authenticated caller identities.

Availability is physical-day finish plus configured delay, becoming observable
at the next committed daily boundary. The exclusive cursor is
`availableAt|sequence`, ordered by both indexed fields so shortening a later
policy delay cannot hide earlier messages. Save the last consumed item's cursor
even when `nextAfter` is null. Page size defaults to 25 and is bounded at 100.

`customer_notices.relay(world, send, limit=25)` supplies pending available
messages to an adapter callback **outside** the world database transaction.
The recipient must durably deduplicate `(runId,id)`, compare `stable(intent)` and
return exactly:

```python
{'id': intent['id'], 'runId': intent['runId'], 'fingerprint': stable(intent),
 'status': 'accepted', 'receiptId': durable_recipient_receipt_id}
```

`stable(intent)` is the existing world SHA-256 fingerprint of canonical JSON's
one-element array containing the intent, shortened to 24 hex characters. Missing,
changed or invalid acknowledgments leave the intention pending. Only the error
class is retained. Lost replies/concurrent relays can redeliver the exact message;
the recipient provides deduplication, not exactly-once transport. A different
receipt for an already accepted concurrent delivery is rejected. Acceptance
neither resolves an episode nor creates an enterprise arrangement automatically.

There is no actual call-center adapter in this increment. Authentication of the
real document producer, recipient handling, caller verification, dispositions,
arrangements and enterprise queue ownership remain explicit integration work.

## Durability and validation

Activation makes an additive SQLite migration and records a consistent rollback
backup at `customerNoticesRollbackBackup`. Reads do not enable the feature.
A durable rowid watermark indexes newly learned trusted finance-inbox evidence
once per day; it does not rescan every profile's full inbox. First processing
also includes historical delivered notices without backdating contact decisions.
Per-premise notice lookup and availability/pending feeds are indexed.

Projection updates, customer episodes, outbox events and the physical day share
the existing transaction. Interruptions roll everything back together. Pausing
preserves history and delayed delivery; reopening the same completed boundary
does not create new effects. Rollback is opening the retained pre-feature backup
with the earlier runtime, not removing live tables.

Focused suites: `tests/test_world_customer_notices.py` and
`tests/test_world_customer_notices_http.py`. They cover actual-notice requirements,
future/foreign evidence, reservations, household cashflow, settlement/return,
repeat caps, cohort replacement, invalid/stale commands, interruption/restart,
availability reordering, indexed pagination and strict/lost/concurrent receipts.

`scripts/check_world_customer_notices.py --engine-python <python> --out <new-dir>`
uses a disposable saved 570-premise town and eight explicit fixture households.
Real desktop controls produce 32 contacts, with 25/7 history pages, withheld
delayed feed, lost-response exact retry, pause and server restart. The 570-premise
source snapshot, historical exports, baseline backup and finance amounts remain
unchanged. Desktop widths 1440 and 960 have no external requests or page errors.
Fixture delivery is synthetic trusted test evidence, not live enterprise delivery
or acceptance, and this is not the 15,000-account/five-year benchmark.
