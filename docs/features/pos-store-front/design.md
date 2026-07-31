# pos-store-front - technical design (Phase 3)

Input: the approved `feature-analysis.md`, `grill-decisions.md`, `api-contract.md`, `db-design.md`.
Money slice, so this phase is mandatory.
Anand's Phase-3 rulings folded in: no F-key shortcuts (everything cursor-selectable), the Sell screen is a normal design-consistent page (no full-screen mode for now), RetailJI contributes skeleton placement only.

## Summary

The feature adds two Django apps (`sell` - the Sale/Return/CreditNote documents and their postings; `offers` - the rulebook) plus a thin read-only aggregator (`storefront` - dashboard and cash summary), extends four existing apps (`core` external numbering, `approvals` routes, `outbound` request fields, `accounts` matrix editor + till PIN), and adds one genuinely new frontend layer: `src/till/`, the offline spine (Dexie/IndexedDB local dataset, durable bill queue, till-owned numbering, sync engine, print adapter), on which the Sell screens sit as ordinary shell pages built from the existing hand-rolled UI kit.
The server accept pipeline is the money heart: validate, resolve, accept the till's number, post two balanced GL events, flag instead of block.
Everything follows an existing traced pattern (Grn/StoreTransfer for documents, `outbound/posting.py` for posting services, ScanScreen's wedge capture for scanning, `?tab=` for tabs, navConfig for nav/guards); the only new architecture is the till layer, which is the point of the feature.

## Component breakdown

### Backend - new app `sell`

- `models.py` - `Sale`, `SaleLine`, `SaleTender`, `Return`, `ReturnLine`, `CreditNote`, `CreditNoteRedemption`, `Salesman`, `HeldBill`, `ContinuityFlag`, `DeferredCosting`, `IrnQueueItem`, exactly per `db-design.md`. `Sale`/`Return`/`CreditNote` subclass `core.Document` with `series_lookup()` returning `SAL`/`SRT`/`CRN`; `GenericRelation("approvals.Approval")` on `Return`.
- `services/accept.py` - the sale acceptance pipeline (contract steps 1-13), one `@transaction.atomic` entry `accept_sale(payload, actor) -> AcceptResult`. Pure orchestration; each step a named function.
- `services/posting.py` - `post_sale_money(sale)` (event A) and `post_sale_costs(sale, lines)` (event B), building `Leg` lists and calling `core.posting.post_entries`; writes `StockLedgerEntry(kind=sale_out/sale_return_in)` and `CashLedgerEntry` projection rows in the same transaction (the `outbound/posting.py` shape).
- `services/returns.py` - plain-return pipeline + credit-note issue; `services/creditnotes.py` - redemption/expiry.
- `services/recompute.py` - the advisory server-side reprice (GST from dated slab, offer resolution) writing `ContinuityFlag` rows; also the nightly applied-vs-rulebook sweep (management command `sell_daily_check`).
- `services/costing_sweep.py` - `sweep_deferred(barcode, season)` called from a signal/hook where PT posting creates or prices a Cohort; posts event B for waiting lines.
- `services/dataset.py` - snapshot/delta builder for `GET /api/sell/dataset` (per-section `updated_at > since`).
- `views.py` / `urls.py` / `serializers.py` / `permissions.py` - DRF `APIView`s, explicit paths, `require_section("sell", ...)` gates: `DatasetView`, `SaleCreateView`, `SaleListView`, `SaleDetailView`, `RegisterView`, `RegisterHandoverView`, `HeldBillsView`, `ReturnCreateView`.
- `maker_checker` wiring: `KINDS` entry + `ApprovalPolicy` row for the plain return (kind `sell_return`), self-clearing at manager approval - the manager's tap IS the approval, recorded through the existing approvals machinery rather than a bespoke override table. The over-cap discount override on a Sale stays an on-document evidence field (`override_by`) because it is verified at the till offline and the bill cannot wait for a server approval round-trip; the daily check audits it.

### Backend - new app `offers`

- `models.py` - `Offer` per `db-design.md`.
- `resolution.py` - the pure, deterministic three-layer engine (`resolve(cart, offers) -> per-line evidence`); no ORM imports, testable against the shared golden vectors.
- `views.py` - list (view-gated, store-filtered) + create/update (manage-gated, live rules end-and-replace, never edit in place).
- `tests/vectors/*.json` - golden carts with expected per-line outcomes; the same files are consumed by the frontend port's vitest suite. Any divergence between the two engines is a red build, which is what makes "prices the same at till and server" a tested property instead of a hope.

### Backend - new app `storefront` (read-only aggregator)

- `views.py` - `DashboardView`, `CashSummaryView`. No models, no writes; imports other apps' models read-only, the same registered import-linter seam the `search` app already has. This keeps `sell` free of cross-app imports (ADR-0002).
- `masters` gains `StoreTarget` + a small `StoreTargetView` (GET/PUT) since targets are a master, not storefront state.

### Backend - changed apps

- `core/documents.py` - `VoucherSeries.accept_external(...)` (kernel change, supervised, anti-cheat tests: exactly-once, hole-flag, SAL-only).
- `core/posting.py` - the registered SAL/SRT floor exception (account allow-list + doc-type check + written reason).
- `core/gl.py` - the seven new `GLAccount` codes.
- `approvals` - `ApprovalRoute` model, `Approval.route/current_step`, route progression + later-step short-circuit in `services.py`; seed for `stock_request`.
- `outbound` - `StockRequest.expected_arrival_at`, `.source`; create view attaches the route.
- `accounts` - `AccessMatrixView` (GET) + `RoleAccessView` (PUT) with the `FLOORS` constant; `User.till_pin_hash`; `/me` untouched; the two RBAC contract tests re-pointed at the stored matrix.
- `stockledger` / `finledger` - enum/choices extensions only; projection maintenance for the two new kinds follows the existing in-transaction pattern.

### Frontend - the till layer (`src/till/`, new)

- `db.ts` - Dexie schema: `items`, `stock`, `offers`, `creditNotes`, `salesmen`, `managers`, `gstSlabs`, `meta` (cursor, fy, nextSeq, storageSentinel), `queue` (outbound bills, ordered), `held`. One database per store code.
- `sync.ts` - down: pull `/api/sell/dataset` on app-online + a 5-minute interval + manual "sync now"; up: drain `queue` FIFO on online-event + 60s interval, single-flight, exponential backoff capped at 60s. Terminal 4xx responses (contract's 400/409/422 codes) stop the queue and surface a store-facing exception card; network errors retry forever (F1/F2).
- `numbering.ts` - `nextBillNumber()` inside the same Dexie transaction that enqueues the bill: read `meta.nextSeq`, stamp, increment, all-or-nothing. FY boundary computed from the Indian-FY helper's rules, mirrored.
- `pricing.ts` - MRP-inclusive back-calculation (half-up + rounding line) and the GST slab pick; `offers.ts` - the TS port of `resolution.py`, tested against the same golden vectors.
- `print.ts` - `PrintAdapter` interface with a `BrowserPrintAdapter` v1 (receipt HTML via hidden iframe + `window.print`); the hardware spike swaps in an ESC/POS adapter behind the same interface without touching callers. Printer-check = adapter `probe()`; on failure the bill still saves and the screen says so (G2).
- `guard.ts` - till init: `navigator.storage.persist()`, storage-sentinel check (sentinel missing -> red sync light, billing blocked until re-bootstrap + `GET /api/sell/register` reconciliation), single-till lock via `navigator.locks` so a second tab cannot double-write the counter.
  **As built (#189), three things.** The sentinel is a pair of `localStorage` keys rather than db-design's `meta` row - a marker inside the database cannot survive the database being thrown away, which is the one event it exists to detect - and the second key is what stops a page reload lifting the block, since the first sync after a loss refills `meta`.
  The re-bootstrap is a **button**, not something the boot sync does on its own: recovering moves the number the next customer's bill will carry, and a counter that reset itself quietly is the thing the red light is there to prevent.
  The lock is advisory over an invariant IndexedDB already enforces inside `commitBill`'s transaction, so a browser without `navigator.locks` (or one whose lock manager throws) counts as holding it - refusing to bill because an advisory API is missing would turn a nicety into a lost day's trade.
- `TillProvider.tsx` - React context exposing till state (sync status, pending count, dataset ready) via `useSyncExternalStore`; mounted only under `/sell` routes.

### Frontend - screens (all normal shell pages, existing UI kit, `data-testid` throughout)

- `pages/sell/Billing.tsx` - the skeleton placement per D10 §4: scan/type-to-search box top-right (wedge capture via a `useWedgeScan` hook extracted from ScanScreen's sink + focus-keeper; ScanScreen itself is not reused - it is a full-screen count surface, wrong shape here), line grid centre (`.lines-table`), payment panel right (tender rows, split, tendered-cash/change), customer strip below, totals with "you saved", action row of plain buttons (Save & Print with lock+spinner, Print/Reprint, Hold Bill, Search, New Bill). **No keyboard shortcuts; every action is a visible button.** Salesman picker defaults to last-picked (one click to change). Over-cap discount opens the manager-PIN modal (verified against the cached hash offline). Sync light sits in the page header (green/amber+count/red), not a modified top bar.
- `pages/sell/ReturnsExchange.tsx` - find original bill (local first, server when online), pick lines, reason + condition; exchange flows into the current bill; plain return is server-only and disabled offline with an explanatory note.
- `pages/sell/CustomerSearch.tsx` - by mobile/name/bill number; read-only detail + Reprint. No edit affordance exists.
- `pages/Home.tsx` (rebuilt) - the Dashboard cards from `GET /api/store/dashboard` per the contract shape; quick-actions row; held-bills count links into Billing's hold list; manager row rendered only when present in the payload.
- `pages/CrossStoreSearch.tsx` - `GET /api/stock/availability` results size-by-size; "Request this" posts the StockRequest with `source: cross_store_search`.
- `pages/setup/AccessMatrix.tsx` - the roles x sections grid, floor cells greyed with reasons, per-cell save via the PUT.
- `pages/MasterPages.tsx` gains Store Targets (month x store grid, money-manage gated).
- `routes.tsx` + `navConfig.ts` - replace the three `planned:true` sell items with built routes; STORE_LAYOUT already places sell; nav/route/planned-pages tests updated in the same commit (they fail otherwise by design).
- `vite.config.ts` - add `vite-plugin-pwa` (app-shell precache only; API traffic is never SW-cached - the till reads IndexedDB, not stale HTTP).
  **As built (#189):** the options live in `src/pwa/config.ts` rather than inline, because "the service worker never caches an API response" is a money rule and a money rule wants a test - and a config object a test can import is the only seam a bundler plugin offers.
  `runtimeCaching: []`, a precache globbed by file extension, and `navigateFallbackDenylist: [/^\/api/]` so a navigation-shaped API request is never answered with the app shell.

## Request flow (the three that matter)

**Clean offline sale.** Scan -> `useWedgeScan` -> local resolve from `items` (+ stock readout, oldest-season default, one-tap season ask only when truly ambiguous) -> line appended, salesman defaulted, offers auto-applied by `offers.ts`, GST back-calculated by `pricing.ts` -> tender split entered -> Save & Print -> one Dexie transaction: {bill assembled with `idempotency_uuid` + `nextBillNumber()`, local `stock` decremented, `queue` append} -> `PrintAdapter.print()` -> UI resets for the next customer.
`sync.ts` drains: `POST /api/sell/sales` -> server `accept_sale` pipeline (contract steps 1-13) -> `accept_external` mints the same number -> stock ledger + GL event A + event B -> 201; replay of the same uuid returns 200 identical.
Flags raised server-side (hole, offer mismatch, sold-before-inward) surface on the Dashboard action queue, never at the counter mid-sale.

**Sold-before-inward line.** Scan finds nothing locally -> "not in system" row with manual description + MRP entry -> bill proceeds and prints -> server marks the line deferred, creates `DeferredCosting(waiting)` -> Dashboard shows "1 bill waiting on inward" -> GRN/PT later prices the cohort -> `sweep_deferred` posts event B linked `against_voucher` to the Sale -> flag closes.

**Cross-store request.** Cross-store search -> request raised -> `ApprovalRoute(stock_request)` step 1 (own store manager approves in Approvals) -> step 2 Operations Head (or Ops Head short-circuits both) -> approved request spawns the normal transfer (existing machinery) -> requesting store watches Transfer/In-Transit and receives by the existing scan flow.

## Error handling approach

- Server: contract error codes in `{"error", "code"}` bodies; every accept-pipeline refusal is one of the six 4xx codes; everything the business can absorb is a `ContinuityFlag`, not an error (flag-never-block is the pipeline's default branch).
- Till queue: network failure -> silent retry with backoff (sync light amber + count); terminal 4xx -> queue halts, a red exception card names the bill and the reason, billing continues on the next number (the failed bill needs a human - typically `BILL_NO_TAKEN` after a mis-handover). Nothing is ever dropped from the queue silently.
- UI: existing conventions - `apiErrorMessage`, `.warn-note` / `.login-error` blocks, buttons lock + spin while awaiting (G3).
- Printing failure: bill saves regardless; banner + one-tap Reprint (G2).

## Assumptions

1. Pilot store and printer hardware are open items (spike pending); `PrintAdapter` isolates the outcome.
2. Day-close/store open-close (I3) is out; cash summary is read-only; held-bill "expire at day close" is implemented as expire-at-local-midnight-prompt until I3 defines day close properly.
3. Tally export of sales vouchers belongs to D6/Tally-sync; this feature records everything the catalog's daily-consolidated voucher needs (per-slab, per-HSN, B2B detail) but writes no Tally file.
4. The five CA gates stand; SOR accrual and credit-note expiry post as designed but the alpha handles no live money until the rulings land.
5. Salesman master is till-facing v1; HRMS will reparent it later (shaped for a FK, per `db-design.md`).
6. JWT-in-localStorage stays an accepted alpha caveat (already on record); the dataset endpoint never carries cost/margin, asserted by test.
7. One till per store is enforced socially + by the `navigator.locks` single-tab guard + the `BILL_NO_TAKEN` server refusal; a second *machine* is out of scope until the invariant changes.
