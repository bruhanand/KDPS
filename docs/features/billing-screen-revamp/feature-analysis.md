# Billing screen revamp - Phase 0: impact analysis

Confirmed by Anand, 1 Aug 2026.
Slug: `billing-screen-revamp`.

## Source

- Anand's revamp brief (chat, 1 Aug 2026): the Billing tab must never scroll as a page; the money section needs a structural redesign (functionality unchanged); UPI amount must be QR-ready for later hardware; customer mobile field should suggest existing customers; Find/New/Hold move to the top; Save & Print and Reprint always visible.
- The exploration and research record: `docs/my-understanding/system-design/10-pos/billing-screen-revamp.html` (10+ commercial systems, Indian POS, open-source POS, UPI integration specs).
Its section 4 lists decisions D-1 to D-6, carried into the grill below.
- The standing design of record it refines: `docs/my-understanding/system-design/10-pos/store-front-design.html` section 4 (region placement will be superseded on agreement; behaviour rules stand).
- Current implementation: `app/frontend/src/pages/sell/Billing.tsx` and the `src/till/` layer (feature `pos-store-front`, docs in `docs/features/pos-store-front/`).

## Impact table

| Area | What changes | Why |
|---|---|---|
| PWA · Billing screen (`pages/sell/Billing.tsx` + CSS) | Fixed three-band frame (top strip / work area with the only scrolling region / pinned footer); payment card rebuilt (pre-fill remaining, one colour-coded balance line, quick chips); customer card rebuilt (mobile typeahead, GSTIN behind a "Business bill?" disclosure); lifecycle buttons (Find / Held(n) / Hold / New) move to the top strip; alerts collapse to one line | The core of the feature: the page must fit the viewport with only the line list scrolling |
| PWA · till layer (`src/till/`) | Tender pre-fill/chip logic; a new payment adapter with a mock implementing the UPI charge states (Generating / Awaiting / Success / Failed / Unknown), same shape as the print adapter; a customer cache + typeahead lookup if D-3 chooses offline | Payment behaviour additions and the hardware-ready UPI seam |
| PWA · Held bills panel | Opens from the top strip instead of the bottom action row | Lifecycle actions regroup around the bill's identity |
| Django `sell` | Customer typeahead lookup (D-3): lightest is an endpoint over past bills' indexed `customer_mobile`/`customer_name`; heavier is a first customer master | There is no customer model today; bills carry free text only |
| Django `storefront` | Customer list joins the till bootstrap payload, only if D-3 chooses a synced offline list | The till is offline-first; lookups follow the items/offers pattern |

Not impacted: `core`, all ledgers and postings, offers/pricing, GST computation, the other Sell tabs (Return & Exchange, Customers, Till & Sync), the app shell, RBAC.

Rules in play:

- Rule 3 (snapshot): if a customer master is born, the bill snapshots name/mobile onto itself, never references the master row.
- Rule 5 (flag, never block): collapsing alerts to one line must not soften the second-window hard block, which stays full-screen.
- Rule 12 (variation is data): chip denominations and layout knobs are data-shaped.

## Money slice

**No.**
No posting, valuation, GST computation, or document-FSM change; tenders are recorded exactly as today, and pre-fill is input assistance only.
Two grill outcomes would flip this to yes and trigger the money process in `docs/agents/dev-process.md`:

1. Adopting a manual "UPI received" override (D-5), which changes tender trust semantics.
2. Any change that derives tender amounts rather than assisting input, which would touch the day-close numbers.

## Build order

1. **The frame** - fixed viewport bands, sticky grid header, pinned footer, top-strip buttons, one-line alerts. Pure structure, no behaviour change, no backend.
2. **Payment card** - pre-fill on tap, balance line, quick chips (per D-2). Frontend only.
3. **UPI charge card** - the five states behind the mock adapter. Frontend only.
4. **Customer typeahead** - blocked on D-3 (scope + offline/online); backend endpoint or master + till cache + UI.
5. **Polish** - GST column collapse (D-4), scan sound (D-6).

Steps 1-3 have no backend dependency; step 4 is the only one needing a design ruling and server work.

## Open questions (input for the Phase 1 grill)

From the exploration doc:

- **D-1** Enter on an empty scan box jumps to payment (and Esc refocuses the scan box)? Touches the 31 Jul "no shortcuts" ruling.
- **D-2** Quick-cash chips (Exact / round-ups) - yes or no?
- **D-3** Customer lookup: which customers does a till see (own store vs all KDPS), and synced-offline vs online-only? This quietly creates the first customer master.
- **D-4** GST on the grid: keep both columns or collapse to a badge with detail on demand?
- **D-5** UPI manual "mark as received" fallback: no vendor ships one; if wanted, it needs a manager-PIN control and a reconciliation flag, and flips the money-slice call.
- **D-6** Sound on scan (success + distinct error tone)?

Surfaced by this analysis:

- Minimum screen size the fixed frame must hold on, and what happens below it (rail stacks? slide-over?).
- Does "Find a bill" stay a jump to the Customers tab, or become an in-place overlay so the cashier never leaves the bill?
- Where do the "did you mean" suggestions and the not-in-system prompt render inside the fixed frame so they never push the rail?
