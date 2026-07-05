# KDPS Operating System — Product Requirements Document

## Product Summary

**KDPS Operating System** is a deterministic retail ERP for **KDPS Lifestyle Pvt Ltd**, a multi-brand Indian fashion/apparel retailer operating **50+ stores** across **Bihar & Jharkhand** (one PAN, two state GSTINs: Bihar state code 10, Jharkhand state code 20).

### Key Facts
- **Domain**: Multi-brand fashion retail (clothing, innerwear, accessories)
- **Scale**: 50+ MBO stores + warehouses, 40+ brands, 20,000+ SKUs
- **Currency**: INR (₹), money stored as integer paise
- **Tax**: Indian GST (CGST+SGST intra-state, IGST cross-state)
- **POS**: Ten Software (third-party billing counter at each store)
- **Statutory books**: Tally (separate — ERP exports vouchers to Tally)

### Core Philosophy (12 Rules)
1. Every business event is a document with a lifecycle
2. Documents write ledgers; ledgers never hand-edited
3. Master data lives in one place; documents snapshot it
4. Every fact has exactly one owner
5. Flag, never block (exceptions → queue, not halt)
6. Calculated numbers are not typed by hand
7. Outside systems need written rules + daily checks
8. AI only reads and suggests
9. Every line says exactly what item it is
10. Every action has an actor
11. Deadlines are data, not memory
12. Business differences are data, not code

## Technology Stack (ADR-0001)
- **Backend**: Python 3.12 + Django 5.1 + DRF + drf-spectacular + PostgreSQL 16
- **Frontend**: React + TypeScript (Vite) PWA
- **Auth**: JWT (djangorestframework-simplejwt) with cookie + header dual-path
- **Deployment**: Render alpha (Singapore region) — auto-deploy from `main`

## Full Module List

### Built & Functional
1. **Core / Kernel** — Money-as-paise, append-only ledgers (DB triggers), docstatus FSM, gap-free voucher numbering, balanced posting engine, Indian FY
2. **Accounts / Auth** — JWT auth, RBAC, user/role management, login brute-force guard, demo seed
3. **Masters** — Stores, Brands, Seasons, GSTINs, GstSlabs (date-effective), SKUs, Categories, CategoryMargin
4. **Vendors / Bookings** — Vendor management, multi-store booking orders, commercial models (Outright/Correction/SOR/Consignment)
5. **Inbound / GRN** — Goods Receipt Notes, branded/non-branded `kind` discriminator
6. **PT Mapper** — Brand PT file upload/parse/mapping (9 profiles), non-brand PT authoring, learning engine, pricing engine
7. **Stock Ledger** — Stock movements, on-hand tracking, location-aware posting
8. **Financial Ledger** — Value GL (balanced double-entry via kernel `post_entries`), vendor/cash subledgers unified with GL control accounts (F1 hardening), books health/trial balance
9. **Files** — File upload support
10. **AI Agents** — Gemini integration (stubbed, not active)

### Not Yet Built
11. **Selling / POS** — Sale document, POS integration (Ten Software adapter)
12. **Outbound** — Transfers, returns to brands, EOSS/V-flip, write-offs
13. **Offers / Discounts** — Offer rulebook, brand-specific discounts, markdown ladder
14. **Payments / Settlement** — Vendor payment lifecycle, approval routing, bank reconciliation, cash audit
15. **Tally Sync** — XML voucher export, nightly auto-sync
16. **Analytics / Intelligence** — Dashboards, profitability, dead stock, forecasting
17. **Controls** — Exception queue, reconciliation engine, approvals, audit trail
18. **Stock Counting** — Count sessions, book vs counted
19. **HR / Workforce (WAPCS)** — Attendance, payroll, employee management

## Sprint Plan (Locked Order)

| Sprint | Scope | Status |
|--------|-------|--------|
| **Sprint 0** | Bug fixes + local dev environment setup | **CURRENT** |
| Sprint 1 | Outbound (transfers, returns) | Planned |
| Sprint 2 | Offers / Discounts | Planned |
| Sprint 3 | Analytics / Reports | Planned |
| Sprint 4 | HR / Attendance | Planned |
| Sprint 5 | Controls | Planned |
| Sprint 6 | Tally Sync | Planned |
| Sprint 7 | Selling + POS (combined; waiting on client design) | Planned |
| Sprint 8 | Payments / Settlement | Planned |

## Sprint 0 Status
- [x] PostgreSQL 15 installed and running
- [x] All Python deps installed (Django 5.1, DRF, etc.)
- [x] Frontend deps installed (Vite, React, TypeScript)
- [x] Migrations applied (67 migrations)
- [x] Seed data loaded (foundation + PT mapper)
- [x] Backend + frontend boot clean
- [x] Full test suite: 358 passed, 0 failed, 1 skipped
- [x] Cookie auth bug fixed (JWT_COOKIE_SECURE=0 for local HTTP)
- [x] `/api/schema/` OpenAPI endpoint live (200 OK)
- [x] Finledger double-entry verified working (F1 hardening was already complete)
- [x] PRD.md, test_credentials.md, auth_testing.md written
