# ADR-0007 — Entity, GSTIN & cross-state scoping

**Status:** Accepted 2026-06-25 · **Amended 26 Jun 2026** (entity count confirmed; cross-state paperwork = manual)

## Context

This is the single highest-blast-radius foundation decision. KDPS operates across Bihar and
Jharkhand under two state GSTINs. Getting the tax-identity hierarchy wrong means re-keying the tax
identity on every document. Three things key off the same hierarchy: GST treatment of moves
between stores (intra-state vs cross-state), RBAC data-scoping (which entities / stores a user may
see, ADR-0003), and the Tally company mapping (D6).

The old (distrusted) ADR-0007's relational `LegalEntity → GSTIN → Store` model is genuinely good
and is salvaged here. The decision is ratified under the Q&A: **Q3 — cross-state transfer = taxable
IGST supply**. The registration reality is now **confirmed (26 Jun 2026): KDPS is one legal entity
(one PAN) holding two state GSTINs — Bihar (state code 10) and Jharkhand (20) — and one Tally
company** (distinct persons under GST). The relational shape is kept as designed (the entity count
is a data row, not a schema choice) and now carries the confirmed value: one `LegalEntity` row, two
`GSTIN` rows. This ADR also fixes the F3 statutory bug where D3 booked a cross-state transfer as
"internal — none".

## Decision

Model the hierarchy **relationally**, so the entity count is a data row, not a migration. The
confirmed value (26 Jun 2026) is **one entity, two GSTINs**:

```
LegalEntity (1..n)            # CONFIRMED = 1 (one PAN); the relational shape still absorbs n
   └─ GSTIN (1..n per entity, one per state it registers in)   # CONFIRMED = 2 (Bihar 10, Jharkhand 20)
        └─ Store / Warehouse  # each maps to exactly one GSTIN
```

- **One company (one PAN), two GSTINs** → one `LegalEntity`, two `GSTIN` rows — **the confirmed,
  seeded case (26 Jun 2026)**; one Tally company falls out of the single `LegalEntity`.
- **Two companies** (not KDPS's case) → two `LegalEntity` rows, one (or more) `GSTIN` each — the
  shape still supports it without a migration.
- Every document / posting **snapshots its store → GSTIN → entity at creation** (state + GSTIN are
  the first-class stored columns from ADR-0004), so the tax identity is a stable historical fact.

### Two GSTINs = distinct persons; cross-state = IGST
Bihar and Jharkhand registrations are **distinct persons** under GST (Sec 25(4)/(5)). Treatment is
driven off the **state code (first two digits) of the sender's and receiver's GSTINs**:
- **Cross-GSTIN (Bihar ↔ Jharkhand) store transfer = a taxable IGST supply** between distinct
  persons (kept for awareness and reporting), valued at cost as deemed open-market value (Rule 28
  second proviso, full-ITC condition). **Scope decision (26 Jun 2026): the move is recorded and
  flagged, the paperwork is manual.** The system records the stock move (business-unit →
  business-unit) and **flags it as a cross-state move needing manual paperwork**; it does **not**
  auto-generate the **IGST tax invoice or the e-way bill** — KDPS produces those **manually, outside
  the system** (e-way bill on consignment value incl. IGST, ₹50,000 threshold cross-state). The flag
  + `state_gstin` ledger dimension still **fix the D3 "internal — none" statutory bug (F3)** and
  close the D6:161-vs-D6:261 internal split in favour of the IGST treatment, without the system
  taking on invoice/e-way generation.
- **Intra-state move (same GSTIN) = stock-ledger-only** — no tax invoice, no IGST; a quantity
  movement between locations under one registration.

### Data-scoping keys off this same hierarchy
RBAC data-scoping (ADR-0003) is expressed against this tree: a user's scope is
`all / entity / region / store-group / store`, resolved through `LegalEntity → GSTIN → Store`. The
scope authority and the GST routing read **one** hierarchy — no duplicated truth (Rule 4). A
mandatory test proves cross-store / cross-entity isolation (ADR-0005).

### Tally company mapping falls out of the entity count
The Tally company mapping (D6) **falls straight out of the `LegalEntity` count** — one Tally
company per legal entity — so "one Tally company or two" is a data lookup, not a separate design
decision later.

## Consequences

- Foundation builds `LegalEntity`, `GSTIN`, `Store/Warehouse` in `masters` with this shape; the
  seed loads the **confirmed (26 Jun 2026)** one-entity / two-GSTIN value (Bihar 10, Jharkhand 20).
  The relational shape still makes any future change data, not schema.
- Scoping, GST voucher routing and Tally company selection all read one hierarchy.
- The cross-state move is recorded and flagged in the relevant outbound / transfer build slice; the
  IGST tax invoice and e-way bill are produced **manually by KDPS, outside the system**. The CA
  forwards (slab basis on the transfer invoice; Jharkhand e-way carve-out) attach to that manual
  paperwork.

## Sources

- KDPS domain fact: two GSTINs, distinct persons, cross-state = taxable IGST supply.
- GST: Sec 7(1)(c) + Schedule I, Sec 25(4)/(5) distinct persons, Rule 28 second proviso (deemed
  OMV at cost), e-way bill thresholds (₹50,000 cross-state).
- Decision log (25 Jun): Q3 cross-state IGST; salvaged `LegalEntity → GSTIN → Store` relational
  model.
- Decision log (26 Jun): entity count **confirmed** = one PAN / one legal entity, two GSTINs
  (Bihar 10, Jharkhand 20), one Tally company; cross-state move is **recorded + flagged**, the IGST
  invoice and e-way bill are produced **manually by KDPS, outside the system**.
