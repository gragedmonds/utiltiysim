# Customer awareness and contact intents

The opt-in `world-contacts/1` model turns experienced service symptoms into
durable `customer-contact-intent/1` messages. It does not create service tickets,
book staff or resolve investigations. The world owns customer experience;
the enterprise recipient owns acceptance and subsequent handling.

## Operate the model

Open **Customer awareness** from world controls (`/contacts`). Enable generation,
choose the daily noticing probability, delivery delay, repeat interval and
maximum contacts, and save with a reason. Advance the world from world controls.
The history distinguishes delayed/available and pending/accepted intents, with
25 rows per page. A lost save response exposes a retry of the same command,
retained across a page reload. These are administrator scenario controls,
not SAP or worker screens.

Defaults are illustrative: disabled, 0.5 daily noticing probability, one day
delivery delay, three days between contacts and three contacts per experience.
The first valid policy command creates additive tables and a rollback backup.
Invalid commands do not migrate the world. Policy changes require the exact
world identity, current physical date, revision and local administrator actor;
same-command retries return the original result. Existing historical exports,
snapshots and saved policies are preserved. Rollback means opening the retained
pre-feature backup with the prior runtime, not deleting tables from a live world.

## Experience and knowledge

- Electricity/gas network service loss, water-main isolation loss and visible
  sewer overflow can start an experience at an occupied, commissioned service.
  A break without experienced loss does not itself trigger a contact.
- Hidden downstream leaks and missing meter transmissions are not customer
  knowledge. A customer can experience a supply loss while telemetry is absent.
- Noticing uses an independent seed/experience/day random draw. Awareness is
  dated when noticed, never backdated to a hidden fault's onset.
- Continuing symptoms can create bounded repeats linked to the prior intent.
  Receipt acceptance alone does not stop repeats. Physical restoration or
  vacancy ends that experience but preserves already-created, delayed contacts.
  Pausing generation preserves pending delivery and tracks ended experiences.
- Applied occupancy changes start a new experience context. This context is
  premise occupants, not an authenticated or durable named household/person.
  Merely scheduling or canceling a future change does not reset memory.

Daily effects, experience updates, causal events, contact outbox rows and clock
advancement commit together. A failed day leaves none of that day's contacts.
Internal events reference the source effect table, asset and day plus the saved
policy; recipient messages contain only the customer's observed symptom and
stable service/premise/experience IDs. They exclude hidden fault IDs, exact
physical quantities, diagnosis, internal asset IDs and policy parameters.
Sewer uses the existing derived sewer service identity, never a fictitious meter.

## Recipient contract and recovery

Schema: `schemas/customer-contact-intent-1.schema.json` (unknown fields forbidden).
`GET /api/contact-intents?limit=25&after=<cursor>` returns currently available
intents, bounded at 100 per page. Availability uses the committed world clock;
a caller cannot pass a future `asOf` date. Each item has an availability/sequence
cursor. Save the last consumed item's cursor even when `nextAfter` is null.
Sequence alone is insufficient: a newer policy may shorten delays so messages
become available in a different order. The feed includes accepted messages for
independent consumers/replay; consumers must deduplicate.

The current physical clock advances at UTC day boundaries. A subdaily delay
becomes deliverable at the next committed daily boundary. This does not claim
fine-grained call scheduling or local-calendar workforce operation. Observation,
notice, creation and availability timestamps are explicit; precise recipient
receipt/processing timestamps belong to the future recipient adapter.

`contacts.relay(world, send, limit=25)` is the adapter seam. It invokes a supplied
local callback with pending, available intents, outside a SQLite transaction.
There is no live sender or HTTP action that fabricates acceptance. A recipient
must commit its own inbox/handling work atomically, deduplicate by environment
and intent ID, reject changed payloads under the same ID, and return:

```python
{
    "id": intent["id"],
    "environmentId": intent["environmentId"],
    "fingerprint": stable(intent),
    "status": "accepted",
    "receiptId": durable_recipient_receipt_id,
}
```

Use `utilsim.world.store.stable(intent)` for this version's fingerprint: SHA-256
of the UTF-8 canonical JSON **one-element array containing the intent**, keys
sorted, ASCII escaping enabled, separators `(',', ':')`, no NaN; first 24 hex
characters. An accepted receipt has exactly these fields. Lost/invalid replies
leave the intent pending with the error class and attempt count. Reopening and
retrying may send it again; concurrent senders may also deliver duplicates.
Recipient deduplication gives one recipient effect, not exactly-once transport.
An accepted receipt is not evidence of a ticket's resolution or physical repair.

The administrator endpoint `/api/contacts` includes future history and policy.
The local world server remains an administrator surface; it is **not** a sandbox
for worker/AI access. An eventual actor gateway must expose only the filtered
recipient contract and must not grant access to the world database/admin routes.

## Acceptance and remaining scope

Run:

```powershell
python -m pytest tests/test_world_contacts.py -q
python scripts/check_world_contacts.py --db <existing-world.sqlite> --viewer-dir packages/town-viewer/dist --out <new-output-directory>
```

The browser checker operates on a backup copy and a separate disposable SQLite
recipient inbox. On the 608-premise neighborhood fixture, 578 occupied services
produced two rounds of contacts: all 1,156 were accepted once despite a committed
recipient receipt being lost and both world/server reopening. It checks bounded
pages, delayed knowledge, repeats, restoration retaining intents, same-command
retry, source/history preservation and desktop layouts at 1440 and 1024 pixels.
Both layouts were visually inspected; no browser errors or external requests.
The focused suite also covers four-domain symptoms, concurrent relays,
corruption rejection, daily rollback, invalid policies and deterministic replay.

A separate 2,268-premise, 31-day run reopened halfway through and retained 6,196
available contacts plus one correctly withheld future contact. All available
records paged without duplicates or omissions; repeating the completed boundary
created no new events. Advancement took 45.805 seconds and the two bounded
history/feed queries took 0.006 seconds on the local Windows host. SQLite
integrity passed. This is a medium world diagnostic, not a platform scale result.

8 October 2026 validation: full non-slow Python run passed 743 tests (two existing
dependency warnings). The final 74 contact/water-main/occupancy checks cover two
late contact additions and the bounded HTTP/query refinements after collection.
All 291 viewer tests, 11 conformance checks, repository lint, JavaScript syntax
and diff checks pass. The copied browser acceptance was repeated on the final
runtime and again preserved the original world with all 1,156 receipts deduplicated.

Still open: actual Service Cloud/IS-U recipient integration, authenticated caller
identities, invoice/notice delivery, high-bill reactions, cash constraints/payment
intentions, agent handling/dispositions and behavior changed by real interactions.
This delivery does not claim the full customer lifecycle, finite workforce loop,
full AI isolation, or the 15,000-account five-year platform benchmark. It changes
the SQLite world owner only; no enterprise/PostgreSQL schema changed.
