# ADR-0004 — Database conventions

**Status:** Accepted 2026-06-25

## Context

This is the heart of correctness for a money-critical, GST-bound, append-only ledger system. The
conventions every module obeys must be fixed before any table exists. The old (distrusted)
ADR-0004 reasoning — researched against current Postgres practice for money types, append-only
enforcement and key strategy — is genuinely good and is salvaged in full here. What is added is
the ratified two-step inbound posting (Q1) and the no-reposting / corrections rule made a
code-level invariant (the new money-critical open items in the decision log). This ADR ratifies
the conventions; ADR-0006 ratifies the posting *engine* that depends on them.

## Decision

### Money — integer paise (`bigint`)
- All stored monetary amounts and ledger postings are **integer paise** (`bigint`). This makes
  *balance = sum of postings* an exact integer sum with zero float / rounding drift — the
  double-entry sum-to-zero checksum (Σdebits = Σcredits) is exact (ADR-0005, ADR-0006).
- **Rates, margins, GST % are `NUMERIC`** (ratios, not money).
- **GST and discount-split-back-to-lines compute in higher-precision `Decimal`, then round to
  paise at defined points**, with an explicit India-standard rounding rule (half-up) and a
  **rounding line** capturing any residual. The most common money-bug class is designed out, with
  a named place for every stray paisa.
- Single currency (INR); no currency column until multi-currency is ever needed.
- A reusable money type / value object lives in `core`; no module reinvents paise handling.

### Append-only ledgers — enforced at the database AND in code
Defence-in-depth (Postgres has no native immutable-ledger feature):
1. The app only INSERTs into ledger tables; corrections are **reversing postings**, never edits.
2. `REVOKE UPDATE, DELETE` on ledger tables from the app DB role.
3. A **trigger** that raises on any UPDATE / DELETE of a ledger row.
4. A `LedgerModel` base in `core` that forbids `save()` / `delete()` on existing rows (Django's
   ORM would UPDATE otherwise) — the DB grants + trigger are the backstop, the base model is the
   first line. **Append-only is a code-level invariant, not only a DB grant** (the decision-log
   "no-reposting" item).

### Corrections rule (the no-reposting invariant)
**Reposting is forbidden.** Every correction is a **new, today-dated event carrying a reason
code**, linked back to the source document (e.g. via `voucher_detail_no` / the source document
ref). Nothing is silently rewritten — not stock, not value, not liability, not a Tally voucher.
Late freight after a PT, a retro-linked direct GRN, a voided sale: each posts a fresh corrective
event, never a mutation of the original. (Late-freight forward-only-adjust vs separate
cost-correction event, and sold-before-PT memo handling, are open items to close before the
inbound slice — but the invariant that they will be *new events* is fixed here.)

### Two-step inbound posting (Q1 / Q2)
At inbound the two postings are separated:
- **GRN posts the QUANTITY movement** — qty, location, condition, season, owned-flag provisional;
  **no unit cost**. The GRN writes the stock ledger (quantity only), so goods are sellable day one
  (the booking-less direct-receipt path, Q9, depends on this).
- **PT at Patna inward posts the VALUATION movement** — unit cost stamped (frozen, Q5/Q36),
  owned-flag finalised — **plus vendor liability per commercial model**: Outright / Correction
  post incl-GST liability at inward; **SOR accrues on the Sale** (D3 writes it), **Consignment
  never posts liability from the PT**. The PT creates priced stock truth for all models and
  carries the settlement basis; liability *timing* depends on the model.

### Effective-dated masters — SCD-2
Masters that change over time (brand commercial model / margin / return window, GST slabs,
store→GSTIN, barcode→season cohort) are **SCD-2 effective-dated**: a change is a new row with a
validity window, never an in-place overwrite. Documents snapshot the master values they used at
creation (Rule 3), and the POS adapter re-attaches season at the edge via the effective-dated
master for that barcode at that store on that sale date (Q6).

### docstatus lifecycle
Every document carries a **docstatus** lifecycle (draft → submitted → cancelled, ERPNext-style
contract re-implemented as plain Django, ADR-0001) so a document's posting state is explicit and a
cancellation is a defined, reversing-entry transition — never a delete.

### Keys & identity — three distinct things
- **Primary key = `bigint` identity** (single-node Cloud SQL; smallest, fastest).
- **Business document number** = a separate human-readable deterministic string
  (e.g. `DEO-SAL-20260620-001`) — the Tally join key and external identity, never the PK.
- **Idempotency key** = a UUID an offline-captured write carries (unique), used to dedupe on sync
  so a retry never double-posts (Q8 own-POS: client-UUID per sale → server returns the same
  Sale-ID on retry). The server assigns the bigint PK on commit.

### Scoping dimensions as first-class columns
Every document and posting carries **store, brand, season and state-GSTIN** as real stored
columns (snapshotted from the master, ADR-0003) — scoping filters on them, cross-state = IGST
routing keys off them (ADR-0007), and analytics groups by them.

### Single writer + surrounding conventions
- Only the server (app DB role) writes postings; the PWA never writes money. A separate migration
  role holds DDL rights; the app role is DML-only and cannot UPDATE / DELETE ledgers.
- Actor + timestamps + acting role on every row (`created_by`, `created_at`, the acting role;
  UTC stored, IST displayed) — Rule 10; audit is a byproduct. The maker-checker flows and the
  audit trail both ride on these columns.
- An explicit **business-day boundary** is defined now (the daily Tally voucher, EOSS windows and
  60–120-day return deadlines all hinge on it — cheap now, nasty to retrofit).
- Masters soft-delete (active flag, never hard-delete); ledgers are insert-only.
- Django migrations, reviewed; the append-only grants / triggers are themselves migrations.

## Consequences

- Every money calculation has an explicit rounding step and a place for the residual.
- Ledger immutability survives application bugs and ad-hoc queries; corrections are auditable
  reversing events, never silent rewrites.
- Offline resilience rides on idempotency keys, not on client-generated primary keys.
- The two-step inbound posting makes both anchor docs' ledger-writer tables literally correct
  (GRN writes qty, PT writes value) and unblocks direct-to-store receipt and own-POS
  auto-inward-on-scan.

## Alternatives rejected

- **`NUMERIC(14,2)` for stored money** — the common "accounting ideal", but loses the
  exact-integer-sum ledger property; integer paise chosen for that property.
- **UUID primary keys** — unneeded for a single-node app; bigint is smaller and faster. UUIDs are
  idempotency keys only, never PKs.
- **Editable ledgers / reposting** — rejected absolutely; it would break the audit trail, the
  Tally tie-out and statutory immutability. Corrections are new events.

## Sources

- Crunchy Data — Working with Money in Postgres (integer minor units vs numeric).
- Postgres.fm — Append-only tables (enforce via perms + triggers); MS Learn ledger tables.
- pganalyze / Andy Atkinson — UUID vs serial primary keys; avoid UUIDv4 PKs.
- Decision log (25 Jun): Q1 two-step posting, Q5 frozen P-RATE cost, no-reposting / corrections
  invariant, late-freight and sold-before-PT open items.
