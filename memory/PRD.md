# KDPS Operating System — PRD / Build Memory

## Problem statement
KDPS Lifestyle Pvt Ltd is a multi-brand apparel retailer operating stores across
**Bihar & Jharkhand** (one PAN / one legal entity / two state GSTINs). We are building a
**deterministic retail ERP** ("KDPS Operating System"): documents write append-only
ledgers, Tally remains the statutory book, AI is suggest-only at the edges. The repo's
`docs/` folder holds the full plan (constitution `CONTEXT.md`, 12 rules, 7 ADRs, a
191-page application map across 14 modules).

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
- **P0 / Phase D Slice 2 — more readers/profiles:** `.xls` (Jockey, FAHRENHEIT, SUVIDHI, ambreli, TWILLS)
  + `.xlsb` (Madura) + headerless CSV (USPOLO); archetypes D (Jockey SAP), E (wide SAP), F (printed invoice
  with anchored header). Confirm BASIC/P RATE source columns + any loading factor with finance/CA.
- **P0 / Phase E — Patna Inward Review & Reconcile (HO):** UI/API for Patna HO to review mapped PT files,
  approve, reconcile booking lines, and trigger the `core` ledger stock posting (first stock-ledger write).
- **P1:** Master Data stewardship UI (create/edit), Users & Roles admin screen (in-app role editing),
  generated OpenAPI → typed TS client wired into the frontend (replace hand-rolled `api.ts`).
- **P1 — Phase 2:** Selling floor / POS ingest (outbox/dead-letter).
- **P2 — Phase 3+:** Money-in (collection & 3-rail bank audit), Transfers, Payments/vendor settlement,
  Controls (exception inbox, reconciliations, approvals/second-eye), Tally bridge, Intelligence (suggest-only).
- **P2 — Non-Branded Booking / PO Maker agent:** deferred pending user's client clarification.
- **P2 — Production hardening:** HTTPS/secure-cookie, refresh tokens out of localStorage; confirm
  Django+Postgres deploy path with support (Emergent deploy tuned for FastAPI+Mongo).

## Next action items
1. Gather Phase D inputs: KDPS PT target schema + sample brand PT Excel files + mapping rules.
2. Build Phase D (PT mapper + unmapped queue), then Phase E (Patna inward reconcile → stock ledger).
