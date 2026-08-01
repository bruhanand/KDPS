# Billing screen revamp - Phase 1: grill decisions

Grilled 1-2 Aug 2026, Anand ruling on each.
Eleven questions, all closed.
These rulings are the spec; where they touch `docs/my-understanding/system-design/10-pos/billing-screen-revamp.html`, that doc has been updated to match.

## Q1 · Keyboard: none at all (D-1)

**Ruling: no keyboard behaviours of any kind.**
No F-keys (re-affirmed, emphatically), no Enter-on-empty-scan-box to jump to payment, no Esc-to-refocus.
Everything is a scan or a click.
The scan box keeps its existing auto-focus behaviour (cursor returns after every action); that is focus management, not a shortcut.

Anand's billing flow, confirmed against the design (all already present unless marked new):

1. New bill is a click.
2. Scanning needs no Enter; the scanner just fires.
3. Fixing a wrong item = delete the line, rescan.
4. Quantity is click-to-edit on the line.
5. Customer mobile + name are optional; the customer can skip them.
6. **New ruling: scanning the same barcode again increments the quantity on the existing line** (always, no toggle), instead of adding a duplicate line.
7. One billing salesperson acts as the default; any line's salesperson is changeable per line (the existing last-picked default).
8. Ambiguous barcode (two live seasons) shows the pick-one option, then continues - unchanged.

## Q2-Q3 · Draft = continuous autosave; Undo added

**Ruling: the in-progress bill autosaves continuously - no Draft button.**
Every scan, delete, quantity/discount/salesman change is written to the till's local storage the moment it happens.
The top strip shows a quiet "Draft · saved".
Crash, tab close, or power cut: reopening Billing restores the draft exactly where it was.
"Hold bill" stays unchanged as the deliberate park-this-customer action (it clears the screen for the next bill).

**New ruling: a per-action Undo button on the bill area**, stepping back through the last cart actions (scan, delete, quantity, discount, salesman) one at a time.
Safe by construction: nothing touches stock or money until Save & Print.

## Q4 · Quick-cash chips: yes (D-2)

**Ruling: yes, as recommended.**
Under the Cash row: **Exact** plus the next two round figures, computed from what is still to pay.
One click records what the customer handed over; the change line answers.
No settings; refine later if the counters want different denominations.

## Q5 · UPI: manual stays forever, stamped and visible (D-5)

**Ruling: the recommendation applies, edge cases per the research.**

- Manual UPI entry stays allowed forever - billing never stops on the internet.
- Every UPI tender carries a stamp: **confirmed** (the bank answered via the QR flow) or **manual** (the cashier vouched).
- No manager PIN on manual UPI; control is by visibility: the day close shows "UPI: ₹X confirmed / ₹Y manual" per till, so patterns surface the same evening.
- The QR charge card ships now against a mock payment adapter (same seam as the print adapter) with the five states: Generating → Awaiting (Cancel · Check status) → Success (reference captured) / Failed (retry or another tender) / Unknown ("can't reach the bank - check again").
- The acquirer owns the timeout: the till never marks a UPI charge failed on its own clock; Unknown offers re-check, never assumes.
- Polling per the Paytm spec when hardware lands (~8/minute, manual check-status surfaced after a minute).

**Money-slice status stays No**: the stamp is data on the tender; postings are untouched.

## Q6 · Customer lookup: a real customer master, synced to tills (D-3)

**Ruling: shape (c).**

- One customer row per mobile number: name, mobile, optionally GSTIN.
- Built automatically: every Save & Print carrying a mobile number creates or refreshes the row (latest name wins).
- Scope is **all KDPS** - a Deoghar regular is recognised in Ranchi.
- Every till syncs the list like items and offers, so the typeahead is instant and offline.
- The till holds names and numbers only - no purchase history locally.
- Bills snapshot name/mobile onto themselves (Rule 3); a later correction to the master never rewrites an old bill.
- This is KDPS's first customer master; loyalty/WhatsApp/regulars reporting stand on it later.

## Q7 · GST on the grid: badge + on-demand breakup (D-4)

**Ruling: collapse.**
Each line shows the rate as a quiet badge ("5%" / "18%") - enough to catch a wrong slab at a glance.
Clicking the tax figure in the bottom bar opens the full breakup (per-rate totals, CGST/SGST or IGST).
Print is unchanged; calculation is unchanged.
The freed width goes to item name and discount.

## Q8 · Sound on scan: yes (D-6)

**Ruling: yes, both tones.**
A short tick on a landed scan; a distinctly different buzz on a failed one (unknown barcode, or the season question waiting).
Mute toggle lives in Till & Sync per store.

## Q9 · Screen floor: 1280px

**Ruling: the fixed one-screen frame holds at 1280px width and up** (covers 1366×768 laptops), grid keeping roughly 2/3.
Narrower than that, the frame degrades honestly: bands stack, the page scrolls again, everything still works.
No separate compact design.
A till is a laptop in landscape - stated, not assumed.

## Q10 · Find a bill: stays a jump

**Ruling: keep the jump to the Customers tab.**
Autosave (Q2-Q3) makes leaving and returning free - the draft is exactly where it was.
No overlay duplicate of the past-bill search; revisit only if cashiers complain.

## Q11 · Floating prompts, one pattern

**Ruling: nothing pushes the layout.**
The "did you mean" suggestions and the "not in system" (bill-it-off-the-tag) prompt both hang off the scan box as a floating panel over the grid.
The customer typeahead behaves the same way under the mobile field.
The season question stays inline on the item's own line.
The payment rail, customer card, and footer never move a pixel.

## Consequences for the build order (unchanged from Phase 0, plus)

- Step 1 (the frame) absorbs Q9 and Q11.
- Step 2 (payment card) absorbs Q4; **plus the autosave + Undo work from Q2-Q3 and the qty-increment rule from Q1 land with the frame/cart work**.
- Step 3 (UPI charge card) absorbs Q5.
- Step 4 (customer master + typeahead) absorbs Q6 - backend model + bootstrap sync + UI.
- Step 5 (polish) absorbs Q7 and Q8.

Next: Phase 2, `/contract-designer`.
