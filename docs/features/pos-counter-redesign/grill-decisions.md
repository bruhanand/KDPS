# POS counter redesign - Phase 1: grill decisions

Grilled 2 Aug 2026, Anand ruling on each.
Fourteen rulings, all closed.
These rulings are the spec; where they contradict an earlier record (the 1 Aug no-keyboard ruling, D-4's credit-note rule, D10 §4's action row), **these win** and the older doc is rewritten in this feature's doc pass.

## Q1 · The dark travels to the counter's room, not the app

**Ruling: option D.**
The counter is **always dark**, whatever the app theme says - the design's warm near-black surfaces, orange accent, Archivo for text, IBM Plex Mono for money/codes/bill numbers.
While a counter route is open, the top bar and the nav rail dress in the same dark tokens, so the room has no seam; every other route keeps the June "Warm" language byte-identical.
The two fonts are **bundled** (self-hosted, cached by the PWA) - a shop counter works with the line down, so no Google Fonts request may sit on the render path.

## Q2 · Return & exchange moves onto the counter

**Ruling: as designed - the mode toggle, fully.**
Sale / Return & exchange is a toggle on the bill bar; the return mode scans the old bill, shows its lines dimmed, marks pieces coming back by scan, offers "take everything back", and an exchange switch scans new pieces going out.
The separate `/sell/returns` screen retires.
The machinery underneath (`exchange.ts`: refund = what the customer paid, exchange document = return leg + sale leg linked to the original bill) survives; what moves is where the picking happens.

**Finding the bill has three doors, all on the counter:**
1. scan the bill's printed barcode (Q6),
2. type the bill number,
3. **search by customer** - mobile or name, see their past bills, pick one (the walked-in-with-nothing case). Reads the till's synced customer master (#242/#245) and the existing bill-search endpoint when online.

**Doc scope:** the customer is missing from the design corpus - born in a feature folder (#242), placed nowhere in D1-D10. This feature's doc pass writes it in: D8 as the master, D10 where the counter reads and feeds it, the returns flow where it finds bills.

## Q3 · No money ever leaves

**Ruling: there are no refunds of any kind.**
Money that has come into KDPS never goes back out - no cash from the drawer, no UPI reversal, no card refund.
A return exists only as an **exchange** (the case that matters: damaged goods), and the customer buys equal or more.
The design's "Refund done" overlay and refund tender boxes are dropped.

## Q3b · The exchange can never come up short

**Ruling: equal-or-up is a hard gate.**
The pieces going out must be worth at least the pieces coming back; Save & Print refuses to close otherwise, with a plain line saying so.
Ruled twice, deliberately - recorded as policy, not a Rule 5 violation.

**Consequences, accepted knowingly:**
- **The credit note dies at the counter.** Short exchanges were its only birth; nothing issues one, so nothing redeems one. The #182/#184 issue/cache/redeem machinery and the "owed to the customer" panel are retired from the counter. (Whether the server's acceptance path keeps tolerating note tenders from old payloads is a design-phase call; nothing will send them.)
- CONTEXT.md's glossary entry ("Credit note (counter)... plain returns are credit-note-only") and D-4's plain-return ruling are **superseded** - rewritten in the doc pass.

## Q4 · F-keys return

**Ruling: keyboard shortcuts are in - reversing the 1 Aug ruling.**
F2 hold · F3 look up / find bill · F4 new bill · F9 pay & print · Esc back to scan (and dismiss error) · Enter = next bill on the finish overlay.
The printed key labels come **off** the buttons; **hovering a button shows its shortcut** (tooltip).
Handlers `preventDefault` to claim the keys from the browser.
Every action stays a visible button - the keys are an accelerator, never the only door.
Doc pass rewrites the billing-screen-revamp grill Q1 record and D10 §4's "no F-key shortcuts" line.

## Q5 · The discount box: computed first, capped manual second

**Ruling: the model is -**
1. A scanned item **shows its linked discount by itself** - the offer rides the barcode, lands on the line, names its rule (the shipped offer engine, kept).
2. **Manual discount is percent-capped, hard** - default **10%**, on undiscounted items.
3. **An item already on offer takes no further manual discount** - unless configuration explicitly allows it more.
4. **Both dials are data, set at HO** (Rule 12): the default manual cap, and the may-stack allowance for discounted items. Owner / Operations Head / admin territory, in the admin section.

Maps onto D5's layer model: manual discount is a layer with a configured cap and a configured combine flag, like offers stack only when flagged.

**Scope consequence:** a small backend config master (the cap, the stacking allowance) + its ride on the till dataset so the counter enforces it offline. Phase 0's "no Django change" is amended.

## Q5b · The cap is absolute

**Ruling: absolute - no way around it at the till.**
No manager PIN, no override; the ceiling moves only from HO (Operations Head, owner, admin).
With discounts, credit notes and plain returns all off its docket, the counter's manager-PIN machinery is likely fully orphaned - **verify at design time what still rides on it; retire it if nothing does.**

## Q6 · The bill barcode

**Ruling: yes - functionality now, bill redesign later.**
A **Code 128** barcode of the full bill number (`26-27/BANKA/SAL/1041`) at the foot of the existing receipt template, drawn as pure SVG in `till/receipt.ts` - no library on the print path, works offline.
The printed bill's proper redesign is a future feature; this adds only the barcode.
Typing the number and customer search remain the other doors (pre-barcode bills exist).

## Q7 · The page header goes

**Ruling: confirmed.**
The standard PageHeader, section tabs and breadcrumb leave the counter; the design's **bill bar** replaces them (mode toggle · bill number + status · Sold by · Held bills / Hold / New bill).
Two tabs are absorbed (Return & exchange → the toggle; Customers → the return mode's find-bill door); Till & Sync's door moves to the sync pill (Q10).
The RBAC/nav contract tests are **rerouted, not deleted** - a login without a section's access must still never see a door to it.

## Q8 · No sideways scroll at 1366

**Ruling: the bill grid never scrolls horizontally at 1366px** - the counter's reference width.
The design phase earns the pixels (padding, column widths, folding size into the item cell if it must); the constraint is the ruling, the pixels are engineering.

## Q9 · Demo scanner chips

**Ruling: kept, dev builds only** (`import.meta.env.DEV`).
One click scans a known tag or bill for browser QA; never shipped to a shop.

## Q10 · The sync light becomes the top-bar pill

**Ruling: as the design draws it.**
While a counter route is open, the top bar hosts the existing SyncLight as the "Synced / Offline · will sync" pill beside the store name; **clicking it opens Till & Sync** - restoring the door Q7 removed.
Other routes keep today's top bar untouched.

## Bill-level "Sold by" (from the design, no dissent)

The bill bar carries a bill-level salesperson select; lines inherit it when they have nobody; "Apply to all N lines" appears when lines disagree with it.
The per-line select stays; the actor guard stays (no line reaches the printer with nobody on it).

## The Rule 5 checklist (carried from Phase 0, binding on the frame slice)

Every shipped control gets a home in the new frame before its ticket closes - none may be dropped by repaint:
Undo · "Draft saved" indicator · find a bill · paper re-entry (date field + exit) · resume-or-discard pending draft · no-price-list warning · printer-failed banner · gift line · held-since-before-today review · blocked-counter takeover · not-in-system "bill off the tag" · did-you-mean suggestions · ambiguous-season pick · GST breakup popover · customer typeahead.
(The credit-note rows, owed-to-customer panel and manager PIN leave the list by Q3b/Q5b - retired by ruling, not dropped by accident.)
