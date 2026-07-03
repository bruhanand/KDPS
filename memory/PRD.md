# KDPS Operating System — PRD / Build Memory

## Problem statement
KDPS Lifestyle Pvt Ltd is a multi-brand apparel retailer operating stores across
**Bihar & Jharkhand** (one PAN / one legal entity / two state GSTINs). We are building a
**deterministic retail ERP** ("KDPS Operating System"): documents write append-only
ledgers, Tally remains the statutory book, AI is suggest-only at the edges. The repo's
`docs/` folder holds the full plan (constitution `CONTEXT.md`, 12 rules, 7 ADRs, a
191-page application map across 14 modules).

## Current state — 2 July 2026 (read this first)
The foundation **and** the first business layer are **built and merged to `main`**, auto-deploying to a **Render alpha** (Postgres 16 + Django API + React PWA). Everything below this section is a **chronological build log**: the earliest (28 Jun) entries describe superseded money mechanics (stock value + auto-bill at **BASIC×qty**); those were **rebuilt to P RATE + commercial-model liability** in the 30-Jun Phase C/E remediation. Treat this section as the source of truth for status.

- **Landed (git):** PR #31 merged the Emergent export to `main`; PR #33 + #34 merged the `harden/green-and-security` sprint (money-path + security + CI green); PR #35 seeded the PT-mapper master data on Render. `main` is the alpha of record; `emergent` (exports) and `dev` (hand changes) PR into it (3-branch model). *(Corrects the "Deployment readiness check (28 Jun)" section below — deployment is live on Render, not blocked on MongoDB / a missing git remote.)*
- **Built on `main`:** kernel `core` + 9 apps (`masters` `accounts` `files` `vendors` `inbound` `ptmapper` `stockledger` `finledger` `aiagents`); React/TS PWA with ~12 wired screens + ~20 "coming soon" stubs.
- **Money path — remediated (Phases A–F of the 30-Jun review, all on `main`):** P RATE valuation (not BASIC), commercial-model liability branching (owned → bill at PT; SOR/consignment → never a payable at PT; direct → GRNI), a balanced value voucher on every PT inward via `post_entries`, GRN + PtFile reparented onto `core.Document`, Books-Health/trial-balance endpoint (`GET /api/finledger/health`). Full backend suite green on real Postgres.
- **Active dev moved Emergent → Claude Code (30 Jun)** — Emergent parked, not cut; repo kept portable.
- **PT-mapper fed + hardened (1 Jul, PR #34):** 9 brand profiles + normalisers + big seed; seeded on Render (PR #35). Fill rates ≈ BRAND 86% / SIZE 87% / SEASON 67% / COLOR 47%. MUFTI COLOR gap resolved.
- **Store analysis (2 Jul, commit 9b50b30):** JSL store deep-dive (business analysis + 16-measure dashboard, HTML+PDF) + a reusable `store-dashboard` skill under `.claude/skills/`.
- **Inbound UX restructure (3 Jul, branch `implement-inbound-plan`, not merged):** "Inbound" → **Stock Receive** (receiving only) and "PT Mapper" → **PT File Operation** (two sub-tabs: PT File Mapper + PT File Making). Brand PTs now link to a received invoice/GRN at upload. See the dated section below.
- **Known alpha caveats:** (1) `finledger` vendor/cash ledgers are still single-entry running balances — only the PT-inward path is true double-entry / in the Σ=0 trial balance; (2) two security items **deferred by decision** — demo creds seeded on the public Render alpha, JWT/refresh in `localStorage`. Five money-critical GST items still await a CA ruling before live money.
- **Not built:** selling/POS, offers, payments/settlement, transfers, returns, Tally sync, analytics, store open/close.

## Implemented — Inbound experience restructure: Stock Receive + PT File Operation (3 Jul 2026) ✅
UX reorganisation (step 1 of a larger UX overhaul — deeper simplification is a later session).
Decisions D1–D4 confirmed with Anand; scope is **UI reconstruction + renaming + wiring the
invoice↔PT link only** — no change to receiving/posting behaviour or the money path. Branch
`implement-inbound-plan` (not merged).

**Renames (cosmetic):**
- **"Inbound" → "Stock Receive"** (nav + page). It is *purely receiving*: per-store pending
  bookings, receive-against-a-booking, direct (booking-less) receipt, and the company invoice
  upload. `navConfig.ts` (Store Ops "Receive"→"Stock Receive", Documents "Inbound (GRN / PT)"→
  "Stock Receive"), `Inbound.tsx` heading + back-links; routes unchanged (`/inbound`,
  `/store/receive` still resolve to `InboundPage`).
- **"PT Mapper" → "PT File Operation"** (`navConfig.ts`, `PtMapper.tsx` header + the two detail/
  queue back-links; `Home.tsx` warehouse card sub-copy).

**Stock Receive = receiving only:** the warehouse work queue ("arrivals awaiting PT" + "Make PT
file") was **removed** from this page. Lifted `InboundQueueCard` + `useInboundQueue` + `useMakePt`
out of `Inbound.tsx` into a shared `components/InboundQueueCard.tsx` (GRN detail still uses
`useMakePt`).

**PT File Operation = two sub-tabs on one page** (D1=A; internal state synced to `?tab=mapper|making`,
default `mapper`):
- **PT File Mapper** (branded) — **invoice-first entry (D3):** pick the received invoice (from
  `GET /inbound/grns`, filtered to rows with an `invoice_number`) → enter mapping mode → upload the
  brand PT, which is linked to that GRN. Escape hatch "Map without an invoice" preserves the old
  behaviour. File list filtered to `source !== "invoice"`. Keeps the Learning-proposals +
  Unmapped-queue header links.
- **PT File Making** (non-branded) — hosts the **moved** work queue + "Make PT file". File list
  filtered to `source === "invoice"`.

**Backend (small, additive):** `PtFileListCreateView.create()` accepts an optional `grn` id and sets
`pt.grn` on the created file, guarded by the **one-live-PT-per-GRN** check (409 with `pt_file_id` if a
non-cancelled PT already exists; 404 if the GRN is missing). The RAN-WH posting restriction is **not**
applied here — linking a brand PT to a store-received GRN is a reference, not a posting, and branded
goods legitimately land at stores. No serializer/model/migration change (`grn`/`grn_number` already
exposed; the PT detail page already renders the `GRN {n}` chip).

**Tests:** `tests/test_inbound_pt_authoring.py` extended — brand PT links at upload
(`pt.grn == grn`), a second link on a live-PT GRN → 409 (points at the existing PT), upload without
`grn` still works, missing GRN → 404. **Verified:** `pytest` link + ptmapper/inbound suites green on
real Postgres; `makemigrations --check` clean; frontend `tsc --noEmit` + `vite build` green.
*(The pre-existing `test_iteration9/10/13` live-`:8001`-server failures are environmental, unrelated.)*

## Architecture (locked by ADRs)
- **Backend:** Python 3.12 + Django 5.1 + Django REST Framework + drf-spectacular, **PostgreSQL** only.
  Kernel in `app/backend/core` (money-as-paise, append-only ledger w/ DB triggers, docstatus FSM,
  gap-free voucher series) — already built & green (75 tests).
- **Frontend:** React + TypeScript (Vite) PWA, typed against the DRF OpenAPI schema.
- **Auth:** custom JWT (djangorestframework-simplejwt), username/password, role + data-scope claims.
- **Modular monolith:** `core` < `masters` < domain apps (one Django app per module).

## Environment bridge (Emergent container)
- Platform process manager (read-only supervisor) runs `uvicorn server:app` (→ `app/backend/server.py`
  re-exports the Django ASGI app, port 8001) and `yarn start` (→ Vite, port 3000).
- `/app/backend` & `/app/frontend` are **symlinks** to `/app/app/backend` & `/app/app/frontend`.
- Local PostgreSQL 15 (`kdps_dev`, user `kdps`); `DATABASE_URL` in `app/backend/.env`.
- Served deps live in `/root/.venv` (py3.11); canonical CI deps via `uv` (py3.12).

## User personas / roles (configurable; seeded working set)
Owner/Director, HO Ops/Buyer, Accounts/Finance, Warehouse/Inward, Store Manager, Store Staff/Cashier,
Data Steward, IT/System Admin. (AI service account deferred.) Scope dimension is separate from role:
all / entity / region / store_group / store, resolved over LegalEntity → GSTIN → Store.

## Design language — "Warm" (approved 28 Jun 2026)
Navy #1f2d4d + rust #c4623f on warm cream surfaces (paper #faf7f2, surface #fffdfb, beige rail #f1ece4);
per-layer colour bands; system fonts only + ui-monospace for IDs/money; navy-tinted shadows; 16px card
radius. Tokens centralised in `frontend/src/index.css`. Brand red #e53e35 reserved for wordmark/login/one CTA.

## Implemented — Vendor ageing, RBAC editor, `/inbound`, OpenAPI client, auth hardening (28 Jun 2026) ✅
- **Vendor-dues ageing:** `GET /api/finledger/vendor/ageing` now calculates outstanding vendor dues from the append-only vendor ledger using FIFO allocation, grouped into **0–30 / 31–60 / 60+** buckets. `/ledgers/vendor` shows ageing summary cards and vendor-level ageing table beside existing balances and entries.
- **Users & Roles editor:** `/masters/users` and `/edges/rbac` now provide an owner/IT-admin gated editor for creating/updating roles, nav groups, users, role assignments, active/staff flags, passwords, and store-scoped users. APIs added under `/api/auth/admin/{meta,roles,users}`.
- **GRN UI route:** `/inbound`, `/inbound/new`, and `/inbound/:id` are first-class routes for store and owner receiving flows; Store Ops and Documents nav now point to `/inbound`. Store users get locked receiving store, direct GRN creation, and detail navigation.
- **OpenAPI TS seam:** Generated `frontend/src/lib/api-schema.ts` from DRF schema via `openapi-typescript`; `api.ts` now exposes generated schema types plus `openApiClient` while preserving existing Axios compatibility. New RBAC screen uses the typed API helper.
- **Auth hardening from retest:** Added header-or-cookie JWT authentication (`CookieOrHeaderJWTAuthentication`), httpOnly `access_token` / `refresh_token` cookies on login/refresh, cookie clearing on logout, bcrypt-sha256 password hasher preference with PBKDF2 fallback, and `seed_admin` alias to existing `seed_foundation`.
- **Tested:** iteration_9 passed product flows; iteration_10 passed auth-cookie hardening + regression checks. Self-tests: Django check, targeted Python/TS lint, frontend typecheck, `pytest tests/test_iteration9_rbac_vendor_inbound.py` 8/8, browser smoke. **Known non-app issue:** external preview ingress still injects wildcard CORS headers on OPTIONS; internal Django CORS returns explicit origin + credentials.

## Implemented — Alpha-testing UI polish (28 Jun 2026) ✅
- **Login simplified:** left-side brand panel now shows only the logo mark + “KDPS Operating System”; descriptive copy and module chips removed.
- **Coming-soon placeholders:** unbuilt routes now show a clean “Coming soon” message with a short explanation of what that page will do; removed “191 pages across 14 modules” roadmap copy.
- **Configurable shell:** sidebar width is resizable via a drag handle and persists in local storage. Sidebar items inside each section can be drag-reordered for early alpha testing; group/section positions remain fixed.
- **Dashboard configurability:** home dashboard cards can be selected/hidden via “Configure dashboard”, reordered by dragging, and clicked to open a compact modal with a small visual graph + purpose text. Roadmap/build-status panel removed from dashboard.
- **Tested:** targeted JS lint clean, TypeScript typecheck clean, browser smoke verified login copy removal, dashboard config modal, dashboard card modal, coming-soon copy, and sidebar resizing.

## Implemented — Code review stability fixes (28 Jun 2026) ✅
- **PT mapper refactor:** split `ptmapper/engine.py::map_record()` into focused extraction, validation, price, resolution, row-building, and blank-column helpers while preserving output behavior.
- **Inbound GRN refactor:** split `_add_grn_line()` validation/parsing and booking-line variance checks into smaller helpers; added safe integer conversion for received/damaged quantities.
- **Stock ledger posting refactor:** split `post_pt_inward()` into PT-row entry construction, batch entry building, and PT-posted state update helpers; append-only posting behavior preserved.
- **Identity checks reviewed:** production files flagged by the report contain correct `is None` / `is not None` checks only; no unsafe `is "literal"` comparisons were found.
- **Auth type hints:** added explicit signature typing for cookie/header JWT authentication and removed unused import after tester feedback.
- **Tested:** testing_agent iteration_11 passed backend regression. Additional self-checks: Python lint clean, Django check clean, `tests/test_refactor_regression.py` 6/6, `tests/test_iteration9_rbac_vendor_inbound.py` 8/8, and `tests/test_iteration11_pt_posting_regression.py` 3/3.

## Deployment readiness check (28 Jun 2026) ⚠️ — SUPERSEDED
> **SUPERSEDED (see "Current state — 2 July 2026" at top).** This blocker is resolved: the app now deploys to a **Render alpha** (Postgres 16, from `render.yaml` on `main`) — it was never migrated to MongoDB, and a GitHub remote with merged PRs now exists. Kept below as history.
- **Deployment agent status:** FAIL for Emergent managed deployment because KDPS intentionally requires **PostgreSQL**, while the target managed platform health check expects MongoDB-only managed database support. This is architectural, not a runtime regression.
- **Checks passed:** supervisor config exists; frontend build passes; Django system check passes; ports are correct; CORS/CSRF settings are present; secrets/URLs are environment-driven; no mocked API layer.
- **Hardening applied:** frontend `REACT_APP_BACKEND_URL` now fails fast when missing; backend `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, and `DATABASE_URL` now fail fast when missing.
- **Tested:** testing_agent iteration_12 passed deployment-readiness regression; pytest `tests/test_iteration12_deployment_readiness.py` passed 8/8 after backend env hardening.
- **Deployment blocker remaining:** provide/confirm external managed PostgreSQL `DATABASE_URL` or choose a major database migration strategy. Do not migrate to MongoDB without explicit architecture approval because append-only ledger guarantees are Postgres-oriented.

## Implemented — Repo deploy-readiness (no app logic changes) (Jun 2026) ✅
- **.gitignore bug fixed:** removed `/app/backend` and `/app/frontend` patterns that (anchored to repo root `/app`) silently ignored the *real* source at `app/backend/*` & `app/frontend/*`. Now tracked: `ptmapper` (16), `finledger` (9), `stockledger` (9) apps + new frontend pages (Bookings/Inbound/PtMapper/StockLedger/VendorLedger/CashLedger/StockOnHand → 15 files in `src/pages`).
- **Postgres data untracked:** `git rm -r --cached .pgdata` removed 1539 wrongly-tracked PG data files; `.pgdata/` added to `.gitignore`.
- **Missing server dep added:** `uvicorn[standard]>=0.25` added to `app/backend/pyproject.toml` (previously only in container `/root/.venv`). Verified a fresh `uv sync` venv boots `uvicorn server:app` and serves `/api/auth/login` (HTTP 200).
- **Fresh-clone build verified:** `uv sync` (55 pkgs, incl. openpyxl/xlrd/pyxlsb/uvicorn) + `yarn build` (tsc + vite, 1863 modules) both succeed from committed `uv.lock` / `yarn.lock`.
- **settings.py env hardening:** removed hardcoded `pt-mapper.preview...` host from CSRF default (now `https://*.emergentagent.com` wildcard, still covers preview); added additive env-driven `CORS_ALLOWED_ORIGINS`. The 4 deploy vars stay `os.environ[...]` fail-fast.
- **Backend start cmd (fresh clone, from `app/backend`):** `uv sync && uv run python manage.py migrate && uv run uvicorn server:app --host 0.0.0.0 --port $PORT`.
- **Tested:** testing_agent iteration_13 → backend 8/8 + frontend login→dashboard 100%, 0 CORS regressions. **GitHub push still pending — use the "Save to Github" feature** (no git remote configured in container).


## Implemented — Code-review remediation Phase A + B (30 Jun 2026) ✅
Acting on the LordCode implementation review (`implementation-review-2026-06-30`). The
review's critical/high findings were **independently verified** against live code AND the
locked decisions in `CONTEXT.md` (all confirmed; not false positives). User chose: do
Phase A (security) + Phase B (verification spine) now, then PAUSE before the money core.

**Phase A — security holes (exploitable now, no money rework):**
- **CORS:** the broad `*.emergentagent.com` + localhost origin regexes are now gated behind
  `DEBUG` (`config/settings.py`). In production (`DEBUG=0`) CORS is driven purely by the
  exact-origin `CORS_ALLOWED_ORIGINS` env allowlist — no credentialed wildcard on the shared
  preview domain. Preview (DEBUG=1) behaviour unchanged.
- **Fail-closed reads:** `scope_by_store` applied to all stock-ledger reads
  (`stockledger/views.py`: list/summary/on-hand). `finledger` vendor+cash reads now gated by a
  new `IsFinance` DRF permission (payables/ageing/cash are finance-only).
- **Money/role gates (`ptmapper/views.py`):** PT `post`/`reverse` restricted to Patna/HO roles
  `{accounts, owner, it_admin}`; `review/resolve` restricted to mapping stewards
  `{warehouse, data_steward, ho_ops, owner, it_admin}`. Role check runs BEFORE object lookup
  (forbidden→403 even for missing pk; allowed→404).
- **Append-only audit:** posted/sent PT can no longer be `DELETE`d (`PtFileDetailView.destroy`
  guards stage==MAPPING → 409 otherwise).
- **Booking write-path scope (`inbound/views.py`):** GRN create now scope-checks the booking
  (`_resolve_booking`, fail-closed by destination store) and resolves the booking line only
  within that booking — a payload can no longer mutate another store's booking line.
- **Seed hardening (`seed_foundation.py`):** demo users/sample-booking/credentials gated behind
  `SEED_DEMO` (default "1"; set "0" in prod); `set_password` now runs **only on user create** —
  a redeploy no longer reverts an operator-rotated password. `/admin` mount gated behind
  `DEBUG or ENABLE_DJANGO_ADMIN=1` (`config/urls.py`).

**Phase B — verification spine:**
- Deleted the bug-cementing assertions: `test_iteration11` no longer asserts "a vendor bill is
  always raised" (liability is commercial-model dependent — Phase E golden tests will own it);
  rewrote the two seed-revert tests (`iteration10`, `iteration12`) to assert the NEW correct
  behaviour (re-seed does NOT overwrite a rotated password) with self-cleaning `finally` restore.
- New `tests/test_iteration14_security_hardening.py`: finance-gated finledger reads, Patna-gated
  PT post/reverse, steward-gated review-resolve, store-scoped stock reads, PT delete guard.
- Fixed an order-dependent flake in `test_foundation::test_me_without_token_returns_401` (used a
  fresh session so a shared-jar cookie can't authenticate it).
- Added `.github/workflows/ci.yml` — Postgres service + kernel anti-cheat suites + API
  regression suites + frontend build (runs on push via "Save to Github"; not executed in-container).
- **Tested:** full backend suite green — **130 tests** (`tests/` + `core/tests`) pass deterministically;
  browser smoke: owner login → dashboard → stock ledger OK; Django check clean.

**New env vars (defaults preserve preview; set these for production):**
`SEED_DEMO=0`, `ENABLE_DJANGO_ADMIN=0` (omit), `CORS_ALLOWED_ORIGINS=https://app.kdps...` (exact),
`DJANGO_DEBUG=0`.

**PAUSED here for user review before the money core (Phases C–E).**

## Code-review remediation — Phase C + E DONE, D partial (30 Jun 2026) ✅
Labels below are the **code-review** phases (distinct from the older product phases C/D/E).

**Phase C — kernel posting primitive (DONE, 8 kernel tests):**
- `core/gl.py` — `GLEntry`, the append-only **value general ledger**: one balanced
  posting fans into ≥2 legs, signed paise (debit +, credit −), so a voucher sums to 0
  and the whole ledger's `trial_balance()` = Σ(amount) = 0. `GLAccount` codes
  (INVENTORY, VENDOR_PAYABLE, GRNI, SOR_STOCK, SOR_CONTRA, INPUT_GST, CASH).
- `core/posting.py` — `post_entries(doc, legs)`: the **sole** GL writer, balanced-or-fail
  (Σ=0, ≥2 legs, integer paise), all-or-none in one txn, dims snapshotted; `Leg`/`dr`/`cr`/`PostingRef`.
- `core/ledger.py` — `truncate_guard_sql`: `BEFORE TRUNCATE` trigger (binds even the
  superuser) + `REVOKE TRUNCATE`, applied to GL + stock + vendor/cash + probe tables
  (migrations `core/0005`, `stockledger/0002`, `finledger/0002`). Test-only escape hatch
  (`kdps.allow_truncate`) set per-connection by `conftest.py` so Django flush still works.

**Phase E — money slice rebuilt on `post_entries` (DONE, 5 per-model golden tests). Fixes C1/C2/C3:**
- **C2:** stock valued at **P RATE** (locked unit cost), not ex-GST BASIC; `P RATE ≤ MRP`
  enforced; **strict money** — an unreadable/missing/over-MRP cost raises `PtPostingError`
  → API **422** listing offending rows (no silent ₹0 valuation).
- **C1:** vendor liability branches by **commercial model** (booking snapshot): owned
  (Outright/Correction) → bill at PT; brand-owned (SOR/Consignment) → **never** a payable at PT.
- **C3:** every PT inward now posts a **balanced value voucher** via `post_entries`
  (owned → Dr INVENTORY/Cr VENDOR_PAYABLE; brand-owned → off-book Dr SOR_STOCK/Cr SOR_CONTRA;
  direct → Dr INVENTORY/Cr GRNI). Reversal appends the negated mirror of stock + GL + payable.
- `stockledger/posting.py` rewritten; `finledger.post_pt_vendor_bill` model-gated.

**Phase D — gap-free numbering DONE; full FSM reparent PENDING (design decision):**
- DONE: GRN + Booking numbers now via gap-free `VoucherSeries.allocate` (`26-27/<scope>/GRN|BK/<n>`),
  replacing the racy `count()+1` (review H5). Idempotent under concurrency.
- PENDING (needs user steer): reparent `PtFile`/`GRN`/`Booking` onto `core.Document` (docstatus FSM,
  DB immutability, `idempotency_uuid`, `select_for_update` on post, **reversal-as-cancel**).
  *Design finding:* Booking is a poor fit for freeze-on-submit (it is numbered at birth and mutates
  through fulfilment — status/received roll-ups), and PT reversal-as-cancel changes the
  current "reverse → back to 'sent' → re-post" correction workflow + frontend stage display.
  Recommend: fully reparent **PtFile** + **GRN** (clean fits); keep **Booking** a living master
  with gap-free numbering (+ optional `idempotency_uuid`). Awaiting confirmation.
- Tested: full suite **143 pass** (8 GL + 5 Phase-E golden + existing), live MUFTI PT post/reverse OK.

**Phase F (P1) — NOT started:** `sku` + `cohort(barcode,season)` masters; persisted per-unit
`unit_cost_paise` + DB `CHECK unit_cost ≤ mrp`; `MoneyField` on `*_paise`; materialised
stock-on-hand + indexes; fix silent `[:2000]`/`MAX_ROWS=8000` truncation.

## Phase F (P0) + Books-Health card + Master stewardship — DONE & TESTED (30 Jun 2026) ✅
Delivered the user-approved trio (a + b + c). All verified: backend **97 unit + 17 integration pytest pass**,
testing_agent **iteration_15** (frontend 6/6, backend 7 pass / 1 skip-by-design), curl e2e.

**(a) Phase F — identity & scale (P0):**
- **MoneyField everywhere:** `*_paise` columns now use `core.money.MoneyField` (refuses float/Decimal at the
  write boundary) — `vendors.Booking.estimated_value_paise`, `vendors.BookingLine.mrp_paise`,
  `masters.GstSlab.threshold_paise`, plus the new SKU/cohort/on-hand money columns. (`vendors/0002`, `masters/0002`).
- **SKU + cohort masters** (`masters.Sku`, `masters.Cohort`): barcode IS the SKU; a cohort = (barcode, season)
  holding the locked per-unit `unit_cost_paise` with a **DB CHECK `unit_cost ≤ mrp`**. Registered/refreshed inside
  every PT post (`stockledger.posting._register_identity`). Backfilled from the live ledger in `masters/0002`.
- **Materialised stock-on-hand** (`stockledger.StockOnHand`, `db_table=stockledger_on_hand`): indexed projection
  per (store × barcode), maintained inside each post/reverse (`_apply_on_hand`), backfilled in `stockledger/0003`,
  rebuildable via `manage.py rebuild_stock_on_hand`. `StockOnHandView` now serves all 3 groupings from it.
- **Truncation no longer silent:** PT reader flags `meta.truncated` + `row_limit` when a file hits the 8000-row cap
  (banner `ptfile-source-truncated-banner`); on-hand reports `summary.{lines,displayed,truncated}` (banner
  `onhand-truncated-banner`) — the old silent `[:2000]` drop is gone.

**(b) Books-Health card (P1):** `GET /api/finledger/health` (IsFinance-gated) returns trial balance (Σ GL legs = 0),
balanced flag, and the equation of state (Σ inventory+SOR vs Σ payable+GRNI+contra). Owner dashboard renders the
"Equation of state" panel (`trial-balance-panel`) — live: **Books tie · ₹0 · 8 vouchers · 16 legs**.

**(c) Master Data stewardship UI (P1):** create/edit for Stores/Brands/Seasons/GSTINs. New steward-gated CRUD
(`masters.IsMasterSteward` = owner/it_admin/data_steward; reads open) — ListCreate + Detail views, `/masters/{res}` &
`/masters/{res}/{id}`. Frontend `MasterPages.tsx` adds New/Edit editors + active toggle per registry (New/Edit hidden
for non-stewards e.g. store cashier). Soft-deactivate, never hard-delete (ledger-referenced masters).

**Phase F (P1) — NOT started (superseded above):**

## Phase D frontend verification — DONE (30 Jun 2026) ✅
- testing_agent iteration_14 → **frontend 100% (8/8 flows, 0 console errors, 0 bugs)**. Closes the
  last open item: confirmed the PtFile/Grn → `core.Document` reparenting renders correctly on the UI.
- Verified: computed `PtFile.stage` badge/stepper tracks docstatus across all 4 stages
  (mapping/sent/posted/reversed with labels Mapping (Warehouse)/Sent to Patna/Posted to system/Reversed);
  FSM-frozen posted/reversed files hide edit/send/post (only Reverse + Export + ledger link); role-aware
  action gating (Owner/Warehouse/Accounts) matches spec; store-cashier (deo.cashier) scope-locked
  (receive-store-locked, only DEO GRNs); fresh direct GRN minted gap-free `26-27/DEO/GRN/5`.
- No frontend code changes were required — serializers kept the same `stage`/`stage_label` shape the
  React pages already consume. **Code-review remediation Phases A–E + D reparent are now complete & verified.**

## Implemented — Vendor & Cash ledgers (append-only) (28 Jun 2026) ✅
- **New `finledger` app**: `VendorLedgerEntry` (accounts payable) + `CashLedgerEntry`, both extending
  `core.LedgerEntry` — append-only (ORM + `BEFORE UPDATE/DELETE` trigger on `finledger_vendor_entry` /
  `finledger_cash_entry`, verified blocks superuser). Gap-free vouchers via `VoucherSeries` under store_code
  'HO' (doc_types VEND / CASH). Sign: vendor +bill/−payment (Σ=payable); cash +receipt/−payment (Σ=on hand).
- **Posting** (`finledger/posting.py`, finance-only via `_is_finance`): manual Record Bill / Record Payment
  (payment auto-posts a paired cash-OUT) / Record Cash Movement; append-only reversals (a vendor-payment
  reversal also reverses its paired cash row). **Auto vendor bill**: `stockledger.post_pt_inward` now calls
  `post_pt_vendor_bill` when a PT file is posted *with a booking* (amount = BASIC×qty stock value); PT reverse
  calls `reverse_pt_vendor_bills`.
- **API**: `/api/finledger/vendor/{entries(paginated),balances,bill,payment,entries/:id/reverse}` and
  `/api/finledger/cash/{entries(paginated),summary,movement,entries/:id/reverse}`.
- **Screens**: `/ledgers/vendor` (`VendorLedger.tsx`) — payable summary, outstanding-by-vendor, paginated
  entries, Record Bill/Payment forms, Reverse. `/ledgers/cash` (`CashLedger.tsx`) — cash-on-hand by account,
  paginated movements, Record Movement (account select CASH/BANK/UPI), Reverse. Nav wired; finance-role gated.
- **Tested:** testing_agent iteration_8 → frontend 100% (bill/payment+auto cash-out, reversals, pagination,
  role gating: warehouse sees no posting buttons). Backend curl + append-only triggers verified directly.

## Implemented — Ledgers: pagination + Stock-on-Hand + nav (28 Jun 2026) ✅
- **Server-side pagination** on `GET /api/stockledger/entries` (DRF `PageNumberPagination`, page_size 50, scoped to this view only — `{count,next,previous,results}`); Stock Ledger page now has Prev/Next + "Showing X–Y of N".
- **Stock on Hand** screen (`/ledgers/stock-on-hand`, `StockOnHand.tsx`) backed by `GET /api/stockledger/on-hand?group_by=sku|brand|store` — live net position (Σqty>0) from the append-only ledger, with SKU/Brand/Store grouping tabs + summary cards. Cross-linked with Stock Ledger.
- **Ledgers nav wired**: added "Stock on Hand" item; Vendor/Cash Ledger remain intentional "Planned" placeholders (route via catch-all → ModulePage).
- **Tested:** testing_agent iteration_7 → frontend 100% (5/5: pagination, on-hand 3 groupings with consistent 241-unit total, cross-links, nav placeholders). Added `.catch` error surface on the on-hand fetch.

## Implemented — Code-quality refactor (28 Jun 2026) ✅
- Behavior-preserving refactor from a code review: split high-complexity functions into focused helpers —
  `engine.map_record` (`_map_prices`/`_map_season`/`_map_taxonomy`), `ptmapper.views.process_file` +
  `ReviewResolveView.post` (`_resolve_single`/`_resolve_taxonomy`/`_repropagate`), `inbound.views.create`
  (`_resolve_receiving_store`/`_build_grn`/`_add_grn_line`), and `seed_ptmapper.handle`. Removed dead code +
  unused import, added type hints. **Verified zero behavior change**: 84/84 kernel+foundation pytest, new
  `tests/test_refactor_regression.py` 6/6, ruff/django-check clean, seed reproduces identical counts
  (iteration_6, 100%). Note: the review's "3 undefined variables" and "35 is-vs-`==`" were tool false
  positives (all are correct `is None`/`is True/False`; changing them would be a regression) — not applied.

## Implemented — Phase E complete: append-only Stock Ledger posting (28 Jun 2026) ✅
- **First real business ledger over the `core` kernel.** New `stockledger` app: `StockLedgerEntry(LedgerEntry)`
  — append-only (ORM guard + `BEFORE UPDATE OR DELETE` DB trigger + REVOKE, verified blocks superuser
  UPDATE/DELETE). Self-describing rows (barcode SKU + brand/design/colour/size/season/item/HSN), signed
  `qty`, value `amount` = BASIC×qty in paise, `kind` (pt_inward / pt_reversal), gap-free `doc_number`.
- **Patna "Push into system"** (`POST /api/ptmapper/files/:id/post`, body optional `{booking_id}`) →
  `post_pt_inward`: mints a gap-free `PT` voucher for **RAN-WH** (`26-27/RAN-WH/PT/n` via `VoucherSeries`),
  writes one inward entry per KDPS row, optionally **reconciles a Booking** (matches KDPS DESIGN+SIZE to
  `BookingLine.style_code`+`size`, bumps `inwarded_qty`), locks the file. Verified: MUFTI 97 rows valued
  (₹814.25/₹1920.10…), booking inwarded 39→5 & 32→3.
- **Append-only correction** (`POST …/reverse` → `reverse_pt_inward`): mints its own PT voucher, writes a
  negative mirror of every live inward row, un-bumps the booking, returns the file to `sent` (fix & re-post).
  Verified net qty → 0 across the inward+reversal pair.
- **API & UI:** `GET /api/stockledger/entries` (`?pt_file=` / `?doc_number=`) + `…/summary`. New **Stock
  Ledger page** (`/ledgers/stock`, `StockLedger.tsx`): 4 summary cards + entries table (inward green /
  reversal red chips). PT detail gains a booking selector on post, a Reverse button, and a posted banner
  showing the voucher + booking + "View in Stock Ledger" (links by file → shows inward + reversals together).
- **Tested:** testing_agent iteration_5 → frontend 100%, 0 bugs (post±booking, reconcile banner, reversal,
  Stock Ledger page + filter, role gating). Backend curl + the append-only trigger verified directly.

## Implemented — Phase D Slice 2 + Phase E workflow: Readers & Warehouse→Patna workflow (28 Jun 2026) ✅
- **Legacy/binary readers** (`ptmapper/engine.py`): `read_sheets` now dispatches by extension **and** magic
  bytes — `.xls` via xlrd (OLE2), `.xlsb` via pyxlsb (Madura SAP), `.xlsx` via openpyxl, `.csv`; correctly
  routes mislabelled files (a `.xls` that is really `.xlsx`, a `.csv` that is OLE2). Excel serial dates in
  `.xlsb` decoded. `MAX_ROWS=8000` cap honoured. Deps added to `pyproject.toml`: openpyxl, xlrd, pyxlsb.
- **Workflow stages** on `PtFile`: `mapping` (Warehouse/Ranchi) → `sent` (to Patna HO) → `posted` (locked).
  Plus `manually_edited`, `sent_at`, `posted_at`. Resolve-propagation skips hand-edited/non-mapping files.
- **Hand-editable KDPS table**: warehouse opens Edit → every cell becomes an inline input → Save
  (`PATCH /api/ptmapper/files/:id/rows`, recomputes blanks/counts, sets `manually_edited`).
- **Send / Recall / Post / Export**: `POST files/:id/send` (warehouse→Patna), `POST files/:id/recall`
  (Patna sends back), `POST files/:id/post` (Patna pushes into system → **locks**), `GET files/:id/export.xlsx`
  (real .xlsx, KDPS 22-col order) alongside the existing CSV export. `rerun` is 409-guarded to mapping stage.
- **Frontend** (`PtMapper.tsx`): list gains Mapping + Workflow columns; detail page has a 3-step StageStepper,
  role-aware actions (owner=all, `warehouse`=edit/send, `accounts`=Patna recall/post on sent files only),
  inline edit grid, Excel+CSV download, stage banners. Large files render a 1000-row display cap (download
  for full set) to keep the DOM light.
- **Tested:** testing_agent iteration_4 → frontend 100%, 0 bugs across 11 scenarios (3 new readers via UI
  upload, edit→save, send, post-lock, recall, role gating for all 3 users, xlsx/csv export, regression).
- **NOT yet done (next P0):** "Push into system" currently transitions to `posted` and **locks** the record;
  it does **not yet write the `core` stock ledger**. That first stock-ledger write is the remaining Phase E work.

## Implemented — Phase D: PT File Mapper (Warehouse / Ranchi) (28 Jun 2026) ✅
- **Deterministic, table-driven engine — NO AI** (`ptmapper` Django app). Reads a brand PT file
  (.xlsx/.csv), detects the header row + data range, identifies the archetype profile (A generic /
  B Tally-Vistaar / C Ginesys PT-EMAIL), maps columns, normalises controlled fields via DB lookups,
  derives SEASON (from invoice date), NAG=QTY, MARGIN=(MRP−P RATE)/MRP×100, OUTPUT TAX=INPUT TAX,
  and carries BASIC / P RATE from source (money flagged, CA-gated per spec §5).
- **Lookup tables are the product:** seeded from KDPS's real Master Sheet via `seed_ptmapper`
  (970 controlled values, 592 brands, 23 colours, 135 sizes, 98 ITEM→sub/type, 30 taxonomy rules).
  Unmapped raw values go to a **review queue**; a human maps one (adds a Lookup/TaxonomyRule) and
  re-running re-maps every file — zero code change. COLOR vocab keeps price tiers (PREMIUM/ECONOMY).
- **API:** `POST /api/ptmapper/files` (upload+map), `GET files/:id`, `POST files/:id/rerun`,
  `GET files/:id/export` (CSV in KDPS 22-col order), `GET /api/ptmapper/review`,
  `POST /api/ptmapper/review/:id/resolve`, `GET /api/ptmapper/controlled?dimension=`.
- **Frontend** (`PtMapper.tsx`, Documents > PT Mapper): upload + files table, file detail with the
  wide KDPS output table (blank cells flagged amber) + Re-run + Export CSV, and the Unmapped queue
  (single-dim select resolve + 5-axis taxonomy resolve). Reachable by warehouse + owner roles.
- **Tested:** testing_agent iteration_3 → frontend 100%, 0 bugs. Verified resolve→propagate loop
  (DEAL unresolved 7→6→5). Backend verified via curl (MUFTI 97 rows; 88-BEIGE→CREAM re-mapped 15 rows).
- **Deferred to Slice 2:** `.xls`/`.xlsb` readers (Jockey/Madura, archetypes D/E/F) — currently return a
  friendly "not yet supported" message.

## Implemented — Phase 1 Inbound: Booking + Receive (GRN) (28 Jun 2026) ✅
- **Backend (Django apps):** `files` (DB blob storage), `vendors` (Vendor master + Booking + BookingLine,
  two-step human-in-the-loop draft→confirm), `inbound` (Grn + GrnLine, receive against a booking OR direct),
  `aiagents` (Gemini document extraction via Emergent universal key). Endpoints: `GET/POST /api/bookings`,
  `POST /api/bookings/draft` (AI), `GET /api/bookings/:id`, `GET /api/vendors`, `GET /api/inbound/pending`,
  `POST /api/inbound/invoice-draft` (AI), `GET/POST /api/inbound/grns`, `GET /api/inbound/grns/:id`.
- **Frontend:** `Bookings.tsx` (list / create with AI file-draft + graceful manual fallback / detail) and
  `Inbound.tsx` (GRN list + pending-bookings, New receipt: against-booking auto-prefill OR direct receipt,
  invoice AI prefill that degrades to manual, GRN detail). Routes wired in `App.tsx`; `/store/receive` → Inbound.
- **AI (Gemini, Emergent key):** booking Receiving Reader + store/warehouse Invoice Reader. Universal Key
  balance topped up by user (28 Jun 2026) — extraction verified (CSV read 2/2 lines @100% confidence).
- **Scoping:** fail-closed — store user (deo.cashier) sees a LOCKED store on receive + only their store's
  pending bookings; never warehouse/other-store data. Verified.
- **Tested:** testing_agent iteration_2 → frontend 100% (11 flows), 0 bugs. Backend verified via curl.

## Implemented — Phase 0 Foundation (28 Jun 2026) ✅
- **Auth:** JWT login/refresh/logout/me; brute-force lockout (5 fails → 15 min, HTTP 429); idempotent
  `seed_foundation` (roles, masters, demo users) → writes `memory/test_credentials.md`.
- **RBAC + scope:** `accounts` app (configurable `Role` with `nav_groups`/`landing_page`, custom `User`,
  `ScopeType`). Fail-closed store scoping verified (store user sees only their store).
- **Masters spine:** `masters` app (LegalEntity, Gstin, Store, Season, Brand w/ two-axis commercial model,
  GstSlab) + read-only API + Django admin.
- **Frontend:** warm login (demo-login chips), role-aware app shell (5-layer sidebar, store/GSTIN switcher
  locked for single-store users, user menu), per-role dashboards (owner/ops/finance vs store vs warehouse),
  INR Lakh/Crore + SKU-grain primitives, real Master Data tables (Stores/Brands/Seasons/GSTINs), placeholder
  pages for not-yet-built modules.
- **Tested:** testing_agent iteration_1 → backend 100%, frontend 100%, no bugs. Regression suite at
  `app/backend/tests/test_foundation.py`.

## Backlog (prioritised)
- **P0 / Phase D Slice 3 — printed-invoice/anchored-header archetypes:** `ambreli`/USPOLO style files read OK
  but produce 0 KDPS rows (no generic header match → need profiles D/E/F). Build those profiles when needed.
- **P1:** Master Data stewardship UI (create/edit master data with stewardship controls).
- **P1:** Continue replacing legacy page calls with `openApiClient` / generated schema types as pages are touched.
- **P1 — Phase 2:** Selling floor / POS ingest (outbox/dead-letter).
- **P2 — Phase 3+:** Money-in (collection & 3-rail bank audit), Transfers, Payments/vendor settlement,
  Controls (exception inbox, reconciliations, approvals/second-eye), Tally bridge, Intelligence (suggest-only).
- **P2 — Non-Branded Booking / PO Maker agent:** deferred pending user's client clarification.
- **P2 — Production hardening:** External ingress/proxy CORS policy alignment, reduce localStorage token reliance now that httpOnly cookies exist, HTTPS/secure-cookie review, Django+Postgres deploy path validation.

## Next action items
1. Run broader alpha QA over the current screens and capture issues from real users.
2. Build Master Data stewardship UI for create/edit of mutable masters.
3. Add Vendor dues drill-down/export if accounts users need follow-up bill-level ageing.
4. Continue POS ingest / selling floor planning after current P1 review.
