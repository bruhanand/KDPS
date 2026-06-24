# ADR-0007 — Entity, GSTIN & cross-state scoping

**Status:** Accepted 2026-06-25

## Context

This is the single highest-blast-radius foundation decision. KDPS operates across Bihar and
Jharkhand under two state GSTINs. Getting the tax-identity hierarchy wrong means re-keying the tax
identity on every document. Three things key off the same hierarchy: GST treatment of moves
between stores (intra-state vs cross-state), RBAC data-scoping (which entities / stores a user may
see, ADR-0003), and the Tally company mapping (D6).

The old (distrusted) ADR-0007's relational `LegalEntity → GSTIN → Store` model is genuinely good
and is salvaged here. The decision is ratified under the Q&A: **Q3 — cross-state transfer = taxable
IGST supply**, contingent on the client confirming KDPS is **one company with two state GSTINs**
(distinct persons under GST). That registration reality is being **forwarded to the client and the
CA** (the Q3 questionnaire), and the relational shape is chosen precisely so the answer is a row
count, not a schema migration — the schema does not bet on the guess. This ADR also fixes the F3
statutory bug where D3 booked a cross-state transfer as "internal — none".

## Decision

Model the hierarchy **relationally**, so the one-company-vs-two answer is a data row, not a
migration:

```
LegalEntity (1..n)            # one or two; the CA's answer is just the row count
   └─ GSTIN (1..n per entity, one per state it registers in)
        └─ Store / Warehouse  # each maps to exactly one GSTIN
```

- **One company, two GSTINs** → one `LegalEntity`, two `GSTIN` rows (the expected case, pending
  client/CA confirmation).
- **Two companies** → two `LegalEntity` rows, one (or more) `GSTIN` each.
- Every document / posting **snapshots its store → GSTIN → entity at creation** (state + GSTIN are
  the first-class stored columns from ADR-0004), so the tax identity is a stable historical fact.

### Two GSTINs = distinct persons; cross-state = IGST
Bihar and Jharkhand registrations are **distinct persons** under GST (Sec 25(4)/(5)). Treatment is
driven off the **state code (first two digits) of the sender's and receiver's GSTINs**:
- **Cross-GSTIN (Bihar ↔ Jharkhand) store transfer = a taxable IGST supply** — an out-voucher +
  IGST tax invoice at the sender, a matching purchase voucher (+ ITC) at the receiver, valued at
  cost as deemed open-market value (Rule 28 second proviso, full-ITC condition), with an **e-way
  bill** on consignment value incl. IGST (₹50,000 threshold cross-state). This **fixes the D3
  "internal — none" statutory bug (F3)** and closes the D6:161-vs-D6:261 internal split in favour
  of the locked IGST treatment.
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
  seed loads whichever count is provisionally true and is revised by editing rows when the
  client/CA answer the Q3 questionnaire — switching is data, not schema.
- Scoping, GST voucher routing and Tally company selection all read one hierarchy.
- The cross-state IGST treatment is scheduled for the relevant outbound / transfer build slice;
  the CA forwards (slab basis on the transfer invoice; Jharkhand e-way carve-out) attach to it.
- Until the client confirms one-company-two-GSTINs, the IGST treatment is the working decision but
  is flagged contingent — the relational shape absorbs either answer without rework.

## Sources

- KDPS domain fact: two GSTINs, distinct persons, cross-state = taxable IGST supply.
- GST: Sec 7(1)(c) + Schedule I, Sec 25(4)/(5) distinct persons, Rule 28 second proviso (deemed
  OMV at cost), e-way bill thresholds (₹50,000 cross-state).
- Decision log (25 Jun): Q3 cross-state IGST (contingent on client registration reality, forwarded
  to client + CA); salvaged `LegalEntity → GSTIN → Store` relational model.
