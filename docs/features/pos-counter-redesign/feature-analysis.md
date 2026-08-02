# POS counter redesign - Phase 0: impact analysis

Confirmed 2 Aug 2026.
**Amended same day after the Phase 1 grill** - `grill-decisions.md` closed all open questions and moved scope in three places, marked **[grilled]** below: a small backend config master arrives (Q5), the credit-note machinery leaves the counter (Q3b), and the separate returns screen retires into the counter (Q2).

## Source

- A Claude Design project, `POS Billing.dc.html` (project `8296eb9f-b9c5-44a0-8b2c-8166478e66bc`), read whole - markup, styling and the component logic behind it.
  A local copy of the imported file sits in this workspace's `.context/design-import/`.
  Its sibling `support.js` is the generic dc-runtime React shim and carries nothing to implement.
- Two screenshots from Anand showing the Sale mode and the Return & exchange mode of that design.
- Anand's framing: the top bar and the nav rail in the design are **out of scope**; only the POS itself is in.
- Read alongside: `CONTEXT.md`, D10 `store-front-design.html` §4 (the POS screen) and §5 (the Phase-1 grill rulings), and `docs/features/billing-screen-revamp/` - the revamp that shipped 2 Aug, one day before this design arrived.

## What the design is

Three different kinds of change, mixed:

1. **A new skin.** Near-black warm-brown surfaces, one orange accent, Archivo for text and IBM Plex Mono for money, codes and bill numbers.
2. **A re-cut frame.** A full-width scan bar at twice today's height; totals moved inside the line card; Save & Print moved to the foot of the right rail beside Reprint; no page header at all; a finish overlay after a sale showing the bill number as a printed barcode.
3. **Behaviour changes that are not skin.** F-keys wired to hold/look-up/new-bill/pay; Return & exchange as a mode toggle on the counter; cash refunds; no credit-note tender; a free-text discount box on every line.

Group 3 is what the Phase-1 grill has to settle.

## Impact table

### Backend (Django)

| App | Impacted | What changes |
|---|---|---|
| `core`, `accounts`, `files`, `vendors`, `inbound`, `ptmapper`, `stockledger`, `finledger`, `aiagents` | No | No model, migration, posting, serializer or endpoint. |
| `masters` | **Yes [grilled]** | Q5: a small config master for the manual-discount policy - the default cap (10%) and the may-stack allowance for offer-discounted items - HO-editable, ridden onto the till dataset so the counter enforces it offline. |
| `sell` | Marginal **[grilled]** | The receipt barcode is client-side (`till/receipt.ts`), so no server change there. Design phase decides whether the acceptance path keeps tolerating credit-note tenders from old payloads after Q3b retires them at the counter, and whether the returns endpoint needs anything when the separate screen folds in (expected: nothing). |

No new Django app is warranted.

### PWA screens

| Screen | Impacted | What changes | Why |
|---|---|---|---|
| Billing (the counter) | Yes - the whole feature | Palette, fonts, scan bar, line grid, totals placement, payment tile, action pair, finish overlay, bill-level "Sold by" with apply-to-all | This is the design |
| App shell | Yes, one concession | The counter must be allowed to drop the standard page header and run edge to edge. Top bar and sidebar untouched | The design has no page header; today the counter renders inside the standard page frame |
| Theme tokens | Depends on the palette ruling | Counter-only dark skin, or a new app-wide dark theme, or a whole-app re-token | The design's browns and orange are not the locked navy/rust |
| Return & Exchange | Only if ruled onto the counter | Would fold into the counter as a mode toggle | Open question 2 |
| Receipt (print) | Only if the bill barcode lands | A scannable bill number at the foot | Open question 5 |
| Till & Sync, Customers, Dashboard, all others | No | | |

No "coming soon" stub comes alive.

### Rules and ledgers

| Rule | In play | How |
|---|---|---|
| **5 - flag, never block** | Yes, the live one | Roughly twenty shipped controls have no place in the design (list below). Losing a flag surface in a repaint is a Rule 5 break, invisible in review unless checked deliberately |
| **6 - calculated numbers are not typed by hand** | Yes, conditionally | The design's free discount box arrives with no cap and no approval behind it |
| **10 - every action has an actor** | Yes | A bill-level "Sold by" must not let a line reach the printer with nobody on it. The design does guard this; the guard is kept |
| 1, 2, 3, 4, 7, 8, 9, 11, 12 | No | Nothing posts, nothing writes a ledger, no document lifecycle moves, no master changes |

Documents touched: none. Ledgers touched: none. Postings: none.

**Controls the design has no room for** (the Rule 5 checklist - each one needs a home before any frame ticket ships):

Undo · the "Draft saved" indicator · Find a bill · keying in a printed bill from the old machine, with its date field and its exit · the "a bill was left in progress" resume-or-discard question · the no-price-list warning · the printer-failed banner · the "this bill earns a gift" line · held bills left over from before today · the blocked-counter takeover · the "not in our system, bill it off the tag" prompt · the did-you-mean suggestions · the ambiguous-season pick · the manager PIN · the credit-note tender rows · the GST breakup popover · the owed-to-the-customer credit-note panel · the customer typeahead.

### Money slice

**No - with a condition.**

Nothing here posts, prices, or moves a document through its lifecycle, so by the letter of the test this is a free slice.
**[grilled]** The three questions that could have flipped it were answered the safe way or safer: no refunds of any kind (Q3), the discount hard-capped from HO (Q5/Q5b), and the credit note retired deliberately rather than dropped by accident (Q3b).

Practical ruling stands: run it as a free slice for spec purposes, review it supervised.
The risk here is **subtraction** - a control quietly not carried across - which an ordinary "does the new code work" review does not catch; the Rule 5 checklist (kept current in `grill-decisions.md`) is the countermeasure.

## Build order (post-grill)

1. **The skin.** Dark counter tokens, bundled Archivo + IBM Plex Mono, the chrome dressing (top bar + rail go dark on counter routes, Q1), the sync pill in the top bar (Q10). Every control stays exactly where it is and keeps working. Reversible in one commit, and judgeable on its own.
2. **The frame.** Bill bar replacing the page header (Q7, nav contracts rerouted), hero scan bar, line grid (no sideways scroll at 1366, Q8), totals inside the card, payment tile, action pair in the rail, F-keys with hover hints (Q4), bill-level Sold by with apply-to-all. This is where the Rule 5 checklist is worked through, item by item. *Depends on 1.*
3. **The finish overlay** after a sale, and the Code 128 bill barcode on the receipt (Q6). *Depends on 2.*
4. **The discount policy** - the `masters` config master (cap + stacking allowance), its dataset ride, and the counter enforcing it (Q5/Q5b); manager-PIN machinery retired if verified orphaned. *Backend independent; counter part depends on 2.*
5. **Return & exchange on the counter** - the mode toggle, three find-bill doors, equal-or-up hard gate, credit-note retirement (Q2/Q3/Q3b). The separate returns screen retires. *Depends on 2 and 3 (scanning the bill barcode).*
6. **The doc pass** - customer written into D1-D10, superseded rulings rewritten (no-keyboard, D-4 credit-note, D10 §4 action row, CONTEXT.md glossary). *Anytime after the grill; lands with closeout.*

## Open questions

None - all closed by the Phase 1 grill; the rulings live in `grill-decisions.md`.
