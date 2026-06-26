# ADR-0003 — Data scoping

**Status:** Accepted 2026-06-25

## Context

KDPS runs 50+ stores/warehouses across two states (Bihar & Jharkhand), two GSTINs, 40+ brands and
multiple seasons. Every read and write must be confined to what the actor is entitled to see, and
cross-store / cross-entity isolation is a money-and-statute boundary, not a convenience. The
design-of-record had drifted on the mechanism: the consolidated design (line 561) said
"PostgreSQL row-level security scoping each store/GSTIN", while the distrusted old ADRs rejected
RLS for queryset filtering. Two live, contradictory positions (the F4 / Q12 finding).

The review Q&A settled it. **Q12 — LOCKED: Option A — app-layer scoping (django-scopes), schema
RLS-ready.** The ERPNext engineering study added the pressure that decided it: scoping dimensions
must be carried as declared columns **from the kernel**, because retrofitting them after data
exists is painful and money-corrupting. This ADR ratifies the conscious decision the review asked
for; it does not silently inherit either old position.

## Decision

**Scope is enforced at the application layer, fail-closed, with the schema kept RLS-ready as a
defence-in-depth backstop.**

### Application-layer scoping via `django-scopes`
- Reads and writes are filtered to the actor's scope at the ORM layer using `django-scopes`
  (or an equivalent queryset-scoping mechanism). A Store User's queryset is provably unable to
  read another store's / entity's rows.
- **Fail-closed:** a query that runs without an active scope **errors**, it does not silently
  return all rows. The default is "see nothing" until a scope is set, never "see everything". This
  is the single most important property — an unscoped query is a bug that fails loudly.
- Scope is resolved against the `LegalEntity → GSTIN → Store` hierarchy (ADR-0007): a user's scope
  is `all / entity / region / store-group / store`. This reuses one hierarchy; it does not mint a
  per-store role (which would explode the role set).

### Scoping dimensions are declared FK columns on every ledger leg, from the kernel
Carry **store, brand, season and state-GSTIN as real, declared foreign-key dimension columns on
every ledger leg** from day one (Q12). They are snapshotted from the master at posting time
(not derived at query time), so they are stable historical facts. This is non-negotiable kernel
scope: these columns are what scoping filters on, what GST voucher routing keys off, and what
every analytics cut groups by — retrofitting them once ledgers hold data is the painful path the
study warned against.

### Schema RLS-ready (the backstop)
The schema is kept ready for PostgreSQL Row-Level Security as a later defence-in-depth layer
without a migration: scope columns exist, the app connects as a **non-owner DB role**, and a
**5-minute infra check** confirms `SET LOCAL` survives PgBouncer **transaction-pooling** (so a
per-transaction `SET LOCAL app.current_scope` would bind correctly if RLS is switched on). RLS is
not enabled at the foundation; it is held in reserve so the choice "turn on RLS" is a policy flip,
not a re-architecture.

## Consequences

- Scope filtering is cross-cutting → it lives in `core` and every module's querysets apply it; no
  module re-implements it.
- A mandatory **cross-store / cross-entity isolation test** is foundation coverage (ADR-0005): a
  Store User's queryset must be provably unable to read another store's / entity's rows, run as
  the restricted app DB role.
- Carrying store/brand/season/state-GSTIN on every leg makes the ledger self-describing for
  scoping, GST routing and analytics — the same columns serve all three (Rule 4, no duplicated
  truth).
- App-layer scoping can be bypassed by raw SQL or a coding mistake; the fail-closed default plus
  the RLS-ready schema (which can be switched on if the app-layer guarantee ever proves
  insufficient) are the mitigations.

## Alternatives rejected

- **PostgreSQL RLS as the primary mechanism now** — strong DB-level guarantee, but heavier to
  operate, awkward under serverless connection pooling, and harder to test/debug at a solo
  build's pace. Kept RLS-ready as a backstop rather than the front line.
- **Per-object permissions (django-guardian)** — too heavy at 50 stores × many millions of rows;
  scope is a coarse dimension, not a per-row ACL.
- **Scoping baked into roles** — role explosion at 50 stores; scope is a separate dimension from
  role (carried into ADR-0007's hierarchy), never minted into role names.

## Sources

- `django-scopes` (raphaelm) — fail-closed queryset scoping for multi-tenant Django.
- PostgreSQL RLS docs; PgBouncer transaction-pooling + `SET LOCAL` interaction notes.
- ERPNext engineering study (25 Jun 2026): carry scope dimensions as declared columns from the
  kernel; retrofitting after data exists is painful.
- KDPS domain: two GSTINs / distinct persons; `LegalEntity → GSTIN → Store` (ADR-0007).
