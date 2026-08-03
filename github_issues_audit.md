# GitHub Issues Audit Report

**Repository:** [bruhanand/KDPS](https://github.com/bruhanand/KDPS)  
**Audit Date:** August 3, 2026  
**Scope:** All Non-PRD GitHub Issues (Excluding issues labeled `PRD`)

---

## Executive Summary

| Category | Count | Issues |
| :--- | :---: | :--- |
| **Total Non-PRD Issues Audited** | **23** | #73, #77, #79, #105, #155, #158, #168, #190, #192, #198, #200, #205, #215, #220, #224, #234, #236, #251, #252, #256, #257, #262, #274 |
| **Problems Still Exist (Active / Open)** | **18** | #73, #77, #79, #105, #155, #168, #190, #192, #198, #200, #215, #220, #224, #234, #236, #257, #262, #274 |
| **Resolved in Codebase (Fixed / Obsolete)** | **5** | #158, #205, #251, #252, #256 |
| **Excluded (PRD Labeled)** | **6** | #67, #84, #96, #104, #120, #127 |

---

## Detailed Audit Findings

### 1. Active Issues (Problems Still Exist in Codebase)

#### [#73](https://github.com/bruhanand/KDPS/issues/73) — Outbound slice 6: warehouse distribution allocation grid
- **Labels:** `enhancement`, `ready-for-human`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Unimplemented Feature)**
- **Findings:** Slice 6 of the Outbound PRD (#67) requires a warehouse distribution allocation grid for allocating stock by style across destination stores. Inspection confirms this allocation grid UI and API contract remain unbuilt.

#### [#77](https://github.com/bruhanand/KDPS/issues/77) — Outbound slice 9: alerts job — in-transit aging + return-window 30/15/7
- **Labels:** `enhancement`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Unimplemented Feature)**
- **Findings:** Slice 9 of Outbound PRD (#67) requires a shared background alerts job for in-transit aging and return-window countdowns. Blocked by return-window features (#75); no background scheduled alert mechanism exists yet.

#### [#79](https://github.com/bruhanand/KDPS/issues/79) — Outbound slice 12: role-based landing + outbound navigation rework
- **Labels:** `enhancement`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Unimplemented Feature)**
- **Findings:** Navigation rework inside outbound sections (Transfer, Stock Count, Return to Brand) depends on slices #71–#76. The screen map and section tab structures remain incomplete.

#### [#105](https://github.com/bruhanand/KDPS/issues/105) — Fold Write-off into Stock Adjustment — one correction document, reason-coded
- **Labels:** `enhancement`, `ready-for-human`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** `WriteOff` model (`app/backend/outbound/models.py`), views (`views.py`), URLs (`urls.py`), and frontend pages (`app/frontend/src/pages/OutboundWriteoffs.tsx`) still exist as a separate document type rather than being folded into `StockAdjustment`.

#### [#155](https://github.com/bruhanand/KDPS/issues/155) — Stock screens show money as plain numbers, not Indian format
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** Code inspection of [StockLedger.tsx](file:///Users/anand/Code/KDPS/app/frontend/src/pages/StockLedger.tsx#L76) (line 76: `{ summary?.net_value_rupees ?? "0.00" }` and line 164: `{ e.value_rupees }`) confirms rupee amounts render as raw unformatted decimal strings without Indian Lakh/Crore grouping or the `<Money />` component.

#### [#168](https://github.com/bruhanand/KDPS/issues/168) — Scanning the same new barcode rapidly duplicates its row on the scan screen
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** In [ScanScreen.tsx](file:///Users/anand/Code/KDPS/app/frontend/src/components/ScanScreen.tsx#L190-L199), lines 190–199 check whether a barcode exists in `lines` state *before* the async `lookup(code)` returns. Rapid sub-second scans trigger concurrent lookups that both append the item to `lines`, creating duplicate rows.

#### [#190](https://github.com/bruhanand/KDPS/issues/190) — POS: printer spike — browser to thermal receipt printing
- **Labels:** `ready-for-human`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Unimplemented Hardware Spike)**
- **Findings:** Thermal receipt printing integration spike direct from Chrome / PWA to thermal printers remains an open requirement.

#### [#192](https://github.com/bruhanand/KDPS/issues/192) — The generated API client is about a thousand lines out of date
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** Running `manage.py spectacular` and type generator produces extensive diffs against [api-schema.ts](file:///Users/anand/Code/KDPS/app/frontend/src/lib/api-schema.ts), confirming the generated API types are out of sync with backend DRF schemas.

#### [#198](https://github.com/bruhanand/KDPS/issues/198) — Ledger pages show raw rupee strings instead of Indian-grouped money
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** Code inspection of [VendorLedger.tsx](file:///Users/anand/Code/KDPS/app/frontend/src/pages/VendorLedger.tsx#L141) (line 141: `{balances?.total_payable_rupees ?? "0.00"}`) and Cash Ledger confirms raw string rendering instead of using the `<Money />` component.

#### [#200](https://github.com/bruhanand/KDPS/issues/200) — Store manager cannot approve anything at the till
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open Policy / Access Issue)**
- **Findings:** In the permissions floor and access matrix, store managers and cashiers carry identical rights on Sell (no `sell:approve` permission for store managers at the counter).

#### [#215](https://github.com/bruhanand/KDPS/issues/215) — POS: label the Dashboard's collections card with the till's last sync time
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Unimplemented Feature)**
- **Findings:** Dashboard collections card does not display the till's last sync time (`syncedAt`) for store logins.

#### [#220](https://github.com/bruhanand/KDPS/issues/220) — Cancelling a sale or a return leaves its credit note live and its ledger legs standing
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open Integrity Issue)**
- **Findings:** Document cancellation FSM only flips `docstatus` to `cancelled`; it does not issue reversing GL/stock ledger legs or revoke issued credit notes.

#### [#224](https://github.com/bruhanand/KDPS/issues/224) — Re-running the seed silently undoes an access change two administrators agreed
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open Policy Issue)**
- **Findings:** Running `seed_foundation` resets all role access permissions back to foundation sheet defaults, silently overwriting live administrative role configuration changes.

#### [#234](https://github.com/bruhanand/KDPS/issues/234) — Booking list shows every store's bookings to any store login
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** In [vendors/views.py](file:///Users/anand/Code/KDPS/app/backend/vendors/views.py#L171), `BookingListCreateView.get_queryset` filters only by status, brand, season, and search text — no store-scope filter is applied.

#### [#236](https://github.com/bruhanand/KDPS/issues/236) — Dashboard: finledger/health fires and 403s for brand_manager (Books Health widget)
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** [Home.tsx](file:///Users/anand/Code/KDPS/app/frontend/src/pages/Home.tsx#L172) line 172 unconditionally calls `api.get("/finledger/health")` on dashboard load without checking whether the logged-in role has financial ledger capabilities, causing 403 HTTP errors for roles like `brand_manager`.

#### [#257](https://github.com/bruhanand/KDPS/issues/257) — Billing scan box can silently drop a scan under rapid back-to-back scans
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** Rapid sub-second barcode scans in `useScanBox.ts` and `lookup.ts` can drop scans due to state update latency during back-to-back input events.

#### [#262](https://github.com/bruhanand/KDPS/issues/262) — A mistyped GSTIN still prints a tax split on the bill
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Problem Still Exists (Open in Codebase)**
- **Findings:** In [gstin.ts](file:///Users/anand/Code/KDPS/app/frontend/src/till/gstin.ts#L47), `taxKindFor` derives CGST/SGST vs IGST tax split based purely on state code characters, even when `describeGstin` reports the GSTIN is malformed.

#### [#274](https://github.com/bruhanand/KDPS/issues/274) — POS redesign 9/9: the doc pass (customer into the corpus, superseded rulings rewritten)
- **Labels:** `ready-for-human`
- **GitHub State:** `OPEN`
- **Codebase Status:** 🔴 **Task Still Exists (In Progress / Open)**
- **Findings:** Document reconciliation for the POS redesign (incorporating Customer into D8/D10 specs and rewriting superseded rulings) remains an open documentation task.

---

### 2. Resolved Issues (Problems No Longer Exist in Codebase)

#### [#158](https://github.com/bruhanand/KDPS/issues/158) — The whole-system demo seed stops halfway: a warehouse person cannot post value
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN` (Should be Closed)
- **Codebase Status:** 🟢 **RESOLVED in Codebase**
- **Verification Evidence:** Fixed in commit `6fa5186` (`seed_demo_data: PT posting segregation-of-duties...`). Line 853 in `seed_demo_data.py` posts PTs as `accounts1` user. Verification test running `./app/backend/.venv/bin/python app/backend/manage.py seed_demo_data` completed cleanly with exit code 0.

#### [#205](https://github.com/bruhanand/KDPS/issues/205) — seed_demo_data crashes: a store-scoped user cannot post the demo PT
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN` (Should be Closed)
- **Codebase Status:** 🟢 **RESOLVED in Codebase**
- **Verification Evidence:** Resolved alongside #158. `seed_demo_data` executes cleanly end-to-end without posting floor errors.

#### [#251](https://github.com/bruhanand/KDPS/issues/251) — seed_demo_data: RTV seeding fails, rolling back all demo data
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN` (Should be Closed)
- **Codebase Status:** 🟢 **RESOLVED in Codebase**
- **Verification Evidence:** Fixed in commit `6fa5186`. `seed_demo_data` completes RTV seeding (`RTV 26-27/DEO/RTV/3 @ DEO: defective, posted`) without rolling back.

#### [#252](https://github.com/bruhanand/KDPS/issues/252) — seed_demo_data: RTV and V-flip steps crash on unpriced SKUs, rolling back the whole seed
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN` (Should be Closed)
- **Codebase Status:** 🟢 **RESOLVED in Codebase**
- **Verification Evidence:** Fixed in commit `6fa5186`. Both RTV and V-flip seed steps execute successfully during `seed_demo_data`.

#### [#256](https://github.com/bruhanand/KDPS/issues/256) — seed_demo_data fails on a fresh DB: RTV/V-flip seed steps price SKUs at stores that never received them
- **Labels:** `needs-triage`
- **GitHub State:** `OPEN` (Should be Closed)
- **Codebase Status:** 🟢 **RESOLVED in Codebase**
- **Verification Evidence:** Fixed in commit `6fa5186`. Verified on clean DB setup; `seed_demo_data` seeds stock correctly before creating RTV/V-flip entries.

---

### 3. Excluded PRD Issues (Skipped per Instructions)

- [#67](https://github.com/bruhanand/KDPS/issues/67): Outbound module UX rework — transfers, returns, counting, approvals (PRD)
- [#84](https://github.com/bruhanand/KDPS/issues/84): Navigation & shell redesign — section map, stubs, sidebar & role-based landing (PRD)
- [#96](https://github.com/bruhanand/KDPS/issues/96): Daily / More bifurcation & navigation ordering (PRD)
- [#104](https://github.com/bruhanand/KDPS/issues/104): Roles & Access — nine roles, four unconfigurable floors, one approval inbox (PRD)
- [#120](https://github.com/bruhanand/KDPS/issues/120): Supplier Payments & Claims — credit-note lifecycle, settlement engine, payments UI (PRD)
- [#127](https://github.com/bruhanand/KDPS/issues/127): Stock adjustment & write-off — valuation, approval floors, maker-checker (PRD)

---
*Report generated by Antigravity AI Code Auditor.*
