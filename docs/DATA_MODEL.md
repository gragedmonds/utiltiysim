# Data model

Physical equipment, commercial ownership and observations are separate.

```
Premise ─┬─ Building (footprint, height)            Business partner ── Contract account(s)
         ├─ Parcel                                                     │
         └─ Service point (per commodity) ── Installation ── Contract(s) (validFrom/validTo)
                       │                         │
                       └─ Meter ── Register(s)   └─ Tariff assignment ── Tariff
Meter reading unit (route) ── Portion (billing business day) ── Read schedule (per month)
Read (observation + truth) → [M3] VEE decision (revision) → Billing document → Invoice → Payment
```

* A move-out ends a contract; a move-in starts one; vacancy is the gap. Premises are never created by moves.
* A meter exchange will end a device's validity and start another (M3); registers belong to meters.
* Solar homes have an `export` register (OBIS 2.8.0) next to `import` (1.8.0). Consumption is never negative.
* Reads carry `truth` for scoring. A missing read has `registerValue`, `consumption` and `readAt` null and keeps
  `scheduledReadAt`; it is never zero.
* Edits and VEE decisions (M3) are revisions linked to the original read id; observations are immutable.
* `readStatus`, `veeStatus`, bill status and invoice status are separate fields; one badge must not conflate them.
* Read types: `actual` (observed; a physical zero is still `actual`/`received`), `missing` (polling or
  communication failure, values null, `reasonCode` says why), `estimated` (planned estimate), `adjusted` (M3 VEE
  revision). The engine never labels plausibility; VEE decides. Full table: `docs/CONTRACT.md` § Reads.

Read schedules: each route belongs to a portion; the portion is the business day of the month on which the route
is read (Ontario holidays excluded). AMI reads land at 02:00 local, AMR van reads 09:30–14:30, manual reads
09:00–15:00. Period boundaries are the previous and current scheduled reads, evaluated in the town's timezone and
stored in UTC; a period that spans a DST change is an hour shorter or longer in UTC and is not corrected.

Field-level mapping to SAP IS-U and to the m2c.vee normalized read: `docs/SCHEMA_MAPPING.md`.
