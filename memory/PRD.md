# KDPS Operating System — Product Requirements Document

## Original Problem Statement
Full-stack retail fashion ERP for 50+ stores (KDPS). Django 5.1 + React/TS Vite PWA. 
Phase-by-phase execution plan covering Outbound, Offers, Analytics, HR, Controls, Tally Sync, POS Integration, and Payments.

## Core Architecture
- **Backend**: Django 5.1, DRF, PostgreSQL
- **Frontend**: React 18, TypeScript, Vite PWA
- **Kernel**: Append-only ledgers, strict `post_entries` balanced engine, docstatus FSM (Draft→Submitted→Cancelled)
- **Money**: Stored as paise (integer). Never floats.
- **Documents**: Immutable once submitted (DB triggers enforce).

## Sprint Status

### Sprint 0 — Local Dev Setup & Bug Fixes ✅ COMPLETE
- Environment bootstrapped (Postgres, Python, Node)
- Fixed JWT_COOKIE_SECURE bug
- Validated finledger double-entry mechanism
- Created auth/test documentation
- Full test suite: 231 passed, 0 failures

### Sprint 1 — Outbound Module ✅ COMPLETE (6 Jul 2026)

**Backend** (18 tests, all passing):
- StoreTransfer (inter-store + store split) with TransferReceipt companion
- ReturnToVendor (defective + seasonal)
- StockAdjustment (shrinkage, miscount, damage, surplus)
- WriteOff (dead stock, refused defectives)
- VFlip (brand-owned → KDPS-owned ownership conversion)
- Full posting engine integration (stock ledger + fin ledger entries)
- API endpoints: 16 endpoints under `/api/outbound/`

**Frontend** (14 features, 100% pass rate):
- Navigation: "OUTBOUND" sidebar group with 5 items (Transfers, RTV, Adjustments, Write-offs, V-Flip)
- Transfers: List (with Inter-store / Store split tab toggle), Create (3-step form: locations + transport + lines), Detail (with Dispatch + Receive flows)
- RTV: List (with Defective / Season-end tab toggle), Create (store + vendor + brand + type + logistics), Detail (with Submit)
- Adjustments: List (with net variance display), Create (book vs counted auto-calc), Detail (with Submit)
- Write-offs: List, Create (with reason + approved_by), Detail (with Submit)
- V-Flip: List (with info banner), Create (store + brand + season), Detail (with "Flip ownership" confirm modal)
- Cross-state transfer: E-way bill warning + required field validation
- Role-guarded routes matching API guards
- All data-testid attributes for testing

**Known Gaps Carried Forward:**
- Settlement claim tracking → Sprint 8 (Payments)
- EOSS pricing rules → Sprint 2 (Offers)
- Full approval workflow (multi-tier) → Sprint 5 (Controls)
- Non-branded PT AI OCR → Future sprint
- Seasonal return window dashboard alerts → Enhancement (backend cron)

**V-Flip Reporting Verification (6 Jul 2026):**
- StockOnHand.brand correctly updates to "V {brand}" after flip ✅
- SLE entries carry V-prefix for audit trail ✅
- Brand filters correctly separate flipped vs un-flipped stock ✅
- GL posts INVENTORY (KDPS-owned), not SOR_STOCK ✅
- RTV blocked on V-flipped stock (patch applied to post_rtv) ✅
- Empty line.brand fallback fixed: uses original_brand.name, not "KDPS" ✅
- Backfilled existing "V KDPS" rows → "V Louis Philippe" ✅
- 4 regression tests: brand display, ownership GL, RTV block, empty-brand fallback

**Store-Scope Enforcement (6 Jul 2026):**
- enforce_store_scope() shared helper added to permissions.py
- Applied to all 10 outbound write paths (create + submit/dispatch/receive)
- SM for DEO gets 403 on BANKA operations, succeeds on DEO
- Admin unrestricted on all stores
- Polluted RTV id=28 cancelled and stock restored
- 10 API-level regression tests added

**Env Fix (6 Jul 2026):**
- REACT_APP_BACKEND_URL changed from hardcoded pod URL to empty (same-origin)
- api.ts gracefully falls back to same-origin when env var empty

## Upcoming Sprints (Prioritized Backlog)

### Sprint 2 — Offers / Discounts (P1)
- Brand-specific discount rules
- EOSS (End of Season Sale) pricing
- Coupon/voucher management
- Offer application engine

### Sprint 3 — Analytics / Reports (P1)
- Sales dashboards
- Stock movement reports
- Vendor ledger aging
- Financial summaries

### Sprint 4 — HR / Attendance (P1)
- Employee management
- Attendance tracking
- Leave management

### Sprint 5 — Controls (P1)
- Multi-tier approval workflows
- Exception management
- Audit trails

### Sprint 6 — Tally Sync (P1)
- Tally XML export
- Voucher mapping
- Reconciliation

### Sprint 7 — Selling + POS (P1)
- POS terminal integration
- Bill generation
- Returns/exchanges at POS

### Sprint 8 — Payments / Settlement (P1)
- Settlement claim tracking (V-flip, RTV)
- Payment collection
- Bank reconciliation

## Future / Backlog (P2)
- AI/OCR agent wiring (Gemini integration for invoice reading)
- Mobile-specific PWA optimizations
- Barcode scanning integration
- Multi-company support

## Test Counts
- Backend: 401 passed, 1 skipped, 0 failures (24 outbound posting tests + 10 store-scope API tests)
- Frontend: 14/14 features passing (testing agent iteration_21)
- Bug fix verification: 8/8 tests passed (testing agent iteration_22)
- Demo stock seeded via real inbound pipeline (Booking → GRN → PT → post_pt_inward)
- Owned RTV GL verified: Dr VENDOR_PAYABLE / Cr INVENTORY (balanced) + VendorLedgerEntry mirror
- Brand-owned (SOR) RTV GL verified: No GL entries, no vendor subledger (correct — off-book)
- V-flip verified: brand → "V {brand}", INVENTORY GL, RTV blocked on V-flipped stock
- Store-scope: SM blocked outside scope, admin unrestricted (10 API tests)
- Finledger health: balanced=true, reconciliation.reconciled=true, vendor.drift=0, cash.drift=0

## API Endpoints (Outbound)
```
api/outbound/transfers          (GET list, POST create)
api/outbound/transfers/<pk>     (GET detail)
api/outbound/transfers/<pk>/dispatch  (POST)
api/outbound/transfers/<pk>/receive   (POST)
api/outbound/rtvs               (GET list, POST create)
api/outbound/rtvs/<pk>          (GET detail)
api/outbound/rtvs/<pk>/submit   (POST)
api/outbound/adjustments        (GET list, POST create)
api/outbound/adjustments/<pk>   (GET detail)
api/outbound/adjustments/<pk>/submit  (POST)
api/outbound/writeoffs          (GET list, POST create)
api/outbound/writeoffs/<pk>     (GET detail)
api/outbound/writeoffs/<pk>/submit    (POST)
api/outbound/vflips             (GET list, POST create)
api/outbound/vflips/<pk>        (GET detail)
api/outbound/vflips/<pk>/submit (POST)
```

## Frontend Files (Outbound)
```
src/pages/OutboundTransfers.tsx   — TransferListPage, TransferNewPage, TransferDetailPage
src/pages/OutboundRTV.tsx         — RTVListPage, RTVNewPage, RTVDetailPage
src/pages/OutboundAdjustments.tsx — AdjustmentListPage, AdjustmentNewPage, AdjustmentDetailPage
src/pages/OutboundWriteoffs.tsx   — WriteOffListPage, WriteOffNewPage, WriteOffDetailPage
src/pages/OutboundVflips.tsx      — VFlipListPage, VFlipNewPage, VFlipDetailPage
```
