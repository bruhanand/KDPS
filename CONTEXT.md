# CONTEXT.md — KDPS build context

> The single machine-read briefing every coding agent loads before a slice. If a domain fact, a kernel contract, or a locked decision matters for writing code, it lives here or is linked from here. **One file — don't fork it.** Depth lives in `docs/my-understanding/system-design/`; this is the index of what's load-bearing.
>
> Companion files: `AGENTS.md` = how to operate in this repo (workflow; `CLAUDE.md` is a symlink to it). `README.md` = how to run it. **This file = the domain + kernel + decisions.**

---

## What we're building

KDPS Lifestyle Pvt Ltd — a multi-brand Indian fashion retailer (Bihar + Jharkhand, 50+ stores/warehouses, 20,000+ SKUs, 40+ brands) replacing per-store POS + Tally + Excel. We build its operating system: a **deterministic ERP** where documents write append-only ledgers, and GST + Tally stay statutory.

**Two systems, never conflated:**
- **The builder** — AI coding agents + skills + this context engine + human review gates. An AI system that writes the code; we mostly review. Tool-neutral by design: whichever agent picks up a `ready` issue, the loop and the gates are the same.
- **KDPS ERP** — the deterministic product. **AI lives only at its edges** (analytics, messy-data ingest); it never writes stock, money, or Tally.

**Stack (ADR-0001):** React/TypeScript PWA + Python/Django + PostgreSQL. Not Frappe — re-implement ERPNext's *contracts* as plain Django. No backend-as-a-service.

---

## The 12 rules (the constitution — every slice obeys these)

1. **Every business event is a document with a lifecycle.** No document → it didn't happen.
2. **Documents write ledgers; ledgers are never hand-edited.** Fix with a correction document, never an edit.
3. **Master data lives in one place; documents copy (snapshot) it.** A later master edit never rewrites yesterday's document.
4. **Every fact has exactly one owner.** Stock→stock ledger; sale→POS; accounting/GST→Tally; offers→offer rulebook.
5. **Flag, never block.** A mismatch raises a problem item for its owner; the counter keeps working unless truly dangerous. *For money, "truly dangerous" is defined:* a stock movement the books cannot price **or cannot count** is **refused**, never posted at zero - a flag is a visible approximation, a zero-value or zero-quantity posting is an invisible wrong answer. (The quantity half was ruled in on 27 Jul 2026, issue #122: the same decision extended to the same document.)
6. **Calculated numbers are not typed by hand.** Profit, age, MRP come from formulas.
7. **Outside systems need written rules + daily checks.** POS, Tally, banks, WhatsApp: documented contract + matching key + daily reconcile.
8. **AI only reads and suggests.** Never writes stock, vendor balance, cash, or Tally.
9. **Every line says exactly what item it is.** Stock: brand/style/colour/size/season/barcode. Money: commercial model. (Booking may stay at style+size; full identity starts at GRN/PT.)
10. **Every action has an actor.** Who created/edited/approved + when; approvals happen in-system; roles gate each step.
11. **Deadlines are data, not memory.** Return windows, offer/season/payment dates are stored and alarmed.
12. **Business differences are data, not code.** Brand models, GST slabs, offers, roles, seasons = master rows a trained admin adds without a release. *Code holds the small posting engine; variation lives above it as data.*

---

## The kernel — engine + spine (the frozen core everything rides on)

**Build status is not recorded here - the code is the truth.** The kernel below is built and on `main`; what else exists, and how any flow behaves today, is answered by reading `app/backend` / `app/frontend` and git history, never by this file or the design corpus. The contracts in this section bind regardless of build state: code that violates one is a bug even when it is on `main`.

**Engine primitives** (in `core`; ADR-0004/0006):
- **Money = integer paise** (`*_paise bigint`); rates/margins/GST% = `NUMERIC`; GST in `Decimal`, rounded half-up with a rounding line. Unit cost = the vendor's purchase rate directly — **never ÷ (1+slab)**.
- **`post_entries(doc, legs)`** — the *single* writer of every ledger. Balanced-or-fail (Σlegs = 0 in paise) in one all-or-nothing transaction.
- **Append-only ledgers** — balance = sum of legs; INSERT-only (DB `REVOKE UPDATE/DELETE` + trigger + `LedgerModel` base); never hand-edited.
- **Correct-by-reversal / no-reposting** — a fix is a new, today-dated reversing event with a reason code, linked to source. A period-lock rejects postings into a closed period. **There is no "edit the old row" path anywhere.**
- **docstatus FSM** — `draft → submitted → cancelled`; cancel is a reversing transition, never a delete.
- **Naming series / three keys** — surrogate `bigint` PK · business doc-number (`{FY}/{store}/{type}/{seq}`, e.g. `26-27/DEO/SAL/74`, the Tally join key) · idempotency UUID for offline writes. The counter is scoped per `(fy, store, doc_type)`, so `doc_type` **must** be in the rendered key to stay globally unique (the build manual's `DEO-SAL-001` shorthand is the same key, dash-rendered — this slash form is canonical).
- **Scoping fail-closed + dimensions** — `store · brand · season · state_gstin` are declared FK columns on **every** ledger leg, snapshotted at post time; an unscoped query errors (never returns all rows). `django-scopes` at the app layer; schema kept RLS-ready (ADR-0003).
- **SCD-2 masters** — effective-dated where money depends on history (gstin, gst_slab, cost, price, brand_terms, amm). Documents snapshot masters at creation.
- **Audit + data-quality** — actor/timestamps every row (UTC stored, IST shown); `audit_log` (who/why/when, AI-suggestion vs human-decision); a `staging` ingest tier normalises messy source files via `source_layout_profile` + alias tables, flagging never blocking.

**Spine tables** (arrive with the business slices, not K0):
- **sku** — the product; key `(brand, style_code, color, size)` + color_tier (P/M/E), taxonomy, hsn.
- **cohort** — what we count & price; key `(barcode, season)`; frozen `unit_cost_paise` (= P RATE), `mrp_paise`, `owned_flag`.
- **pt / pt_line** — the canonical ~20-column PT row; identity + cost + GST + season crystallise here. The data spine.
- **stock_ledger** — signed `qty_delta` per cohort; `movement_reason` enum; unit_cost NULL on GRN leg, stamped at PT.
- **vendor_ledger** — Dr/Cr per `(vendor, brand)`; what we owe each brand.
- **cash_ledger** — grain store × day × tender `{cash·upi·card·dues}`; paired with `bank_reconciliation`.

---

## Money-critical locked decisions (do not deviate without changing an ADR)

- **Two-step inbound:** **GRN posts quantity only** (no cost); **PT posts valuation (frozen unit cost) + vendor liability per commercial model** at Patna inward.
- **Liability timing by model:** Outright / Correction → liability at inward (PT). **SOR → accrues on the Sale.** **Consignment → never posts liability from the PT, ever.**
- **Unit cost = P RATE directly**, frozen at PT. Never derive ex-GST cost by dividing by (1+slab). `CHECK unit_cost ≤ mrp`.
- **Two GSTINs** — Bihar (state code 10) + Jharkhand (20); **one PAN / one legal entity / one Tally company.** Treatment driven off the first two GSTIN digits.
- **Cross-state (Bihar↔Jharkhand) transfer = taxable IGST supply** (recorded + flagged; IGST invoice + e-way bill produced *manually* outside the system). Intra-state move = stock-ledger-only.
- **Money = integer paise**; balance = exact integer sum of postings.
- **Corrections = new dated reversing events with a reason code, never edits** (no-reposting is a code-level invariant); period-lock/freeze-date enforced.
- **Postings are balanced-or-fail**, written only through `post_entries`.
- **Apparel GST slab (GST 2.0, eff. 22 Sep 2025):** 5% ≤ ₹2,500/piece, 18% above; GST-exclusive, on post-discount per-piece price — held as **date-effective data**, re-verify before go-live.
- **Commercial model = two axes (ownership × return-terms)** with derived labels (Outright/Correction/SOR/Consignment); a first-class dimension, not a flag.

---

## ⚠️ CA-gated / open — DO NOT build past these on money slices

These await a chartered-accountant (or Anand/client) ruling. Build the *mechanism* (Rule 12); the actual rate/rule is data:
- **SOR/Consignment GST single-recognition (F9)** — `gst_recognised = (date, voucher_no)` booked exactly once. [CA]
- **GST recognition point per brand** — consignment-as-agent vs true sale-or-return characterisation. [CA]
- **6-month deemed-supply clock** (CGST §31(7)) on true sale-or-return lots. [CA]
- **Late freight after PT** — forward-only rate adjustment vs separate cost-correction event. [Anand]
- **Sold-before-PT** — SRBNB memo value vs block the sale. [CA/Anand]
- **HSN / apparel slab + P RATE statutory cost sign-off** — re-verify rates + confirm no brand embeds GST in P RATE. [CA]

---

## Glossary (ubiquitous language — use these exact words in code & docs)

**Identity & stock**
- **SKU** — Brand + Style + Colour + Size; smallest priced sellable identity.
- **Cohort** — the stock key `(barcode, season)`; what we count & price; carries frozen cost + age.
- **Barcode** — a **non-unique scan-alias** pointing to a cohort, *not* the identity; a scan decrements the cohort count by one.
- **Season** — the selling period (a **name, never a date**); half the cohort key; drives age; calendar Open → EOSS → Closed.
- **Color tier (P/M/E)** — Premium/Medium/Economy colour stand-in when a brand doesn't track exact colour.
- **EOSS** — End-of-Season Sale; markdown phase; the usual trigger for the **V-flip**.
- **V-flip** — an ownership **label change on stock that stays where it is**. Brand-owned (SOR/consignment) pieces that have not sold become KDPS-owned, so the brand can report them as sold and close its target. Nothing moves, no customer buys anything — the piece is still on the shelf, now on our books, and sells on as clearance. It is an **action on Stock, never a module or its own sidebar tab**; it runs for a few months around the season end. (Settled 25 Jul 2026.)

**Documents & ledgers**
- **Document** — numbered record of one event with a docstatus lifecycle; the only thing that writes a ledger.
- **Posting** — an append-only balanced ledger entry; never edited/deleted — fixed by a reversing entry.
- **Ledger** — derived book; balance = Σ postings; three: stock, vendor, cash; append-only.
- **Snapshot** — master values a document copied at creation (masters are SCD-2).
- **PT (Product Transfer)** — the priced stock-in document (brand's format); stamps frozen unit cost + posts vendor liability per model.
- **GRN (Goods Receipt Note)** — what physically arrived; posts **quantity only**; can exist with no booking.
- **Shipment** — the physical consignment; the anchor of inbound (may have `booking_ref = NULL`).
- **Booking** — the order placed with a brand (Purchase-Order analog); optional (booking-less direct receipt allowed).
- **SRBNB** — Stock-Received-But-Not-Billed accrual; gap between goods-here and bill-matched.
- **TIR** — purchase-side export feeding Tally at inward (GST breakup carried, never recomputed).
- **RTV** — Return-to-Vendor; posts vendor credits.
- **Exception queue** — where a flagged mismatch waits for its named owner (flag, never block).

**Commercial models**
- **Outright (BNS)** — KDPS owns, no returns; liability at inward.
- **Correction (25-18-10)** — KDPS owns, capped return allowance; liability at inward.
- **SOR (Stock-on-Return)** — brand owns; uncapped returns; value off-book until sale; **liability posts on the Sale**; 60–120-day windows tracked.
- **Consignment** — SOR + rolling top-up; brand owns; liability **only** on the Sale, never the PT.

**GST & geography**
- **GSTIN** — a state tax identity; KDPS has two (Bihar, Jharkhand) = separate "distinct persons"; every store maps to one.
- **Cross-state transfer** — Bihar↔Jharkhand = taxable IGST; intra-state = stock-ledger-only.
- **P RATE** — the vendor's purchase rate = the canonical unit cost frozen at stock-in (BASIC × 1.20 in raw PTs — a flat markup, *not* a GST rate).
- **Tally** — the statutory book of record; KDPS feeds it one-way via a deterministic voucher number.

**POS & edges**
- **Sale** — the **source-agnostic** sale document (`source ∈ {KDPS POS, manual}`); posting logic lives on the Sale, not on any adapter. Every Sale records **who sold it** — a salesperson per line (defaulting to the last picked; D10, 30 Jul 2026), distinct from the till login (#107).
- **KDPS POS** — our own counter, and the only writer of a Sale. Offline-first, idempotent. **Decided 26 Jul 2026: KDPS builds its own POS; the third-party-POS route is dropped**, so there is no external sales feed to ingest or reconcile against. The source-agnostic Sale shape is kept anyway — it costs nothing and keeps a future importer (or a migration load) from touching posting logic.
- **Offer** — brand-specific slab/condition discount (value slabs, B2G1 lowest-item-free, gifts, per-store, dates); applied on-invoice at the till. Tie-break (locked 30 Jul 2026, closes D5's O3): three layers - one brand offer per item by best-deal-wins (B2G1 groups dearest-first, cheapest free), then storewide, then bank/tender offers, each stacking only when explicitly flagged; new offers default non-combining; same cart always prices the same.
- **Idempotency key** — client-UUID per sale; retries return the same Sale-ID.
- **Hold Bill** - a till-local parked cart (30 Jul 2026): holds no stock or money, shows on the store Dashboard, flagged at day close for the store to keep or expire; a multi-day set-aside is a Booking, not a hold.
- **Register handover** - the deliberate recovery action when a till device dies or is replaced: the new till resumes from the last server-synced bill number; unsynced bills are re-entered from their printed copies under their original numbers (the paper-bill F3 muscle). The till owns its store's gap-free counter; the server verifies continuity at sync.
- **Sold-before-inward** - a billed line the books cannot yet price: the sale proceeds (manual line, MRP from the tag), the stock/money postings wait in the exception queue until GRN/PT prices the piece. No zero-cost posting ever; the GST-recognition side stays CA-gated (sold-before-PT).
- **Customer exchange (counter)** - the only counter return path: pieces coming back stay tied to the original bill and the customer must take pieces of equal or greater paid value. Money never leaves KDPS, a short exchange is refused, and the counter issues no credit note. (Supersedes the earlier plain-return / credit-note glossary entry; POS counter redesign grill Q3/Q3b, 2 Aug 2026.)

---

## The 7 ADRs (ratified — full text in `docs/my-understanding/system-design/adr/`)

- **0001 Stack** — Django + React/TS PWA + Postgres; typed at both ends with a generated TS client; not Frappe; no BaaS.
- **0002 Repo layout** — monorepo `app/{backend,frontend}`; one Django app per module + thin shared `core`; no peer model imports; seams enforced by `import-linter` in CI; scaffold only what the slice needs.
- **0003 Data scoping** — `django-scopes`, fail-closed; store/brand/season/state-GSTIN as FK dimensions on every leg; RLS-ready backstop.
- **0004 DB conventions** — money = paise bigint; append-only enforced in DB + code; corrections = dated reversals; SCD-2; docstatus; three keys.
- **0005 CI gate** — `ci = typecheck && lint && test`, green-to-merge, on **real Postgres**; four money anti-cheat suites (balanced, append-only, isolation, golden-file over ~150 real invoices).
- **0006 Posting engine** — one `post_entries(doc, legs)` in `core`; balanced-or-fail; correct-by-reversal; period-lock; liability timing lives on the *document*, not the engine.
- **0007 Entity/GSTIN scoping** — `LegalEntity → GSTIN → Store`; one PAN, two GSTINs, one Tally company; cross-GSTIN transfer = IGST (invoice + e-way produced manually).

---

## How we build

- **Build order:** kernel K0→K9 first, then vertical slices in spine order — booking → inbound (GRN→PT→stock+vendor) → vendor liability → selling → offers → payments → Tally → SOR → analytics.
- **Two speeds.** **FREE** (scaffold, screens, seed, reports): AI writes, human reviews after — K0, K4, K5, K9. **SUPERVISED** (money/ledger/GST/RBAC): human reads *every line*, golden-file tested — K1, K2, K3, K6, K7, K8 + every business money slice.
- **The gate:** `npm run ci` must be green on real Postgres before merge. SQLite is rejected at settings load.
- **Loop:** one slice → one spec → one issue labelled `ready` → build (any AI agent, branch only) → human review → merge. **The issue is the memory between chats.** No agent has a merge phase — only a human reaches `main`.
- **Corrections never edit.** Every fix is a new dated reversing event.
- **Variation is data (Rule 12).** Build the *mechanism*; the brand's actual rate/rule/slab is a configuration row.
- **One gate for access (25 Jul 2026, issue #94).** Every API permission is a **section + minimum capability** resolved from the role's stored `section_access` — the same data that shapes the sidebar, so the menu and the API can never tell different stories. A hand-kept role list is an **exception**: allowed only where the ladder provably cannot express the rule, and only with the reason written next to it and registered. A contract test fails when a gate and the matrix disagree. The screen's declared section+rung in the nav manifest is the published pair the server mirrors.
- **The access matrix is not ratified design.** It was transcribed from a client spreadsheet in July to unblock the sidebar; the design corpus names actors almost nowhere (V-flip, returns, transfers have none). Treat the matrix as the working authority for *code*, not as a settled design — the actor model is a deferred design discussion, not a lookup.

## Where to look (canonical depth)

- **Constitution + how-we-build:** `docs/my-understanding/system-design/00-system-architecture.html`
- **Design of record:** `…/consolidation/consolidated-system-design.html`
- **Kernel data model:** `…/consolidation/kernel-data-model.html` · **Glossary:** `…/consolidation/glossary.html` · **Posting catalog:** `…/consolidation/posting-catalog.html`
- **ADRs:** `…/adr/0001`–`0007` · **Build manual:** `…/build-operating-manual.html` · **Build log:** `…/build-log/`
