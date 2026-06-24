# ADR-0006 — The posting engine

**Status:** Accepted 2026-06-25

## Context

The architecture's first rule is **documents write ledgers**: a business event is recorded as a
document, and the document posts double-entry legs to the ledgers — ledgers are derived, never
hand-edited, and corrections are reversing entries. For this to hold across every module (inbound,
outbound, payments, offers, Tally, transfers) there must be exactly **one** code path that writes
postings, with the balanced-or-fail and no-reposting invariants enforced in that one place rather
than re-implemented (and re-bugged) per module.

This need is implicit in the old (distrusted) ADR-0004 (the `LedgerModel` base, append-only
triple) but was never stated as its own decision. The review's F1/F2 findings and the Q1/Q2 Q&A
make it explicit, and the new money-critical "no-reposting / corrections rule" item makes
append-only a **code-level invariant**. This ADR ratifies the single posting engine as a
first-class decision. It sits on ADR-0004's conventions (integer paise, append-only tables,
docstatus) and feeds ADR-0005's balanced / append-only / golden CI suites.

## Decision

### One central engine — `post_entries(doc, legs)`
There is exactly **one** function that writes to the ledgers, living in `core`:

```
post_entries(doc, legs)
```

Every module posts through it; **no module writes ledger rows directly.** `doc` is the source
document (carrying its business document number, store / brand / season / state-GSTIN scope
columns, actor, docstatus); `legs` is the list of double-entry postings.

### Balanced-or-fail
`post_entries` rejects any set of legs whose **debits and credits do not sum to zero in integer
paise** (ADR-0004 money type). An unbalanced post is a hard error inside one DB transaction —
either every leg commits or none does (all-or-nothing). There is no path to a half-posted
document. This is the contract CI suite #1 proves (ADR-0005).

### Correct-by-reversal
A document is never edited to fix a mistake. A correction is a **new document that posts reversing
legs** (and, where needed, the right re-posting), today-dated, carrying a reason code and linked to
the source document. A cancellation flips docstatus and posts the reversal (ADR-0004). This is the
only correction mechanism the engine offers.

### NO reposting — a code-level invariant
**Reposting is forbidden in code, not merely by convention.** The append-only `LedgerModel` base
(ADR-0004) refuses `save()` / `delete()` on existing ledger rows; `post_entries` only ever INSERTs;
the DB grants + trigger are the backstop. There is no API, anywhere, to mutate or re-run a prior
posting. Late freight after a PT, a retro-linked direct GRN, a voided sale — each is a new
corrective event through `post_entries`, never a re-post of the original.

### Liability timing lives on the document, not the engine
`post_entries` is mechanism; *which* legs a document emits is the document's own logic, driven by
the commercial model (Q1/Q2): the **GRN** emits the quantity movement (no cost); the **PT** at
Patna inward emits the valuation movement + vendor liability for Outright / Correction; the
**Sale** (D3) emits the SOR sold-liability; Consignment emits no liability from the PT, ever. The
engine stays model-agnostic — it balances and appends; the document decides the legs. This keeps
the SOR/Consignment two-recognition-path rules (Q4) and the two clocks (statutory-at-arrival vs
operational-on-sale) in the documents, posted through one engine.

## Consequences

- The balanced-or-fail and no-reposting invariants are written and tested **once** in `core`, and
  every module inherits them — a posting bug cannot be local to one module's hand-rolled writer.
- Every ledger row traces to exactly one document and one `post_entries` call, so the audit trail,
  the Tally tie-out (slice 7) and the analytics derivations all rest on one provable contract.
- New commercial models or events extend the *document* logic (which legs to emit), never the
  engine — Rule 12 ("variation is data, not code") and the small frozen kernel hold.
- Because there is no reposting path, all of inbound's open money items (late freight,
  sold-before-PT) must be designed as corrective *events*, which constrains them correctly before
  the inbound slice.

## Alternatives rejected

- **Per-module posting code** — each module writing its own ledger rows; rejected because the
  balanced / append-only / scope-column invariants would be re-implemented (and re-broken) per
  module, and a single audit/tie-out contract would be impossible.
- **Editable ledgers with reposting** — rejected absolutely (ADR-0004): breaks the audit trail,
  the statutory immutability and the Tally tie-out.
- **An accounting-rules engine that the engine itself interprets per model** — rejected; it would
  pull model-specific liability logic into the kernel. Legs are decided by the document; the engine
  only balances and appends.

## Sources

- Architecture Rule 1 (documents write ledgers) + Rule "corrections are reversing entries".
- ADR-0004 (integer paise, append-only tables, `LedgerModel` base, docstatus).
- Decision log (25 Jun): Q1 GRN-qty / PT-value split, Q2 liability timing by model + Sale writes
  SOR liability, no-reposting / corrections rule as a code-level invariant.
