# pos-store-front - Phase 1 grill decisions

Phase 1 artifact of the dev process (`/grill-with-docs`, run 30 July 2026).
Fourteen decisions, each put to Anand with a recommendation and confirmed one by one.
Four Opus research agents validated the contested ones (B2B/GST at the counter, goods-on-approval, offer tie-breaking, offline-first POS architecture); key sources are cited inline.
This is a money slice: the build is supervised and golden-file tested per `docs/agents/dev-process.md`.

## The offline spine

### 1. Till-owned bill counter, server-verified, paper as the recovery floor

The till (the store's browser on the counter machine) holds the authoritative gap-free counter for its store's sale series in durable local storage.
One POS per store is a hard invariant, so there is exactly one writer per series.
The server verifies continuity at sync: it accepts each number exactly once, and a hole raises a flag in the daily reconciliation rather than blocking sync.
A dead or replaced till is handled by a deliberate **register handover**: the new till resumes from the last synced number, and any unsynced bills from the dead machine are re-entered from their printed copies under their original numbers (the same muscle as the paper-bill re-entry flow F3).
The local queue and counter live in persistent browser storage; the sync light turns red if the till detects it lost state.

### 2. Save & Print is the commit point

The moment the cashier hits Save & Print the bill is final locally: number assigned, stock decremented in the local dataset, receipt printed.
Sync is immediate when online, queued when not, with minute-level retries while anything is pending.
The server accepts bills in any order (each carries its idempotency key and its own number); a hole that survives past end-of-day is flagged to a human.
Every bill is stamped `origin: offline` or `origin: online` at commit time - evidence for the daily check, nothing more.

### 3. Reference data auto-syncs; the offers notification informs, never gates

The till pulls the offer rulebook and all live reference data (items, prices, GST slabs, salesman list, customers) automatically whenever online, at a regular interval and immediately when the "new offers live" notification arrives. The earlier credit-note dataset clause is superseded by POS counter redesign grill Q3/Q3b (2 Aug 2026): the counter neither issues nor redeems notes.
The notification still shows at the store so staff know what changed, and a "sync now" button exists, but no human step gates correctness.
Every offer carries its start/end dates inside the synced data, so the till starts and stops offers on its own clock: staleness can only mean missing a new offer, never applying a dead one.

### 4. Credit notes: retired at the counter (superseded 2 Aug 2026)

**Superseded by `docs/features/pos-counter-redesign/grill-decisions.md` Q3/Q3b.**
The same-store credit-note ruling no longer governs the counter. No return or short exchange issues a note, no sale redeems one, and the till dataset carries no open-note cache. Historical rows stay append-only history.

### 5. Offline-first from day one; Chrome-standard till; early printer spike

Research verdict (unanimous across the offline-first literature and the Odoo/Shopify/Square case studies): the local database as source of truth, client idempotency keys, local numbering, and the replay queue are data-layer foundations, and retrofitting them onto an online-first sale flow is the well-documented expensive failure that reproduces the double-billing bug this project exists to kill.
The Sell slice is therefore built offline-first from its first commit; "online" is the queue draining fast.
The till device is standardised on Chrome with the PWA installed and persistent storage requested, because Safari/iOS silently evicts all local data after 7 days without interaction - an unacceptable risk to an unsynced bill queue.
Receipt printing (browser to thermal printer: WebUSB/Web Serial vs a QZ Tray local agent) gets an early hardware spike; it is a lead-time item like the barcode spike was.
Server-side idempotency follows the Shopify pattern: unique constraint on the key, lock-and-conflict on concurrent duplicates, cached original response on repeat.
Sources: [Shopify engineering on idempotency](https://shopify.engineering/building-resilient-graphql-apis-using-idempotency), [MDN storage eviction](https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria), [WebKit 7-day policy](https://webkit.org/blog/14403/updates-to-storage-policy/), [Odoo duplicate pos_reference bug](https://github.com/odoo/odoo/issues/71455), [QZ Tray](https://qz.io/).

## The money edges

### 6. Sold-before-inward: bill now, post when priced

A scan that finds nothing (a piece not yet inwarded) never blocks the sale: the cashier bills it as a manual line with the MRP from the physical tag, stamped **sold-before-inward**.
The money and stock postings for that line wait in the exception queue until the paperwork catches up (GRN/PT prices the piece), then post properly.
Rule 5 holds (no zero-cost posting, ever) and A10 holds (no blocked sale, ever).
The flag lands on the Dashboard's action queue, and an aged sold-before-inward line is a red item in the daily reconciliation.
The commoner case - inwarded stock whose local count shows zero - just bills normally and lets the count go negative locally, flagged for the next stock count.
The GST-recognition side of sold-before-PT stays CA-gated as recorded in `CONTEXT.md`.

### 7. Returns: exchange only, equal-or-up (D-4 superseded 2 Aug 2026)

**Superseded by `docs/features/pos-counter-redesign/grill-decisions.md` Q3/Q3b.**
There is no standalone/plain return and no refund of any kind. A customer can return a piece only inside an exchange linked to the original bill, with reason and condition recorded per return line; the outgoing pieces must be worth at least what the customer paid for the incoming pieces. Save &amp; Print hard-refuses a short exchange. The return window remains data, and a late exchange keeps its recorded manager-override path.

### 8. B2B corner: GSTIN + name at the till, IRN is HO's 30-day duty (closes D-5)

At the till: capture buyer GSTIN + name, nothing more; that flips the bill from B2C to a full tax invoice on the same engine.
The till derives the tax split itself from the GSTIN's first two digits: buyer's state = store's state gives CGST/SGST, different state gives IGST (this is what the old screen's IGST tick did by hand, and it cannot wait for HO because it prints on the customer's copy).
At KDPS's scale (aggregate turnover above the Rs 5 crore e-invoice threshold), every GSTIN-bearing counter sale is legally a B2B invoice that must receive an IRN within 30 days or it is invalid and the customer loses input credit.
So B2B bills are flagged into an HO work queue with a visible 30-day IRN clock (deadline as data, Rule 11); the store's printed bill notes "IRN to follow".
Dropped from the till: the Party A/C ledger picker, the Cess tab, and dynamic-QR machinery (that mandate starts at Rs 500 crore turnover; KDPS is exempt).
Sources: [ClearTax e-invoicing](https://cleartax.in/s/e-invoicing-gst), [IndiaFilings 30-day rule](https://www.indiafilings.com/learn/gst-einvoice-30-day-rule-10crore-turnover), [TaxGuru dynamic QR](https://taxguru.in/goods-and-service-tax/dynamic-qr-code-b2c-invoices-gst.html).

### 9. Offer tie-break: three layers, best-deal-wins per item (closes D-7 / D5's O3)

Layer 1, the brand offer: each item gets at most one, chosen by computing the rupee outcome of every qualifying offer and keeping the largest.
B2G1 grouping is the standard deterministic mechanic: qualifying pieces sorted dearest-first, first X at full price, the cheapest piece free.
Layer 2, storewide offers, and Layer 3, bank/tender offers, apply after Layer 1 only when explicitly flagged combinable; layers never compete, so there is no combinatorial search and pricing is instant on till hardware.
Residual ties break by offer priority number then offer ID: the same cart always prices the same, to the paisa.
Every new offer defaults to non-combining; stacking is a conscious HO choice per offer.
The bill line records which offer won, what it beat, and by how much, feeding the applied-vs-rulebook daily check (B3).
This is the architecture Dynamics 365, Oracle Xstore, Shopify, and Salesforce all converge on.
Sources: [Dynamics 365 multi-discount engine](https://learn.microsoft.com/en-us/dynamics365/commerce/dev-itpro/apply-multiple-retail-discounts), [Oracle Xstore promotion engine](https://docs.oracle.com/en/industries/retail/retail-reference-architecture/latest/rracr/c_xstore_pos_promotion_engine.htm), [Salesforce promotion priority](https://sfcclearning.com/infocenter/content/b2c_commerce/topics/promotions/b2c_promotion_priority_rules.php).

## Access and structure

### 10. The sidebar folds in presentation only

The store persona sees ten flat sections; the 13 section codes underneath (the API gate keys of the #94 one-gate contract) do not change.
Inventory is one page whose tabs (Stock on Hand, Damage & Quarantine, Count & Adjust, Return to Brand) stay gated by their original section codes, so a role without count rights simply sees no Count tab.
Zero backend churn, zero migration, contract tests untouched.
The same trick covers Sell's three tabs and Transfer's four.

### 11. The role matrix becomes admin-editable data; the floors stay code

A Setup - Access screen (it_admin/superadmin only) edits any role's capability per section at runtime (Rule 12: roles are data an admin maintains without a release).
The four money floor rules from the actor-model decision stay hard-coded invariants the editor cannot cross; the screen greys those cells and says why.
Every change is audit-logged (who, when, role, section, old to new).
The contract tests evolve from "gates match the seed" to "gates match the stored matrix"; the seed becomes starting content only.

**Amended 30 Jul 2026 (Anand's ruling, while building #173).** This decision originally said a change "takes effect on next login/token refresh" so nobody's rights moved mid-shift. That is reversed: **an approved change is live immediately, everywhere.** The mid-shift surprise it was guarding against is rare and needed two people to agree to it; a right that cannot be withdrawn until the person next logs out stays open for a whole shift, and a store till may not log out for days. Anand: "everything should be live and get updated instantly."
Two further corrections from the build: the edit is a **proposal a second Owner or IT Admin approves**, not a save, because floor rule 4 ("never by one person alone") governs `section_access` exactly as it governs any other part of a role; and only three of the four floor rules are cells the grid can grey out - rule 1 (nobody approves their own document) and rule 4's second half live in the approvals engine, and the screen states all four so the missing two do not read as forgotten.

### 12. Store targets

A small HO master, one monthly target per store, set by the Operations Head; the capability to edit it is itself a matrix cell.
Month-to-date vs target shows on the store Dashboard from day one; per-staff targets stay parked with HRMS.

## Scope calls

### 13. Hold Bill: park mid-bill, keep-or-expire at day close, visible on the Dashboard

A billing that must pause parks with one tap and the next customer proceeds; retrieval is a one-tap list.
Held bills are till-local, hold no stock or money, and appear on the Dashboard ("2 bills on hold").
At day close they are flagged and the store chooses: keep (the bill carries to the next day and reprices at that day's offers on retrieval) or let it expire.
Nothing expires silently.
A multi-day "keep this aside" is a Booking - a real document with a name on it - not a held bill.

### 14. F10 "Approval / Order": v1 ships without it, the stores are asked now (closes D-6)

Research says the F10 function is almost certainly Indian goods-on-approval practice: items leave on trust with no bill, legally a delivery-challan-out / invoice-on-acceptance shape with a hard 6-month deemed-supply clock (CGST s.31(7)).
There is no public RetailJI documentation and no evidence yet that KDPS stores use it, so v1 ships without it and one concrete question goes to the stores now: "do customers ever take goods home before billing, and what do you press when they do?"
If confirmed, the design is ready: a non-financial Approval document that moves stock out of sellable, posts no revenue/GST/liability, exits by Convert-to-Sale (at that day's price and offers) or Return-to-shelf, and carries the 6-month clock as a tracked deadline (Rule 11) flagged on the Dashboard.
Structurally it is a customer-facing sibling of SOR, which the system already models.
Sources: [CaptainBiz sale on approval under GST](https://www.captainbiz.com/blogs/sale-on-approval-basis-under-gst/), [CBIC s.31 text](https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter7/section31_v1.00.html).

## What this grill did NOT reopen

- The locked D10 Sell-screen design (skeleton kept, sync light, type-to-search, salesman default-to-last, offer chips, trimmed payment panel).
- The locked liability-timing, P-RATE, paise, append-only, and numbering rules in `CONTEXT.md`.
- The five CA-gated money questions; the mechanisms are designed, live money waits.
