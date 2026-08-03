# Feature analysis — pos-store-front

> **Superseded in part on 2 Aug 2026.** The POS counter redesign's Q3/Q3b/Q4/Q5/Q5b rulings are current: keyboard accelerators return; returns are exchange-only and equal-or-up; counter credit notes and standalone plain returns retire; the HO-configured manual-discount cap is absolute, with no till override. Mentions below of credit-note tenders, plain returns, discount overrides, or an open refund question are historical inputs to the 30 July slice, not current policy.

Phase 0 artifact of the dev process (`docs/agents/dev-process.md`).
Confirmed by Anand on 30 July 2026.
Phase 1 (the grill, `/grill-with-docs`) ran the same day and closed every open question below; its 14 decisions live in [`grill-decisions.md`](grill-decisions.md).
The build order and open questions in this file are the post-grill versions as of 30 July; the supersession notice above governs the later counter policy.

## Source

- D10 design discussion transcript (session of 29–30 Jul 2026): sidebar, Dashboard, cross-store request flow, Sell screen.
- `docs/my-understanding/system-design/10-pos/pos-store-requirements.html` — the requirements register (A–I) with the seven pre-design decisions.
- `docs/my-understanding/system-design/10-pos/store-front-design.html` — the running design record (sidebar ✓, Dashboard ✓, cross-store request ✓, Sell ✓).
- The four RetailJI screenshots in `10-pos/current-pos/`.
- Anand's Phase-0 confirmation (30 Jul), which added the sync model, the sidebar ruling, and the targets/access ruling recorded below.

## Scope

Everything D10 has decided so far for the store login: the ten-section flat sidebar, the store Dashboard (quick actions, today row, action queue, store-wise target), the cross-store search-and-request flow, and the Sell (POS) screen.
Out of this analysis: the undesigned D10 remainder (Return & Exchange tab, Customer Search tab, Inventory tabs, the Receive screen and its "data gets true" discussion, store open/close), HO-side offer authoring, HRMS, Tally, analytics.

## Rulings added at Phase-0 confirmation (30 Jul 2026)

1. **Online-first everywhere except Sell.** Most storefront screens are plain online screens, synced instantly. Only the Sell path runs on a local (offline) dataset.
2. **The Sell dataset is the store's inwarded inventory plus the offers.** The local inventory updates when inward/receive is approved — offline billing sells only stock that has been inwarded ("stocks are true with the scanning"). Offers load into the local dataset on a regular sync interval; when HO publishes offers, the store gets a notification and the store person syncs them to the till.
3. **Bills sync at payment time.** Payment completed → the bill syncs online (queued and synced at interval when offline). A bill created offline carries an explicit tag/label ("offline" origin) on the document.
4. **Sidebar: keep it as it is, flat sections only.** The store sidebar is an arrangement of the existing sections (the D10 ten-section shape), with no subsections. No merge of section codes in the access matrix — the #94 one-gate contract keeps its current keys.
5. **Store targets are set by the Operations Head**, and that access — like every access level — must be configurable by the admin, not hard-coded (Rule 12: access is data).

## Impact table

### Backend (Django apps)

| App | What changes | Why |
|---|---|---|
| `sell` (new) | Historical 30 July shape: Sale with cash/card/UPI/credit-note tender plus plain Return/CreditNote documents. **Superseded for the counter by redesign Q3/Q3b:** credit-note tender and standalone return retire; Sale keeps equal-or-up exchange legs. Buyer GSTIN, B2B IRN queue, idempotency and Hold Bill remain. | The core of the feature; the redesign preserves the Sale and its history while narrowing the counter surface. |
| `core` | Sale rides the existing docstatus FSM + gap-free numbering; offline-created bills need per-store gap-free numbers assigned at the till and honoured at sync. | Offline gap-free numbering is a new kernel problem; one-POS-per-store makes the local counter authoritative. |
| `stockledger` | Sale posts the stock decrement (new movement reason); auto-inward-on-scan (A10) adds a movement path if it survives the grill. | Documents write ledgers (Rule 2). |
| `finledger` | Cash ledger postings per tender mode per bill; SOR/consignment vendor liability posts at the Sale. | D4 collections design + the locked liability-timing rule. CA-gated before live money (F9 single recognition). |
| `outbound` | The cross-store request reuses the existing `StockRequest`, with the new approval route (own store manager → Operations Head → conversation → approve; Ops Head may approve directly) and an expected-arrival time the counter can quote. | D10 §3, locked 30 Jul. No hard block rules — possibility is the humans' call. |
| `approvals` | The chain is stored as an approval route — data, not code. | Rule 12; keeps the automate-later door open. |
| `masters` | Store-wise monthly target (new master, set by the Operations Head); customer capture (name + mobile on the bill, shaped so membership/wallet bolt on later per D-3). | Dashboard manager row; requirement E3. |
| `accounts` | Store persona arrangement of the sidebar (section codes unchanged); the role matrix becomes admin-editable data via a Setup screen (it_admin/superadmin), with the four money floors hard-coded and un-crossable, every change audit-logged, and the contract tests pinning gates to the stored matrix. | Rulings 4 and 5 above, settled in grill Q7/Q8; the #94 one-gate pattern survives untouched. |
| Not impacted | `inbound`, `ptmapper`, `vendors`, `files`, `aiagents`; Tally, analytics, HRMS backend. | Receive redesign parked; out of scope by decision. |

### Frontend (PWA)

| Screen / area | What changes | Why |
|---|---|---|
| `shell/navConfig.ts` | Store persona layout: flat ten-section arrangement; tabs inside Sell, Inventory, Receive, Transfer pages. | Ruling 4; the nav manifest is the single source both sidebar and route guard derive from. |
| Sell screen (new) | The RetailJI-shaped POS: scan box top-right, line grid, payment panel, customer strip, action row, sync light, Hold Bill, offer chips, salesman default-to-last. Replaces the three `/sell` planned stubs. | D10 §4, locked 30 Jul. |
| Local dataset + sync loop (new, greenfield) | Local inventory (refreshed on receive approval), local offers (interval sync + store-triggered sync on HO notification), durable bill queue syncing at payment/interval, sync light with pending count. | Rulings 1–3; "net chale ya na chale, billing nahi ruke" (F1/F2). No service worker, local store, or idempotency plumbing exists today. |
| Dashboard (rebuild of Home) | Quick actions row, today row (4 tiles, cashier sees money tiles), needs-your-action queue, live-in-store card, 7-day sparkline, manager row with month-to-date vs store target. | D10 §2, settled 30 Jul. |
| Cross-store search (new) | Search stock across all stores size by size; raise the request from the result. | D10 §3. |
| Inventory page | One page recomposing four existing screens as tabs (Stock on Hand, Damage & Quarantine, Count & Adjust, Return to Brand). | D10 §1 — divide inside the page, never the sidebar. |
| Money / Offers & Pricing (store views) | Store-scoped collections + expenses view; read-only price list and live offers. | D10 §1. |

## Rules and ledgers in play

- Documents: **Sale** (new), Exchange/Return (new, linked to Sale), StockRequest (extended).
- Ledgers: stock (decrement at sale), cash (tender split), vendor (SOR/consignment liability at sale).
- Rules touched: 1, 2, 3 (snapshot at billing), 5 (ambiguity never blocks; refuse-unpriced tension with A10), 6, 9, 10 (salesman, gated voids; the 30 July discount override was later retired by counter redesign Q5b), 11, 12 (offers, approval routes, access, screen layout as data).

## Money slice: YES

The Sale writes stock, cash, and (for SOR/consignment) vendor ledgers, carries the GST breakup, and lives on the FSM with gap-free numbering — the busiest money document in the system.
This triggers the money rules in `docs/agents/dev-process.md`: Phase 1 is `/grill-with-docs`, the build is supervised, golden-file tested.
Two CA-gated items sit on its path: SOR GST single-recognition (F9) and sold-before-PT (via auto-inward-on-scan).

## Build order (post-grill, ratified 30 Jul 2026)

The grill's research overturned the online-first-then-offline sequence: the till is built **offline-first from day one**, because the local database, client idempotency keys, local numbering, and the replay queue are data-layer foundations that are prohibitively expensive to retrofit (grill Q12).

1. **Sidebar arrangement + store Dashboard + store-target master.** Presentation only, no money. Dashboard cards run off data that already exists; sales tiles come alive at step 3. Target set by Ops Head via the admin-editable matrix.
2. **Cross-store search + request route.** Extends `StockRequest` + approvals (route as data); no money.
3. **The till, offline-first.** One supervised money slice: local dataset with sync-down, the Sale document and its postings server-side, idempotent sync-up, till-owned numbering, printing. "Online" is the queue draining fast. Golden files.
4. **The offer engine.** The D5 mechanism plus the three-layer resolution locked in grill Q11, auto-applying at the till. The pilot does not start without it.
5. **Historical plan:** Return & Exchange, Customer Search, credit notes. **Current replacement:** customer search + equal-or-up exchange on the counter; credit notes retire.
6. **Cash Summary + the daily reconciliation gate** — the condition for the pilot store going live.

Riders: the till device is standardised on Chrome with the PWA installed (Safari's 7-day storage eviction is unacceptable for an unsynced bill queue), and a receipt-printer hardware spike starts early (lead-time item, like the barcode spike).
Dependencies: 3 before 4-6; 1-2 independent of each other and of 3-6.

## Open questions after the grill

The nine Phase-0 questions were all closed in [`grill-decisions.md`](grill-decisions.md).
Still genuinely open:

1. **The five CA-gated money questions** (SOR GST single-recognition F9, the 6-month deemed-supply clock, late freight, sold-before-PT recognition, slab sign-off) — the mechanisms are designed, live money waits for the rulings.
2. **To the stores:** what is F10 "Approval / Order" actually used for? The refund/credit-note question was later closed by counter redesign Q3/Q3b: neither; only equal-or-up exchange.
3. **Pilot store choice** — one store, one counter, gated on the daily reconciliation running clean.
4. **Printer route** (WebUSB/Web Serial vs QZ Tray agent) — decided by the hardware spike.
5. **Expected-arrival time on cross-store requests** (route history vs staff-entered) — parked for the Transfer screen design.
6. **The next D10 design sessions:** Return & Exchange and Customer Search tab layouts, Inventory tab details, the Receive screen ("where the data gets true"), store open/close (I3).
