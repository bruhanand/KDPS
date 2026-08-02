# Billing screen revamp - Phase 3: technical design

> **Amended 2 Aug 2026.** Issue #243's round-1 review found the payment + customer rail taller than the space available at 1366×768 - "the line list is the only `overflow-y: auto`" (line below) was not achievable without trimming the two rail cards, which is #246's and #249's scope, not #243's. Anand ruled: the rail gets its own **temporary** `overflow-y: auto` so nothing is ever unreachable (flag-don't-block); #246/#249 must shrink the cards until that scrollbar disappears, restoring the single-scroll rule this doc describes. Read **`grill-decisions.md` § Amendments - 2 August 2026** first; where the two disagree, the amendment wins.

## Summary

The Billing route becomes a fixed-height frame that fills the content area exactly once - top strip, work area, pinned footer - with the line list as the only scrolling region.
The cart machinery stays what it is (pure functions over an immutable `Cart` in `src/till/cart.ts`, thin `setCart` closures in the page); the revamp wraps it with three new till-local capabilities - continuous draft autosave, an in-memory undo stack, scan sounds - and rebuilds the two rail cards (payment, customer) on new pure helpers in `tender.ts` and a new synced `customers` table.
UPI gets a charge card driven by a `PaymentAdapter` interface mirroring the existing `PrintAdapter`, with a mock as the only implementation until the hardware slice.
Server-side the feature is three surgical changes: a `masters.Customer` model feeding the dataset delta, the UPI stamp columns on `SaleTender` validated in the accept pipeline plus a post-commit customer upsert, and the confirmed/manual split in the cash summary.
Nothing posts; no ledger is touched.

## Component breakdown

### Backend (Django)

**`masters` - new**

- `Customer` model (per db-design): `TimeStampedModel`, `mobile` unique, `name`, `gstin`; `updated_at` index `masters_customer_synced_idx` following the `Sku`/`Cohort` watermark convention.
- Migration + data migration backfilling from `sell_sale.customer_mobile` (newest name wins), idempotent on mobile.
- No masters serializer/view: the till is the only consumer and reads it through the dataset (same as `Store`/`Gstin` today).

**`sell` - changed**

- `SaleTender`: `upi_state`, `upi_reference` columns; migration backfills `upi_state='manual'` on existing UPI rows, then adds the three check constraints (per db-design).
- `services/dataset.py`: new `_customers(sync)` builder - all stores (deliberately no store filter, grill Q6), delta clause `Q(updated_at__gt=sync.from_moment)` copied from `_items`, full list on bootstrap; wired into `build_dataset` as `"customers"`. No `deleted` channel (rows never die in v1).
- `services/accept.py`:
  - tender validation (contract §2 step 2): the four `upi_state`/`upi_reference` pairing rules, refused as `VALIDATION` with the house `first_message` style;
  - `_apply_tenders` persists the two new fields;
  - new `_upsert_customer(sale)` registered via `transaction.on_commit` - digits-normalised mobile, get-or-create, latest-non-blank-name-wins, gstin fill; whole body in try/except that logs and swallows (Rule 5: the printed bill is a fact, master data never refuses it).
- `storefront/day.py`: one added aggregation - UPI tenders grouped by `upi_state` into `upi_split {confirmed, manual}`, same queryset as the mode sums; surfaced by `CashSummaryView`.

### Frontend (PWA)

**The frame (`pages/sell/Billing.tsx` + `Billing.css`, restructured)**

- `Billing.tsx` (~2000 lines) splits: the route keeps `Counter` (state, wiring, top strip, footer) and the big pieces move to `pages/sell/billing/` - `BillGrid.tsx` (Lines + cells), `PaymentCard.tsx`, `CustomerCard.tsx`, `UpiCharge.tsx`, `HeldBills.tsx` (moved in). Pure mechanical extraction; no behaviour moves in the same commit as the layout change.
- The frame: `.bill-page { height: calc(100dvh - var(--topbar-h)); display: grid; grid-template-rows: auto auto 1fr auto; overflow: hidden }` - rows are PageHeader, the one-line alert strip, the work area, the footer. The work area is `grid-template-columns: minmax(0,1fr) 340px; min-height: 0`; the line list inside it is the only `overflow-y: auto`, with `position: sticky` column headers. This respects the AppShell contract (".content is the only box that scrolls") by making the page exactly content-height so `.content` never scrolls on this route; below 1280px a media query lets the bands stack and `.content` scroll again (grill G-2).
- Top strip = the existing `PageHeader` row: `lead` stays the bill number + "Draft · saved" indicator; `actions` carries SyncLight, the ScanBox, and the four lifecycle buttons (Find a bill, Held bills (n), Hold bill, New bill).
- All stacked banners collapse into the single alert row; the second-window/storage-lost block keeps its current full-takeover behaviour (Rule 5 hard case, unchanged). **Amended (round-2 review, #243):** keying in from paper is a third exception, for the same reason - its date field and "Not this one" exit are controls, not banner text, so they render off `paper !== null` in their own band instead of taking turns on the alert line; only `blocked`, `loading`, `no-price-list`, `print-problem`, `note`, `gift` and `holds-due` compete for that one line now.

**Floating prompts (grill G-4)**

- `Suggestions`, `NotInSystem`, and the new customer typeahead all render through the existing `src/shell/usePositionedPopover.ts` (portal, anchored to the scan box / mobile field, closes on outside-click/Escape-free - note: the hook's Escape close is fine, it is not a keyboard *action*).
- The season question stays inline in the line (unchanged).

**Cart behaviour (`src/till/cart.ts` - changed)**

- `addPiece` gains the increment rule (grill Q1): before appending, find a live line with the same resolved `(barcode, season)` that is not a manual/off-the-tag line - if found, return the cart with that line's `qty + 1` (salesman, discount, rate untouched); else append as today. The `CartLine.key` doc comment updates to match.

**Autosave (`src/till/draft.ts` - new)**

- Dexie `version(3).stores({ customers: "mobile", draft: "" })` - additive only, per the version(2) precedent.
- The draft row (fixed key `"current"`): `{cart, customer: {name, mobile, gstin}, paper, savedAt}` - everything needed to restore mid-scan.
- Write-through: `Counter` funnels every `setCart`/customer-field change through one `persistDraft()` (per-action; the objects are small and already immutable). Cleared on commit success, New bill, and Hold (hold moves it to `held` as today).
- Restore on mount: read via `engine.db` (never a second `TillDb`), guarded by the `current`-flag race pattern from `useTillWorld` - a read that loses the StrictMode/remount race is dropped, not applied.

**Undo (`src/till/undo.ts` - new)**

- In-memory bounded stack (50) of `Cart` snapshots; push on every cart mutator, pop on the Undo button; cleared with the draft.
- Deliberately not persisted (grill Q2-Q3): after a crash the draft restores, undo history does not.
- No redo.

**Payment card (`pages/sell/billing/PaymentCard.tsx` + `src/till/tender.ts` - changed)**

- `tender.ts` gains two pure helpers beside `splitOf`: `prefillFor(split, mode)` (the remaining `balance_paise` a tapped empty box adopts) and `cashChips(balance_paise)` → `[exact, next ₹100 multiple, next ₹500 multiple]`, deduped, empty when balance ≤ 0.
- Interaction preserves the existing semantics: `payment.cash_paise === null` still means "cash takes the rest"; focusing a box materialises the prefill as an explicit value; typing over it splits. `whyPaymentCannotClose` is untouched.
- One balance line renders from `splitOf`: `balance_paise > 0` → red "Still to pay"; cash over → green "Change to give" (from the existing `change_paise`).
- The exchange-owed swap, credit-note rows, and the Authorised/ManagerPin path move into `PaymentCard` unchanged.

**UPI charge (`src/till/payment.ts` + `pages/sell/billing/UpiCharge.tsx` - new)**

- `PaymentAdapter` interface mirroring `PrintAdapter`: `charge(amount_paise): AsyncIterable<ChargeState>` + `checkStatus()` + `cancel()`, outcome objects `{state, reference?, reason?}` with `state ∈ generating | awaiting | success | failed | unknown`.
- `mockPaymentAdapter`: walks generating → awaiting on a timer, resolves to `failed`/`unknown` only - **it never emits `success`**, so a `confirmed` stamp cannot exist before real hardware (contract §2). The card's Awaiting state shows the QR placeholder, amount, Cancel and Check-status buttons.
- The adapter is threaded into `Counter` as an explicit prop/param (the print adapter's static-import style is noted, but payment needs the mock swappable in tests, so it is passed, not imported, at the one call site).
- Outcome → tender row: `success` writes `upi_state: "confirmed"` + reference; everything else leaves the cashier typing a manual amount → `upi_state: "manual"`. The wire shape change lands in `toTenders`.

**Customer card (`pages/sell/billing/CustomerCard.tsx` + `src/till/lookup.ts` - changed)**

- `lookup.ts` gains `searchCustomers(db, prefix)`: Dexie prefix scan on the `customers` table's `mobile` key plus in-memory name filter, top 5.
- Typeahead popover under the mobile field; pick fills name+mobile (and gstin when the row has one); unknown number shows the inline "new customer" affordance (name only).
- GSTIN moves behind the "Business bill?" disclosure; its validation/tax-kind behaviour is untouched.
- `sync.ts applyDataset` adds the customers block using the items pattern minus deletions: `clear()` on `full`, unconditional `bulkPut` (upsert by mobile) every pull. `useTillWorld` and `TillCounts` gain the table read/count.

**Polish**

- `src/till/sounds.ts` (new): two bundled samples, `tick()` on a landed scan, `buzz()` on a failed resolve / not-in-system; respects a new `META.muted` flag (`writeMeta`), toggled from a new small card on the Till & Sync page next to CounterPin; `TillEngine.setMuted()` + snapshot exposure follow the `rememberSalesman` precedent exactly.
- GST badge (grill Q7): `BillGrid` drops the two GST columns for a per-line rate badge; the footer's "Tax incl." figure becomes a click target opening a popover (same `usePositionedPopover`) with the per-rate + CGST/SGST-or-IGST breakup computed from the existing per-line GST math. Print untouched.
- Cash summary screen: the Money section's day view renders the `upi_split` beside the UPI tile.

## Request flow (the three that matter)

**Scan → line → draft.**
Scan resolves locally (`resolveScan`) → `takePiece` → `addPiece` increments-or-appends → `setCart` → undo push + `persistDraft()` (one Dexie put) → `tick()` → focus returns to the scan box.
Failure path: unresolved scan → `buzz()` → NotInSystem popover.
Nothing awaits the network; unchanged guarantee.

**Tender → Save & Print → accept → upsert.**
Tap a tender box → `prefillFor` fills the remainder → `splitOf` re-renders the balance line → Save & Print runs the existing commit (bill + queue in one IndexedDB transaction, print after) with tenders now carrying `upi_state`/`upi_reference` → queue sync POSTs to `/api/sell/sales` → accept validates the stamp pairings (step 2), writes tender rows (step 4), and on commit fires `_upsert_customer` (step 6, swallow-log) → the next dataset delta returns the new/refreshed customer row to every till.

**UPI charge (mock).**
Amount in the UPI row → "show QR" → `UpiCharge` consumes the adapter's state stream → Awaiting shows QR placeholder + Cancel + Check status → mock ends `failed`/`unknown` → cashier falls back to manual (stamp `manual`, no reference) or another tender.
The bill's commit path is identical in every outcome - the charge card only decides what lands in the tender row.

## Error handling

- Server: house `refusal_body` codes only - the four new refusals are all `VALIDATION` with precise messages; the upsert step has **no** error path by design (logged, swallowed, bill stands).
- Till: flag-never-block throughout - a failed draft write logs to console and the bill continues (the draft is a safety net, not a gate); a failed sound is ignored; adapter `unknown` is a visible state, never converted to `failed` on the till's own clock.
- The frame never hides a hard block: `till.blocked` (second window / storage lost) still replaces the whole work area.
- **Amended (round-2 review, #243):** the alert-strip precedence in `pickBillAlert` ranks `print-problem` ahead of `note`, since `save()` always sets the save-confirmation note before attempting to print - so a print failure never goes silent behind "Bill saved."
- **Amended (round-2 review, second pass, #243):** ranking `print-problem` above `note` is only safe because `printProblem` cannot outlive the bill it belongs to - `takePiece`/`takeUnknown` clear it on the next scan and `resumeHold` clears it before swapping in a held bill's cart, so `holdBill`'s and `resumeHold`'s own failure notes are never buried behind a stale printer banner from an earlier bill. A live (not stale) print problem still outranks `answerHold`'s note - keeping or letting go a held bill from the review list is independent of the open cart, so that conflict is a real one, not staleness; left as a residual (`deviations.md`).
- **Amended (round-6 correctness review, #243):** the scan float (`Suggestions`/`NotInSystem`) is portaled to `document.body`, so it structurally escapes the takeover unless gated explicitly - a scan could still run `applyScan -> takePiece`/`takeUnknown` and append to `cart.lines` with no grid on screen to show it. The portal now renders only when `!counterBlocked`, the same Rule 5 corollary already applied to the lifecycle buttons (`e58fcf9`) and the scan box itself (round-5).

## Assumptions made

1. Cash keeps its `null`-means-the-rest semantics; prefill materialises values, it does not re-derive them - so tender math tests stay valid and the day-close numbers cannot shift (the Phase 0 money-caveat stays dormant).
2. Rescan increment matches on resolved `(barcode, season)` and skips manual/off-the-tag lines; a piece needing a different salesman on the second unit is edited per line, as ruled.
3. Chip formula: exact + next ₹100 + next ₹500 multiples, deduped; refinable later (grill Q4).
4. No redo, undo depth 50, undo not persisted.
5. The customers table syncs without a deletion channel until a merge/cleanup flow exists (contract §1).
6. The mock adapter never emits success; `confirmed` therefore cannot reach the server until the hardware slice - enforced by construction, not by review.
7. `store-front-design.html` §4's region table is updated at closeout, not during the build (the exploration doc carries the agreed layout meanwhile).
8. The Billing.tsx split is mechanical extraction in its own commit before any behaviour change, so review diffs stay honest.
