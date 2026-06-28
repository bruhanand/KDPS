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
- **P0 / Phase 1 — Inbound:** Booking → GRN → PT(branded) → stock ledger entries; barcode registry; the
  first money/stock vertical slice exercising the kernel end-to-end.
- **P1:** Master Data stewardship UI (create/edit), Users & Roles admin screen (make roles editable in-app),
  generated OpenAPI → typed TS client wired into the frontend.
- **P1 — Phase 2:** Selling floor / POS ingest (outbox/dead-letter).
- **P2 — Phase 3+:** Money-in (collection & 3-rail bank audit), Transfers, Payments/vendor settlement,
  Controls (exception inbox, reconciliations, approvals/second-eye), Tally bridge, Intelligence (suggest-only).
- **Infra:** decide production deployment path for the Django+Postgres stack (Emergent deploy is tuned for
  the default FastAPI+Mongo stack — confirm with support before go-live).

## Next action items
1. Confirm Phase-1 (Inbound) scope & open questions from the application map before building.
2. Wire a generated typed API client; add Master Data create/edit + in-app role editing.
