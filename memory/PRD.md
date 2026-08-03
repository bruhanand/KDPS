# KDPS Operating System — PRD / Build Memory

## Problem statement
KDPS Lifestyle Pvt Ltd is a multi-brand apparel retailer operating stores across
**Bihar & Jharkhand** (one PAN / one legal entity / two state GSTINs). We are building a
**deterministic retail ERP** ("KDPS Operating System"): documents write append-only
ledgers, Tally remains the statutory book, AI is suggest-only at the edges. The repo's
`docs/` folder holds the full plan (constitution `CONTEXT.md`, 12 rules, 7 ADRs, a
191-page application map across 14 modules).

## Stack
Django + DRF + PostgreSQL backend (`/app/backend`, served by uvicorn via a shim,
`.venv`→`/opt/kdpsvenv` py3.12), React + TypeScript + Vite frontend (`/app/frontend`).
`bash scripts/dev-bootstrap.sh` rebuilds the whole dev environment (Postgres install +
role/db, `uv sync`, migrate, seeds) whenever the pod is reprovisioned — `/usr` and
Postgres binaries do not survive that, only `/app` does. Both `backend/.env`
(`DATABASE_URL`) and `frontend/.env` (`REACT_APP_BACKEND_URL`) must exist for the app
to boot; if a fresh pod has neither, create them (Postgres user/db `kdps`/`kdps_dev`,
password `kdps`) before running the bootstrap script.

## Document history
This file holds the static problem statement and the current architecture snapshot
only. The full dated history of every review/build pass is in **`CHANGELOG.md`**
(newest first). Open backlog by priority is in **`ROADMAP.md`**.

## Current state — 4 Aug 2026 (Warehouse Ops + Offers/Pricing redesign)
Built and tested in this session, in the priority order the user confirmed:

**P0 — Distribution allocation grid.** New screen `/transfer/distribution`
(sidebar: Transfer → Distribution). Ops Head picks a source warehouse, ticks
destination stores, searches arrived stock by barcode/design, and enters a
qty-per-store grid with a live allocated-vs-available check. "Create transfers"
bulk-creates one **draft `store_split` transfer per destination store** via the
*existing* `POST /outbound/transfers` → approve → dispatch → receive pipeline —
nothing in the posting engine changed; this is purely a batch front-end over it.
Cross-state destinations require an e-way bill number inline before submit.
New `TransferReason.WAREHOUSE_ALLOCATION` tags every draft the grid raises.

**P0 — Partner store flag + configurable billing at Purchase Price.**
- `Store.is_partner` (boolean, default False) — Setup → Stores now has a
  "Partner store" checkbox and a Partner column.
- Every transfer to a partner-store destination now computes
  `StoreTransfer.partner_billing_value_paise` = qty dispatched × the books'
  own unit cost (Purchase Price), set **before** `.post()` (submitted documents
  are immutable — this cost the first attempt a rollback before the fix landed).
  Shown on the transfer detail page as a "Partner billing" card.
- **`BillingPolicy`** (singleton, `outbound/models.py`) is the chain-wide dial the
  user asked to keep configurable rather than hardcoded: `informational` (figure
  shown only, no ledger entry — matches every other transfer's "stock move only,
  no GL" rule) or `gl_posting` (also posts **Dr `PARTNER_RECEIVABLE` / Cr
  `INVENTORY`** at that value, no margin — a partner is billed at cost). Read at
  `money: view`, changed at `money: manage`. Its own page/nav item is
  **Money → Partner Billing** (`/money/partner-billing`) — it was first bolted onto
  `/setup/settings`, which is gated at `sell: manage` and walled Owner out; moved
  to its own Money-section page once the testing agent caught that.
  Verified end-to-end: dispatched a real transfer DEO→BANKA(partner) with
  `gl_posting` on, confirmed via Django shell a balanced
  `Dr PARTNER_RECEIVABLE 280000 / Cr INVENTORY 280000` posted, trial balance
  stayed ₹0. Left the demo policy on `informational` (the safe default) and
  BANKA (`id=5`) flagged as a partner for the testing agent's use.

**P1 — Offers & Pricing sidebar simplified, 5 items → 3.** "Offers & Price" now
shows **Price Book** (`/offers/price-list`, was "Price List"), **Promotions**
(`/offers`, was "Offers"), **Discount Reports** (`/offers/discounts`, was
"Discounts") — same URLs, just renamed and fewer rows, since `PageHeader` derives
each screen's H1 from the nav label. "New Offer" and "EOSS Planning" are no
longer separate sidebar entries but are fully reachable exactly as before: New
Offer via the existing "Write an offer" CTA already on Promotions, EOSS Planning
via a small in-page tab row (new shared `components/PromotionsTabs.tsx`) shown on
both `/offers` and `/offers/eoss`. Routes, gates and backend are all untouched —
this was a manifest + presentation change only, kept deliberately light (no fold/
strip architecture) because those two screens serve the same audience
(`offers_price: view`/`operate`) as the page hosting them.

**P2 — Mock tag printing.** Price Book rows have a "Print tag" button opening a
preview modal (design/color/size/MRP) with a "Print" action that shows "Sent to
printer (mock)" — explicitly **MOCKED**, no printer integration exists.

**Deferred, by the user's own choice** ("we can do it later"): the AI PT-file
chat assistant. Not started.

**Environment note for the next session:** this pod's `backend/.env` and
`frontend/.env` did not exist at session start (fresh reprovision) — recreated
per the Stack section above, then `bash scripts/dev-bootstrap.sh` rebuilt
everything. If backend 500s on boot with `ModuleNotFoundError: No module named
'django'`, that's this exact situation — check `.env` files first before
anything else.

**Testing.** Backend: `pytest outbound masters core/tests tests/test_outbound_*
tests/test_cross_store_*` all green (run in the `/opt/kdpsvenv` venv, budget
~90–150s per batch, the sandbox's own command timeout — not pytest — is what
kills a same-call run past ~120s, so give it a generous explicit `timeout` or
background it with `&`/log file and poll). Frontend: `tsc --noEmit` clean,
`vitest run` — `navConfig.test.ts` (55), `routes.test.ts` (11, one updated for
Distribution no longer being a legacy redirect), `pageVocabulary.test.ts` all
pass. Pre-existing, unrelated to this session: 36 `src/till/*` vitest failures
in this pod (`navigator is not defined` — jsdom environment gap, not code).
`testing_agent_v4` ran two passes (`iteration_29.json` found one blocking
placement bug in the Partner Billing page's permission gate, fixed;
`iteration_30.json` confirmed the fix, 100% pass, no open issues).
