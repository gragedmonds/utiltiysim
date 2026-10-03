# Schema mapping

## Prototype `utility-town/1.0` → engine `utility-town/2.0`

2.0 keeps the 1.0 collections, field names and id grammar, but it is its own version: it validates against
`schemas/utility-town-2.0.schema.json` and the viewer's receiver, not against the 1.0 schema (whose
`schemaVersion` is a constant and whose read and topology rules differ). No 1.0 projection is produced.
Differences:

| Area | 1.0 (prototype) | 2.0 (engine) |
|---|---|---|
| Road geometry | OSM roads scaled to fit the home count | real metres, never scaled; a synthetic street grid sized for the home count (towns are generic: no real place's streets) |
| Identity | `id` | `id`, `topologyRevision`, `indexRevision` (shared with every state frame) |
| Counts | `count` = homes | `count` = `premises.length`; `homes` = residential |
| Topology | strict tree, parent chain = route | construction forest plus loop edges; `enabled` on every edge; `sourceIds` |
| State | flows computed in the viewer | complete `utility-state/1.0` frames and `utility-replay/1.0` from the engine; `null` = unavailable |
| Lots | a home every 23 m along roads | parcels cut per street side (`parcels[]`), houses inside them |
| Terrain | analytic `terrain(x,z)` in the viewer | flat row-major `terrain` heightmap (`order: row-major-z-positive`); `elevationM` on nodes |
| Utility offsets | viewer shifts water +2.8 / gas −2.8 in z | geometry already offset (`source.utilityOffsets = "geometry"`) |
| Sizing | illustrative | engineering step tables (`sizeMm`, `nominalLabel`, `capacityKVA`, `designKVA`, `ratingKVA`, `designM3h`, `designFireLps`) |
| Electric | one transformer per 8 homes, 69 kV | transformer groups by count/span/kVA, feeders, 1φ laterals with phases, OH/UG by era, poles, ties, reclosers, fuses; 115 kV in, 13.8 kV primary (configurable) |
| Gas | trunk → mains → services | MP mains with service regulators plus optional LP core behind `district_regulator` nodes; loops |
| Water | trunk → mains → services | pump station, elevated tank(s), zones, loops, hydrants, valves; fire-flow sizing |
| Customers | one contract per service | contract history (rentals, vacancies), business partners, tariffs with rates, routes and schedules |
| Reads | calendar-month June reads, UTC | read dates from each route's scheduled business day (local time → UTC), technology-specific read hour |
| New collections | – | `parcels, facilities, districts, parks, businessPartners, tariffs, mrus, portions, readSchedules, amiNetwork, stats` |

## SAP IS-U aliases

| Engine field | SAP IS-U | Table |
|---|---|---|
| `businessPartners[].sapPartner` | Business partner (PARTNER) | BUT000 |
| `accounts[].sapContractAccount` | Contract account (VKONT) | FKKVKP |
| `contracts[]` (`validFrom`/`validTo`) | Contract (VERTRAG; EINZDAT/AUSZDAT move-in/out) | EVER |
| `installations[]` (`sparte`, `mruId`, `rateCategory`) | Installation (ANLAGE; SPARTE, ABLEINH, TARIFTYP) | EANL |
| `premises[]` | Premise (VSTELLE) | EVBS |
| `buildings[]` / `premises[].address` | Connection object (HAUS) | EHAU |
| `meters[]` (`serialNumber`, `registerDigits`, `multiplier`) | Device (EQUNR/GERAET; STANZVOR, ZWFAKT) | EQUI / EGERH |
| `registers[]` (`obis`, `direction`) | Register (ZWNUMMER; 1.8.0 delivered, 2.8.0 received) | ETDZ |
| `mrus[]` | Meter reading unit (ABLEINH) | TE422 |
| `readSchedules[].scheduledReadDate` | Scheduled read date (ADATSOLL) | TE418 |
| `sampleReads[]` (`readAt`, `readReason`, `readType`) | MR document (ABLBELNR; ADAT/ATIM, ABLESGR, ISTABLART) | EABL |

## m2c.vee normalized read

| VEE need | Engine read field |
|---|---|
| device / register | `meterId`, `registerId`, `meters[].serialNumber` |
| installation, premise, contract, account | `installationId`, `premiseId`, `contractId`, `accountId` |
| read date, value, previous value, consumption | `readAt`, `registerValue`, `previousRegisterValue`, `consumption` |
| scheduled date, interval | `scheduledReadAt`, `periodStart`, `periodEnd` |
| read type / estimate flags | `readType` (`actual`/`missing`/`estimated`/`adjusted`), `consecutiveEstimates`, `reasonCode` |
| rollover | `registerDigits`, `rolloverFlag` |
| AMI / AMR indicator | `source`, `premises[].meterTechnology`, `meters[].technology` |
| vacancy, move-in/out | `occupied`, `moveInAt`, `moveOutAt` |
| SAP VEE code | `sapValidationCode` (null until real code semantics are supplied; null never means pass) |
| ground truth (scoring only) | `truth` — **strip before sending to VEE** (`/fixtures/vee…` strips it by default) |
