# POS counter redesign - Phase 3: technical design

Drafted 2 Aug 2026 against `grill-decisions.md`, `api-contract.md`, `db-design.md`.

## Summary

The counter becomes a dark room the rest of the app never enters: while `/sell` is mounted, a `data-room="counter"` attribute on `<html>` re-values the existing design tokens to the design's warm near-black palette - which dresses the top bar and sidebar for free, because every shipped component already paints itself from tokens (the dark-mode precedent, applied a second time).
Inside the room, the Billing page keeps its state machinery (`cart.ts`, drafts, undo, holds, the accept queue) and swaps its shell: a bill bar replaces the PageHeader, a hero scan bar replaces the small box, the totals fold into the lines card, Save & Print moves to the rail's foot, and a finish overlay lands after every commit.
Return & exchange folds in as the bill bar's mode toggle, driven by the same parked-exchange machinery the separate screen used, plus three find-bill doors (scan the new receipt barcode, type the number, search by customer).
Money behaviour narrows per the grill: equal-or-up hard gate, absolute discount cap with the on-offer stacking dial, credit notes retired - each enforced in the till's own `guard`/`tender` layer from dataset dials, with the server's three new refusals as backstops.
Backend: one column, one migration, one tiny policy endpoint, three accept-pipeline changes, one route retired.

## Component breakdown

### Backend (Django, all in `sell` except the matrix note)

| Piece | New/changed | What |
|---|---|---|
| `SellPolicy.manual_discount_on_offer_lines` | new column | boolean, default false; model default for the cap moves 0 → 10.00 (per db-design, with the where-still-zero data migration) |
| `views.SellPolicyView` + `urls` `policy` | new | GET (`sell: view`) / PUT (`sell: manage`) per contract §1; serializer validates the two fields; percent as two-decimal string |
| `services/accept.py` | changed | step 3: `EXCHANGE_SHORT` on net < 0, `expected = net` (floor gone); step 6: `DISCOUNT_ON_OFFER_LINE` + `DISCOUNT_OVER_CAP`, override door removed; step 7: credit-note mode out of the serializer choices, recognition walk deleted; step 8 `_issue_change_note` deleted; `_authorised_kind` shrinks to the window kind |
| `services/dataset.py` | changed | `_policy()` gains the boolean; `credit_notes` + `deleted.credit_notes` sections and `_credit_notes()` removed |
| `views.ReturnCreateView` + route + `CanTakeReturns` | retired | models/history stay; `refunds.py` untouched (still reads both tables) |
| tests | changed | accept tests rewrite the override-discount and note-tender cases to the new refusals; dataset golden shapes drop the note sections; new policy-endpoint tests |

### Frontend - the room (new, slice 1)

- **`src/theme/counter.css`** (new): one `html[data-room="counter"]` block re-valuing the existing tokens (`--paper: #100D0B`, `--surface: #171310`, `--hairline: #2A231D`, `--ink: #F3EDE6`, `--muted: #8C8076`, `--navy-fill`→accent, status tints to the design's dark variants...) plus counter-only tokens (`--accent: #FF7A45`, `--accent-ink: #1A0E07`, `--counter-blue: #6EA8FF` for return mode, `--font-counter`, `--mono-counter`). Same discipline as the dark theme: no component CSS changes, no hex outside the block.
- **`src/theme/fonts.css` + `src/assets/fonts/`** (new): `@font-face` for bundled Archivo (400/500/600/700) and IBM Plex Mono (400/500/600) woff2, latin subset; Vite hashes them, the PWA precaches them; referenced only by counter tokens.
- **`src/till/useCounterRoom.ts`** (new): a layout effect on the Billing route setting/removing `data-room="counter"` on `<html>`; StrictMode-safe (cleanup restores, remount re-sets); also swaps the meta theme-color while mounted.
- **SyncLight** moves into the top bar slot for counter routes: `AppShell` renders it (wrapped in a `Link` to `/sell/till`) when the active route declares `room: "counter"` in `routes.tsx` metadata - the pill is the Till & Sync door (grill Q10).

### Frontend - the frame (slice 2, all under `pages/sell/`)

| Piece | New/changed | What |
|---|---|---|
| `Billing.tsx` (`Counter`) | changed | drops PageHeader; renders BillBar, ScanHero, the lines card, the rail; mode state (`sale`/`return`) arrives in slice 5 but the prop seam is cut here |
| `billing/BillBar.tsx` | new | mode toggle (Sale / Return & exchange) · bill number + status line · **bill-level Sold by** select + "Apply to all N lines" (appears when lines disagree) · Held bills (n) · Hold · New bill. Absorbs the lifecycle row; Find-a-bill moves to the return mode's doors |
| `billing/ScanHero.tsx` | new | the 60px scan bar: state ring (accent / return-blue / error red + shake), status word (LISTENING / AWAITING BILL / NOT FOUND), Look-up button (F3), the error card under it (replacing the banner style), **demo chips behind `import.meta.env.DEV`** |
| `billing/BillGrid.tsx` | changed | design's columns and type ramp; per-line offer chip + tag chips; qty stepper; discount cell (amber when carrying value); salesperson select with the no-actor amber; **no horizontal scroll at 1366** - size folds into the item cell below 1440, paddings earn the rest (grill Q8); totals strip renders inside the card foot |
| `billing/PaymentPanel.tsx` | changed | the tile: Cash row + quick-cash chips, UPI row + rest, Card row + rest, one balance footer (amber owed / green settled); credit-note rows, owed-to-customer panel and note asks **removed**; UpiCharge unchanged behind the QR button |
| `billing/RailFoot.tsx` | new | block message line + Reprint + Save & Print (F9), pinned under the rail; the customer tile sits above it (CustomerStrip restyled, typeahead intact) |
| `billing/FinishOverlay.tsx` | new (slice 3) | saved/exchange title, bill number, paid + split, change line, the bill barcode rendered big, Print again / Next bill (Enter); replaces the current `lastBill` banner |
| `src/till/useCounterKeys.ts` | new | one window keydown handler: F2 hold · F3 look up/find bill · F4 new · F9 save & print · Esc dismiss error → refocus scan · Enter next-bill only while the overlay is up; `preventDefault`; disabled while a modal asks (PIN, UPI charge); buttons gain `title` tooltips naming their key (grill Q4) |
| Rule 5 checklist homes | changed | paper re-entry keeps its own band under the bill bar; pending-draft question likewise; one-line alerts (loading / no-price-list / print-problem / note / gift / holds-due) keep `pickBillAlert` and render between bill bar and scan hero; blocked-counter takeover unchanged; floats (suggestions / not-in-system / typeahead) keep `usePositionedPopover`, restyled |

### Frontend - money behaviour (slice 4)

- **`till/tender.ts`**: note tenders removed from `Payment`/`splitOf`/`toTenders`; `whyPaymentCannotClose` gains "the pieces going out must be worth at least the pieces coming back" (net < 0).
- **`till/guard.ts` / `cart.ts`**: manual-discount clamp reads the two dials from the synced policy - cap as ceiling (input refuses to go past, message names the percent and HO), on-offer lines take no manual entry while the dial is off (input disabled with the reason as its title).
- **`till/pin.ts` / `ManagerPin.tsx`**: shrink to the window-override ask only; discount and note ask-kinds deleted.
- **`till/db.ts`**: new Dexie version dropping the cached-notes table; `sync.ts` stops applying note sections; `meta.policy` carries the boolean.
- **Setup surface**: a small policy card (cap + stacking toggle) on the existing Setup screen, calling the new endpoint; hidden below `sell: manage` by the matrix as everything else is.

### Frontend - returns on the counter (slice 5)

- **Mode state** on `Counter`; the toggle repaints the room's accent blue and re-targets the scan pipeline:
  - no bill loaded → scans resolve as bill numbers (barcode payload = the full doc number; `findBill`: till queue first, `GET /api/sell/sales?doc=` second) → loaded bill renders as the against-bill card + its lines dimmed at qty 0;
  - bill loaded → scans mark pieces coming back (max = bought − already returned, from `refunds` shape); per-line **reason + condition** selects (the quarantine feed) live on return lines;
  - exchange switch on → scans add outgoing sale lines as normal.
- **Three doors**: scan · type · **customer search** - a popover on the find-bill state reusing the `GET /api/sell/sales` mobile/name search plus the till's own queue offline; offline door 3 says it needs the line.
- "Take everything back" sets every line to its max; the equal-or-up gate then does the arguing.
- **`/sell/returns` retires**: route redirects to `/sell?mode=return`; navConfig drops the tab (Customers tab folds too); the nav/RBAC contract tests re-point at the surviving pair (`/sell`, `/sell/till`).
- `exchange.ts`'s parked-exchange handoff dissolves into direct cart state (the park/pickup existed because two screens shared the flow).

### Frontend - receipt barcode (slice 3, with the overlay)

- **`till/barcode.ts`** (new): pure Code 128 (subset B) encoder → SVG bars; unit-tested against known encodings; no dependency.
- **`till/receipt.ts`**: footer block - barcode + doc number under it; print CSS sized for 80mm paper.

### The doc pass (slice 6)

Customer written into D8 (master) + D10 (counter reads/feeds, find-bill); superseded rulings rewritten: billing-revamp grill Q1 (keyboard), D-4 + CONTEXT.md glossary (credit note / plain return), D10 §4 action row (F-keys, header); `store-front-design.html` §4 region table updated to this frame at closeout.

## Request flow (the four that matter)

**Scan → line (sale mode).** Unchanged pipeline: wedge fires into ScanHero's input → `resolveScan` → `addPiece` (increments on same barcode+season) → undo push + draft persist → `tick()` → focus returns. Discount cell now clamps from policy dials; failure path buzzes into the hero's error card.

**F9 / Save & Print.** `useCounterKeys` or the button → same `save()`: `whyItCannotClose` (now including net ≥ 0, no-actor, cap rules) → `commitBill` (number + shelf + queue, one IndexedDB transaction) → receipt with barcode → FinishOverlay (Enter = new bill) → queue syncs when it can. A tampered/stale till's payload meets the server's three refusals and lands in the failed queue for a human, as today.

**Return mode.** Toggle → scan bill barcode (or type, or customer-search popover) → bill loads (queue-first, server-second) → scans mark pieces back, reason + condition per line → exchange switch adds outgoing lines → balance shows net; net < 0 blocks with the equal-or-up line → F9 commits one Sale with return legs against the original (existing wire shape; `EXCHANGE_SHORT` can never fire from an honest till).

**Policy PUT.** Setup card → `PUT /api/sell/policy` → saved shape back → rides `_policy()` on the next dataset pull → till persists to `meta` → guard clamps from it offline.

## Error handling

- Till-first, server-backstop: every new refusal (`EXCHANGE_SHORT`, `DISCOUNT_OVER_CAP`, `DISCOUNT_ON_OFFER_LINE`) is enforced at the input or the close-guard locally from the same dials, in the counter's own words; the server codes exist for tampered or stale payloads and route to the failed-sync queue, never a lost bill.
- Flag-never-block survives the repaint: the one-line alert precedence (`pickBillAlert`), the paper and pending-draft bands, and the blocked-counter takeover keep their exact semantics - restyled, not rewired.
- The room attribute is set/removed in one layout effect; a crash mid-room leaves at worst a dark shell that the next route mount corrects.
- Fonts are bundled and precached; the room never fetches at render time - offline is identical to online.

## Assumptions made

1. The room is exactly `/sell` (Billing, both modes). Till & Sync, Customers-as-was, and everything else stay in the app's normal skin; the sync pill is the bridge.
2. The receipt barcode carries the full doc number in Code 128 B; pre-barcode bills use doors 2-3.
3. Per-line reason + condition stay as compact selects on return lines (the quarantine → RTV feed keeps its source).
4. `/sell/returns` redirects rather than 404s; LegacyRedirect already owns that pattern.
5. The `credit_note` tender mode stays in the DB enum for history; only the serializer vocabulary shrinks.
6. The stacking dial is chain-wide (db-design's granularity note); per-offer allowance is a later additive flag.
7. Slice order = feature-analysis build order; slices 1-3 are pure presentation (supervised review for subtraction, not money), slices 4-5 touch money behaviour and get the money-slice review posture.
8. Screenshot-driven QA at 1366×768 and 1920×1080 per slice; the Rule 5 checklist is walked item-by-item in slice 2's review and again at slice 5's (the two restructures).
