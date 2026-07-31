# pos-store-front - API contract (Phase 2)

Companion to `db-design.md`.
Conventions used throughout (matching the existing backend):

- DRF `APIView`/generics, explicit paths in `<app>/urls.py`, JWT auth (`CookieOrHeaderJWTAuthentication`), default `IsAuthenticated`.
- Permission gates via `require_section(section, minimum)`; scoping fail-closed via the existing store/brand scope helpers.
- Error body for all NEW endpoints: `{"error": "<human message>", "code": "<ERROR_CODE>"}` with the HTTP status in the table per endpoint. (Existing endpoints keep their current shape.)
- Money in integer paise; times UTC ISO-8601 (IST is presentation).
- The till talks to these endpoints through its durable queue; every write it replays is idempotent.

Endpoints are grouped by build-order step.

---

## Step 1 - Dashboard & targets

### GET `/api/store/dashboard`

**Amended 30 Jul 2026, after building it (#174).** Six things below were written as if `sell` and `offers` already existed; what shipped is marked inline, and the till (#181) should be built against this amended text, not the original sketch.

Auth: `require_section("home", CAP_VIEW)`.
Store resolution, **as built**: scope narrowed by the top-bar switcher (`active_store_ids`) picks the store, and `?store=` narrows *within* that rather than reaching past it.
The original line ("must be in the caller's scope") left the switcher unsaid, which would have put two scope models on one screen: the `approvals_pending` row counts through `inbox_for`, which obeys the switcher, so a store named past the switcher would have read nought on that row alone while the other five counted correctly - the #171 defect class, on a card nobody would have checked.
A caller who can see many stores and has picked none gets `SCOPE_DENIED`, not an arbitrary first store.

Response 200 (cards keyed; every count links to a section/tab):

```json
{
  "store": "DEO",
  "today": {"net_sales_paise": 0, "bills": 0, "avg_bill_paise": 0, "pieces": 0,
             "collections": {"cash": 0, "card": 0, "upi": 0, "credit_note": 0},
             "vs_yesterday_pct": null},
  "action_queue": [{"key": "approvals_pending", "count": 2},
                    {"key": "transfers_to_receive", "count": 1},
                    {"key": "grn_pt_pending", "count": 0},
                    {"key": "quarantine_to_confirm", "count": 0},
                    {"key": "rtb_windows_closing", "count": 1},
                    {"key": "open_count_session", "count": 0},
                    {"key": "held_bills", "count": 2},
                    {"key": "uncosted_sale_lines", "count": 0},
                    {"key": "continuity_flags", "count": 0}],
  "live": {"offers": [{"id": 1, "brand": "MUFTI", "one_liner": "30% off FW25"}],
            "in_transit": [{"doc_number": "26-27/RAN/TRF/12", "pieces": 40, "expected": "2026-07-31"}]},
  "last7": [{"date": "2026-07-24", "net_sales_paise": 0}],
  "manager": {"day_close": {"date": "2026-07-29", "state": "balanced"},
               "mtd_net_paise": 0, "target_paise": 0}
}
```

Business logic:

1. Resolve store from scope narrowed by the switcher (above); reject anything else.
   -> no single store, or a store outside it -> `SCOPE_DENIED` (403)
2. Aggregate today/last7 tiles from `sell_sale` + `sell_saletender` for the store (billed_at in store-local day).
   **As built:** noughts, and a new top-level `"sales_live": false` beside them. `sell` does not exist until #177, and four zeros with nothing to read them against say "this store sold nothing today" when the truth is "this store cannot bill yet". The flag flips to `true` with the Sale document; nothing else about the block changes.
3. Build action_queue counts from: approvals (pending, store-scoped), in-transit transfers inbound, GRN/PT drafts, QuarantineStock, RTV windows, open count sessions, `sell_heldbill`, `sell_deferredcosting(waiting)`, `sell_continuityflag(open)`.
   **As built:** the first six keys only. The last three read `sell` tables that #177-#186 create, and they are *absent* rather than reported as nought - the ticket's own words are "counting what already exists", and a row reading "0 bills on hold" is a sentence about a store's morning. `approvals_pending` is the caller's own inbox (`inbox_for`), not every pending approval at the store: a count that opens onto an empty screen is worse than no count. `quarantine_to_confirm` counts draft `MarkDamaged` (the flag awaiting confirmation, #138), and `rtb_windows_closing` counts open `alerts_alert(return_window)` rather than re-deriving the pool, so the card and the Alerts screen cannot drift.
4. `live.offers` = offers where store in scope and today within dates and status live.
   **As built:** always `[]` - the rulebook is #183. Empty rather than absent: "no offers running" is a card a store reads every morning.
5. `manager` block included only when the caller holds `sell >= CAP_APPROVE` at this store; otherwise the key is absent (matrix-driven, cashiers see the money tiles but not this row - grill settled).
   **As built: `sell >= approve` AND `money >= view`.** What the block carries is `StoreTarget`, which `/api/masters/store-targets` serves behind `money: view` - gating on Sell alone opened a second door onto data whose first door is locked, and handed the target to a seat holding `sell: manage` with a ratified `money: none` cell (IT Admin).
   Note also: no *seeded* role reaches `sell: approve` today. The ratified sheet gives both store roles `sell: operate`, and an override may only vary sections the sheet left blank, so putting a store manager on the manager rung is an access change two administrators make in the editor (#173) - live on the next request - not a code edit. **Anand's ruling is outstanding on whether the sheet should move instead.**
6. `today.collections` and tiles come from synced bills only; the card is labelled with the last sync time of the till (from register state).
   **Deferred to #182**, which builds register state. Nothing is labelled today because the till has no clock to read.
7. `live.in_transit[]` is **as built** `{id, doc_number, pieces, expected}`. `expected` is the transfer's `expected_arrival_note` (free text: "Bus, Friday evening"), not the date this sketch showed - no expected-arrival date column exists on a transfer, and deriving one from the note would be inventing it; if a real date is wanted, it is a column on `StoreTransfer` first. `id` is there because the card links each carton to its own document, which is where the store scans it in: browser QA found that `transfers_to_receive` alone sent the *receiving* store to `/transfer/in-transit`, a screen scoped to the **source** store, so a store reading "1 carton to receive" clicked through to "nothing on the road". The row now opens the Transfers list and the card opens the carton.
8. `manager.day_close.state` is **as built** `"not_built"` until store open/close (I3) lands. The key keeps its shape from the first day rather than appearing later.

Errors: `SCOPE_DENIED`/403 only (a fresh store returns zeros, never 404). All three causes - no store picked, a store you cannot open, a bad `X-KDPS-Unit` - wear that one code and are told apart by the sentence, never by the code.

### GET | PUT `/api/masters/store-targets`

GET: `require_section("money", CAP_VIEW)`; `?store=&fy=` filters; returns `[{store, month, target_paise}]` (a store login sees its own store only, via scope).
PUT: `require_section("money", CAP_MANAGE)` (the Operations Head per the matrix; the cell is admin-editable).
Body: `{"store": "DEO", "month": "2026-08-01", "target_paise": 250000000}` - upsert on (store, month).

Business logic (PUT):

1. Gate money>=manage; store must exist.
   -> unknown store -> `NOT_FOUND` (404)
2. Validate month = first of month, target_paise >= 0 integer.
   -> bad body -> `VALIDATION` (400)
3. Upsert `masters_storetarget`, stamp `set_by`.
4. Return 200 with the row.

| code | HTTP | trigger |
|---|---|---|
| VALIDATION | 400 | non-first-of-month, negative/non-integer target |
| SCOPE_DENIED | 403 | caller lacks money manage |
| NOT_FOUND | 404 | unknown store |

---

## Step 2 - Cross-store search & request

### GET `/api/stock/availability`

Auth: `require_section("stock", CAP_VIEW)`.
**Registered scoping exception:** this endpoint deliberately reads stock across ALL stores (read-only, quantities and sizes only, no cost, no value) - the cross-store search ruling. The exception is registered with that reason beside the scope helper, same pattern as registered role lists.
Only the **store** axis is suspended. A brand-scoped caller (a brand manager) stays narrowed to the brands they are entitled to: the customer-at-the-counter argument is a store's, and it says nothing about letting one brand's representative read another brand's network position.

Query: `q` (barcode, design no., or name; required, min 3 chars), `brand`, `size` (optional).
Response 200: `{"results": [{"design": "X123", "brand": "MUFTI", "item": "Shirt", "sizes": [{"size": "M", "stores": [{"store": "RAN", "store_name": "Ranchi Warehouse", "color": "Navy", "sku_code": "8901234567890", "hsn": "6205", "season": "SS26", "qty": 2}]}]}], "truncated": false}` (cap 200 styles, `truncated` flag - same convention as StockOnHandView).

**As built (30 Jul 2026), two refinements to the shape above.** Both were forced by the screen and are recorded here rather than left to diverge:

- **The innermost entry is one SKU at one store, not a size's total** - it names its `color` and its `sku_code`. "Request this" builds a `StockRequestLine`, and a line needs a barcode; a size whose colours were summed together reads tidier and leaves the counter unable to say which piece the customer wants. Two colours of one size at one store are therefore two entries with the same `store`.
- **Styles are keyed on brand + design, not design alone.** A design number is a brand's own numbering, so two brands may both call something "1001"; grouping on the bare style code would head one card with the wrong brand and total another brand's pieces into it. The 200 cap counts brand+design pairs.

Business logic:

1. Gate stock>=view.
2. Resolve `q` against Sku (barcode exact, design prefix, name icontains).
   -> under 3 chars -> `VALIDATION` (400)
3. Aggregate `StockOnHand(net_qty > 0)` across all stores (active stores only), grouped brand x design x size x store x SKU.
4. Return with truncation flag; log nothing sensitive (no cost fields exist in the response by construction).

| code | HTTP | trigger |
|---|---|---|
| VALIDATION | 400 | q missing/too short |
| SCOPE_DENIED | 403 | caller lacks stock view |

*As built:* the `SCOPE_DENIED` **code** is not emitted - the capability gate is `require_section`, which answers with DRF's `{"detail": ...}` at 403, exactly as the sibling `/api/masters/store-targets` gate does. The `{"error", "code"}` shape is carried where the contract's code table earns its keep (the till branching a queued write on it); unifying the two capability gates is one change across both endpoints, not this slice's.

### POST `/api/outbound/stock-requests` (CHANGED, updated in place)

Existing endpoint; three changes:

- Body gains `source: "cross_store_search"` (default `manual`) and `expected_arrival_at` (optional; the time quoted to the waiting customer - no hold is placed on the piece).
- On create, `request_document_approval` now attaches the seeded `ApprovalRoute(kind="stock_request")`: step 1 = requesting store's manager, step 2 = Operations Head, with later-step short-circuit allowed (the Ops-Head-direct-approve ruling).
- The fulfilling store is a suggestion, never a constraint: no availability/blocking validation is added ("possible or not" is the humans' call - grill/D10 locked).

Approval progression (in `approvals`, generic):

1. An approver whose role is in the current step's roles approves -> `current_step += 1`; final step approved -> Approval approved (existing semantics).
2. An approver of a LATER step with `later_step_may_short_circuit` approves -> all earlier steps close as satisfied, decision recorded with the actual actor.
   -> approver's role in no remaining step -> `NOT_AN_APPROVER` (403)
3. Reject at any step needs a reason (existing constraint).

---

## Step 3 - The till (dataset down, bills up, register)

### GET `/api/sell/dataset`

Auth: `require_section("sell", CAP_OPERATE)`; store from scope (one till per store).
Query: `since` (opaque cursor = last watermark; omit for full bootstrap).

Response 200:

```json
{
  "cursor": "2026-07-30T10:11:12.000Z",
  "full": true,
  "store": {"code": "DEO", "gstin": "10AAAAA0000A1Z5", "state_code": "10"},
  "items": [{"barcode": "8901...", "season": "FW25", "design": "X123", "brand": "MUFTI",
              "item": "Shirt", "size": "M", "color": "Navy", "hsn": "6205",
              "mrp_paise": 249900, "no_discount": false}],
  "stock": [{"barcode": "8901...", "qty": 3}],
  "gst_slabs": [{"hsn_prefix": "61", "threshold_paise": 250000, "rate_below": "5.00",
                  "rate_above": "18.00", "effective_from": "2025-09-22"}],
  "offers": [{"id": 1, "layer": "brand", "brand": "MUFTI", "trigger_type": "qty", "trigger_config": {},
               "reward_type": "pct_off", "reward_config": {}, "item_scope": {},
               "starts_on": "2026-07-01", "ends_on": null, "combinable": false, "priority": 100}],
  "credit_notes": [{"number": "26-27/DEO/CRN/4", "remaining_paise": 120000, "expires_on": "2027-01-30"}],
  "salesmen": [{"id": 3, "code": "ALIE", "name": "Ali E."}],
  "managers": [{"user_id": 7, "name": "R. Kumar", "till_pin_hash": "pbkdf2$..."}],
  "deleted": {"items": [], "offers": [], "credit_notes": []}
}
```

Business logic:

1. Gate sell>=operate; resolve the caller's single store.
   -> multi-store or no-store scope -> `TILL_SCOPE` (403) - the till is a store login by construction
2. `since` present -> delta by `updated_at > since` per section; absent -> full snapshot, `full: true`.
3. Items = Cohort joined Sku for barcodes with stock or recent movement at this store (cap: all cohorts of this store's brands; the till stores ~20k rows comfortably in IndexedDB).
4. `stock` = StockOnHand for this store (qty only - **no cost or margin fields anywhere in this payload**, H2).
5. `offers` = rules whose store_scope includes this store and (ends_on is null or >= today - 7d); dates ride inside so the till starts/stops offers on its own clock (grill Q3).
6. `credit_notes` = open notes issued by this store (grill Q4). `managers` = this store's users holding `sell >= CAP_APPROVE`, pin hash only (offline override verification).
7. Return new cursor = max watermark seen.

| code | HTTP | trigger |
|---|---|---|
| TILL_SCOPE | 403 | caller not scoped to exactly one store |
| SCOPE_DENIED | 403 | caller lacks sell operate |

**Amended 30 Jul 2026, after building it (#179).**
Ten things above were written before the delta had been thought through end to end.
What shipped is below, and #181 should be built against this text.

- **Which sections are deltaed.**
  Step 2's "per section" is now explicit: **items and stock** carry a watermark; **store, gst_slabs, salesmen, managers** are sent whole on every response.
  A delta over five rows saves nothing and would need a deletion channel `deleted` does not give it - and `deleted` names exactly the three sections that can lose a row invisibly (items, offers, credit notes).
  `managers` in particular must never be stale: a rung withdrawn at head office is withdrawn on the next request, so the counter's copy is replaced, never patched.
  Consequence for db-design: the `updated_at` index it asks for on `GstSlab` is **not** built, because nothing filters that column; the indexes that are built are on `Sku`, `Cohort` and (new, not in db-design) `StockOnHand(store, updated_at)`, which every delta scans twice on the biggest table in the system.
- **The cursor sits a quarter of an hour behind the clock**, and step 7's "max watermark seen" is not what shipped.
  `updated_at` is stamped when a row is written, not when its transaction commits, so a cursor set to the request's own instant can step over a row that was stamped before the request and landed after it - and that row is then missed for ever.
  The lap has to outlast the longest write transaction in the system, which is a PT inward: one `atomic` block upserting `Sku` and `Cohort` row by row, minutes rather than seconds on a 20,000-line PT.
  The till upserts every section by key, so the overlap re-sends a handful of rows and the alternative loses one permanently.
- **The lap is not what the correctness rests on.**
  A **bootstrap cannot miss anything by construction**, so #181 must take one at store open each day rather than deltaing for ever off its first sync.
  That bounds any residual watermark hole to a day, without anybody having to notice one.
- **A damaged `since` self-heals into a full bootstrap** rather than answering `VALIDATION`.
  The cursor is opaque and ours; a till holding a damaged one cannot repair it, and a GET it can never escape is worse than re-sending 20,000 rows once.
  Both failure shapes are caught: Django's `parse_datetime` answers nothing for text that is not a timestamp ("yesterday-ish") but *raises* for text correctly shaped and impossible ("2026-02-30T00:00:00Z").
  No new error code.
- **`items[].mrp_paise` can be `null`, and is never nought.**
  A PT that quotes no MRP registers the SKU with none, deliberately, so an unpriced piece really does reach a shelf.
  The till prices the scan from this field and the accept pipeline writes what the till sends straight onto the bill, so a nought would post no revenue and no tax against a garment that walked out of the shop.
  `null` says "this needs a price from a human"; #181 must not treat it as free.
- **`deleted.items` carries barcodes**, and the only withdrawal that exists is deactivating the SKU.
  A cohort is a record of a purchase and is never unmade; a stock row falls to nought rather than vanishing.
  So a removal takes every season of that piece with it, and a *bootstrap* reports none - there is nothing cached to remove, and an inactive piece is simply absent from `items`.
- **`deleted.credit_notes` has a third trigger the watermark cannot see.**
  A note dies because a date passed (Rule 11) with nothing written, so the delta also asks which notes crossed their own `expires_on` between the cursor and today.
  The other two are the note itself changing (cancellation) and a redemption row appearing - the balance is not a column on the note, because a submitted document may not be UPDATEd.
  A bootstrap sends only notes that have not passed their date, since it reports nothing as closed anyway.
- **`salesmen` rows carry `is_active`** (additive to the sketch).
  `deleted` has no salesmen key, so a seller who has left says so on their own row and the till drops them from the per-line popup.
  A bootstrap sends only the working list.
- **`managers` is narrower than "users holding `sell >= approve`".**
  It is people **explicitly assigned to this store** whose scope is stores at all, who are not the break-glass superuser, and who have actually set a PIN - a blank hash is not a credential.
  A network- or entity-wide administrator whose matrix cell happens to say `sell: manage` is not one of this counter's people, and this list is a credential set that leaves the building on a shop-floor device.
  Note also, exactly as the Dashboard's manager row noted: **no seeded role reaches `sell: approve`**, so out of the box this list is empty until an administrator grants the rung in the editor (#173).
  **Anand's ruling is outstanding on whether the ratified sheet should move instead.**
- **`gst_slabs` includes slabs whose date has not arrived.**
  A rate change announced today and effective in October has to be on the device before the counter reaches October offline.
  The rates are two-decimal **strings**, so the till's back-calculation out of an MRP-inclusive price cannot drift a paise from the server's.
- **`SCOPE_DENIED` is not emitted as a code.**
  The capability refusal is `require_section`, which answers with DRF's `{"error": ...}`-less `{"detail": ...}` at 403, exactly as `/api/stock/availability` recorded when it shipped.
  `TILL_SCOPE` does carry its code, because the till branches on it: it means "this login will never be a till", which is not something to retry.
  Unifying the two body shapes is one change across every gate in the project, not this endpoint's to make alone.
- **Two sections were added while building the Billing screen (#181): `seasons` and `policy`.**
  Both are sent whole on every response, for the same reason `gst_slabs` and `managers` are.
  `seasons` is `[{code, name, status, sort_order}]`, the season master's own ordering.
  A2 says a scan that does not name a season resolves to the *oldest live* one with stock.
  `resolve_piece` makes that choice in three steps: the season actually on this shelf first (from `StockOnHand`), then `(is_closed, sort_order)` from the season master, then the cohort's own id.
  The till can apply the second step and not the first, because the dataset's `stock` rows are counted per barcode and carry no season - so a till without the master would fall back to sorting names, where "FW25 before SS26" is true only by the accident of the alphabet.
  That the two differ on the first step does not matter in practice: the season the till picks is the season it writes on the line, and the accept pipeline honours an exact `(barcode, season)` outright, so the till's choice is the one that reaches the books.
  Sending season-aware stock so the till could match step one exactly is a change to the `stock` section, and it belongs with whatever slice first needs it rather than with this screen.
  `policy` is `{"manual_discount_cap_percent": "7.50"}` from `SellPolicy`, a two-decimal string for the reason the tax rates are.
  Without it the counter cannot hold the cap it is meant to hold, and a cashier's over-cap discount would be discovered by an `OVERRIDE_REQUIRED` days later, on a bill already printed, paid for and in a customer's hand.

- **`updated_at` was not a new column and is not backfilled.**
  db-design lists "`updated_at` (NEW column, auto_now + index) ... Backfill: set to migration time" for `Sku`/`Cohort`/`GstSlab`.
  The column already exists on all three through `TimeStampedModel` and has been stamping real edit times since those tables did, so only the index is new - and a backfill would throw away the only history a delta can read.

### POST `/api/sell/sales`

The one writer of a Sale (bill or bill-with-exchange). Idempotent; the till's queue replays it safely.
Auth: `require_section("sell", CAP_OPERATE)`; bill's store must equal the caller's scoped store.

Request body (one bill):

```json
{
  "idempotency_uuid": "c0ffee...",
  "store": "DEO", "fy": "26-27", "till_seq": 74,
  "origin": "offline", "billed_at": "2026-07-30T12:31:00Z",
  "customer": {"name": "", "mobile": "", "gstin": ""},
  "lines": [{"line_no": 1, "direction": "sale", "barcode": "8901...", "season": "FW25",
              "qty": 1, "mrp_paise": 249900, "disc_paise": 74970, "net_paise": 174930,
              "gst_rate": "5.00", "gst_paise": 8330, "salesman": 3,
              "offer_id": 1, "offer_evidence": {"layer": "brand", "beat": [], "saved_paise": 74970},
              "manual_desc": "", "override_by": null}],
  "exchange": {"original": {"store": "DEO", "fy": "26-27", "till_seq": 40},
                "lines": [{"line_no": 2, "direction": "return", "barcode": "8901...",
                            "qty": 1, "refund_paise": 129900, "condition": "good", "reason": "size"}]},
  "tenders": [{"mode": "cash", "amount_paise": 45030},
               {"mode": "credit_note", "amount_paise": 0, "credit_note": "26-27/DEO/CRN/4"}],
  "totals": {"gross_paise": 249900, "discount_paise": 74970, "net_paise": 45030,
              "gst_paise": 8330, "round_paise": 0},
  "override": {"user_id": 7, "kind": "over_cap_discount"}
}
```

Success: **201** `{"doc_number": "26-27/DEO/SAL/74", "id": 991, "flags": ["number_hole"]}`.
Replay (same `idempotency_uuid`): **200**, identical body, zero writes (F2).

Business logic:

1. Gate sell>=operate; `store` == caller's scoped store.
   -> mismatch -> `SCOPE_DENIED` (403)
2. Idempotency: existing Sale with this `idempotency_uuid` -> return 200 with the stored result. Concurrent duplicate (row lock held) -> wait-and-return, never a second document.
3. Validate shape: >=1 sale-or-return line; integer paise everywhere; Σ tender amounts == totals.net_paise; per line `mrp/disc/net/gst` arithmetic consistent; MRP back-calculation checked (net inclusive; base = net x 100/(100+rate) half-up; rounding carried in totals.round_paise).
   -> arithmetic/tender mismatch -> `TENDER_MISMATCH` (422)
   -> malformed -> `VALIDATION` (400)
4. Bill number: `(fy, store, till_seq)` must be unassigned.
   -> taken by a different uuid -> `BILL_NO_TAKEN` (409) - two writers on one series; a human problem, the till surfaces it and stops
   -> till_seq beyond next expected -> accept + `sell_continuityflag(kind=number_hole)`; flag, never block
5. Resolve each sale line to a Cohort: exact (barcode, season); season absent -> the oldest live season with stock at this store (A2). No cohort at all -> require `manual_desc` + mrp -> mark `sold_before_inward`, `costing_status=deferred`, create `sell_deferredcosting(waiting)` (grill Q5). Stock shows zero locally -> proceed (negative allowed, count reconciles).
   -> unknown barcode AND no manual_desc -> `LINE_UNRESOLVED` (422)
6. Discount policy: any line whose discount exceeds the rulebook + cashier cap requires `override` with a manager (`sell >= CAP_APPROVE` at this store); recorded on the bill (H3/B2).
   -> over-cap without override -> `OVERRIDE_REQUIRED` (422)
7. Credit-note tenders: note must exist, be open, issued by this store, remaining >= amount -> write redemption row, decrement remaining, status->spent at zero.
   -> unknown/closed/short note WITH manager override -> accept + flag `cn_unverified` (grill Q4)
   -> without override -> `CREDIT_NOTE_INVALID` (422)
8. Exchange present: resolve original by (store, fy, till_seq); refund per returned line = what was actually paid on the original line (D2). Original not found (paper era) -> accept + flag `return_orig_missing`. Condition routes stock: good -> available, damaged -> quarantine (D3). If totals.net_paise < 0 (return exceeds new items) -> issue a CreditNote for the difference; cash never leaves the drawer.
9. Create Sale + lines + tenders (idempotent_create, docstatus draft); `post()` with `VoucherSeries.accept_external(fy, store, "SAL", till_seq)` minting `doc_number`.
10. Postings fire (see §Postings): stock ledger `sale_out`/`sale_return_in` per priced line; GL event A (money side); GL event B (cost side) for priced lines; deferred rows wait.
11. B2B: `customer.gstin` present -> derive `b2b_tax_kind` from its state code vs the store GSTIN's (same -> cgst_sgst, different -> igst); if the bill's printed split disagrees -> accept + flag `gst_mismatch`; enqueue `sell_irnqueue(due_on = billed_at + 30d)` (grill Q8).
12. Advisory recompute (never blocks): server reprices GST from the dated slab and re-runs offer resolution; disagreement beyond 1 rupee/line -> flag `offer_mismatch`/`gst_mismatch` for the daily applied-vs-rulebook check (B3, D5 Q10).
13. Persist result envelope for idempotent replay; return 201.

| code | HTTP | trigger |
|---|---|---|
| VALIDATION | 400 | malformed body, non-integer paise, missing required fields |
| SCOPE_DENIED | 403 | store outside caller scope / lacks sell operate |
| BILL_NO_TAKEN | 409 | (fy, store, till_seq) already minted under a different uuid |
| TENDER_MISMATCH | 422 | tenders don't sum to net / line arithmetic inconsistent |
| LINE_UNRESOLVED | 422 | unknown barcode with no manual_desc |
| OVERRIDE_REQUIRED | 422 | over-cap discount without manager override |
| CREDIT_NOTE_INVALID | 422 | bad note tender without manager override |

(Every flag named above has a `sell_continuityflag` kind; flags are returned in the 201 body.)

**Amended 31 Jul 2026, after building the split tender and the manager's PIN (#182).**
Four things about the `override` block, and one new endpoint that had to exist for any of it to work.

- **`override` carries `at` as well as `user_id` and `kind`.**
  The manager types their PIN and the cashier goes on scanning; Save & Print is a different moment, sometimes minutes later, and the gap between the two is the evidence.
  Optional, because a till that predates the field is still a till.
- **The bill records the override, not only the line.**
  `db-design.md` puts `override_by` on `sell_saleline`, which is right for a discount and has nowhere to hang the other case: an unrecognised credit note is a *tender*, and the lines it helped pay for are ordinary lines.
  So `sell_sale` gains `override_by` / `override_kind` / `override_at` (migration `sell.0005`), and a daily check reading "somebody took an unknown note here" finds a name against it.
  The line-level field is unchanged.
- **`kind` is a closed vocabulary**: `over_cap_discount`, `credit_note`, or `over_cap_discount+credit_note` when a manager was asked both at once (`sell.serializers.OVERRIDE_KINDS`, a `ChoiceField`).
  One bill can need two things approving and the contract has one field for them; joining them in a fixed order means the value a check groups on has one spelling.
- **What one tap authorises is bounded at the till, and only at the till.**
  A manager approves *this discount on this line*, and the till refuses to close if the discount grows, moves to another line, or is joined by a second unknown note (`till/pin.ts` `covers`).
  The server still asks only "is `override.user_id` a manager of this store" - and cannot honestly ask more, because the till composes the payload and the PIN is verified on the device by design (grill Q1).
  The server-side floor is therefore *a named manager*, and the per-exception binding is a property of the screen; the daily check is what audits the pair.

**Amended 31 Jul 2026, after building the B2B corner (#187).** Three things about step 11.

- **A seventh flag kind exists: `gstin_invalid`.**
  db-design lists six, and the ticket asks for the buyer's GSTIN to be "validated softly (flag, not block)" - a thing none of the six means.
  Folding it into `gst_mismatch` would put "a character of this registration is mistyped" and "the tax on this bill is not the dated slab's" in one bucket, and head office answers those two with entirely different work.
  The check is the real one (`sell/gstin.py`): fifteen characters, the PAN shape, a state code the GSTN actually issues, and the mod-36 check digit.
  The checksum is what earns it - structure alone passes a transposed pair of digits, which is the commonest way a GSTIN is mistyped and the one that quietly costs the customer their input credit.
  It refuses nothing. The customer is standing at the counter holding the garment.

- **The split is derived from the two characters as typed, even when the GSTIN is malformed.**
  The till printed the customer's copy from those same two characters, offline, minutes earlier (`till/gstin.ts` is a character-for-character mirror of `sell/gstin.py`), and a server that quietly chose differently would put one tax on the paper and another in the books.
  A bad registration is flagged for a human; it is never silently re-taxed.

- **`b2b_tax_kind` rides on every bill the till sends, including B2C ones, where it is `"none"`.**
  Step 11 compares what the till *printed* against what the server derives, which only works if the till says what it printed.
  It is evidence about a piece of paper, not an instruction.

The tax split is presentation, not posting: a single `OUTPUT_GST` account posts whatever the split says, so CGST and SGST on the paper are two halves of one liability (the odd paise goes to SGST, and the two always add back to what the bill charged).

### PUT `/api/auth/me/till-pin` (NEW, #182)

The counter PIN had no way to be set: `db-design.md` §9 adds the column and the dataset ships the hash, and nothing anywhere wrote one - so the manager list was empty by construction and no override could ever be verified.

Auth: `require_section("sell", CAP_APPROVE)` **and** `accounts.till_pin.may_hold_till_pin` - store-bound scope, active, not the break-glass superuser. That is the same sentence the dataset's `managers` section is built from, written once so the two cannot drift.
Body: `{"pin": "4813", "current_password": "…"}`. Response 200 `{"status": "set"}`.

Self-service, and only ever the caller's own row: an override's whole value is that it names who stood at the counter, so an administrator who could set a manager's PIN could authorise a discount in that manager's name.
The password is asked for because a counter is a shared machine and a screen left signed in would otherwise be a way to give yourself somebody else's override.

Hashed with **PBKDF2-SHA256** explicitly, not the project's default bcrypt: the till verifies it offline in a browser, and the Web Crypto API has PBKDF2 and no bcrypt. A hash nothing can verify is not a credential.
PIN rules (invented here, nothing in the design speaks to them): 4 to 6 digits, digits only, not one digit repeated.

| code | HTTP | trigger |
|---|---|---|
| VALIDATION | 400 | not 4-6 digits, not digits, one digit repeated |
| NOT_A_TILL_MANAGER | 403 | holds the rung but is not somebody at a store |
| PASSWORD_WRONG | 403 | the caller's own password does not match |

(A caller who does not hold `sell: approve` is refused by the section gate itself, in DRF's `{"detail": …}` at 403 - the same shape every other capability refusal wears.)

`GET /api/auth/me` gains `has_till_pin` and `may_hold_till_pin` (booleans, never the hash), which `design.md`'s "`/me` untouched" did not anticipate: the card that offers to set a PIN has to know whether you have one and whether you are somebody who may.

**Still deferred, and no longer to #182:** step 1's point 6 - labelling the Dashboard's collections card with the till's last sync time.
The till's clock is in the browser's own database and `TillProvider` is mounted per Sell route on purpose, so a head-office or warehouse login never opens a store's local copy.
Reading it on the Dashboard means moving where the till layer mounts, which is a PWA-shaped decision and belongs with #189.

### GET `/api/sell/register` · POST `/api/sell/register/handover`

GET - the till's boot/recovery state. Auth: sell>=operate, single-store scope.
Response 200: `{"fy": "26-27", "last_accepted_seq": 73, "holes": [61], "series_open": true}`.

POST handover - the deliberate dead-till recovery (grill Q1). Auth: `sell >= CAP_APPROVE` (manager).
Body: `{"reason": "till machine replaced"}`.

1. Gate sell>=approve at this store.
   -> cashier -> `SCOPE_DENIED` (403)
2. Record an `AccessChange`-style audit row (actor, reason, last_accepted_seq at handover).
3. Return `{"resume_from_seq": 74, "unsynced_hint": [61]}` - the new till resumes numbering; the listed holes are re-entered from printed copies via POST sales with `origin: "paper"` and their ORIGINAL till_seq.

| code | HTTP | trigger |
|---|---|---|
| SCOPE_DENIED | 403 | not a manager at this store |
| VALIDATION | 400 | missing reason |

**Amended 30 Jul 2026, after building the GET (#180).**
The POST handover is unbuilt and belongs to #189; three things about the GET are not as sketched above.

- **The response carries `hole_count` as well as `holes`.**
  A till that died on bill 5,000 leaves five thousand holes, and this is on the boot path of every counter every morning.
  `holes` names the first 200 in ascending order, which is as many as a person can act on from printed copies; `hole_count` is the true total, and a screen that shows "249 (1, 2, 3 …)" is telling the truth about both.
- **`last_accepted_seq` counts only bills the kernel actually numbered**, not every `sell_sale` row: `doc_number` is the fact of acceptance, and a draft that never got one is a bill the server has not taken.
  It is `0`, never `1`, for a store that has never billed - the frontier and the next number are two different questions, and answering them with one field would leave one of the two readers wrong.
- **`fy` is the *server's* financial year**, and the till compares it with its own before believing anything else in the body.
  The two clocks straddle 1 April for a few minutes each year, and a till that reconciled a brand-new counter against last year's frontier would jump to bill 5,001 and stay there.
  The `TILL_SCOPE` refusal is the dataset endpoint's, unchanged, for the same reason: one counter's numbering is only ever of use to that counter.

### PUT `/api/sell/held-bills`

Best-effort mirror so the Dashboard sees holds (grill Q13); the till is authoritative.
Auth: sell>=operate, single-store scope.
Body: `{"held": [{"held_uuid": "...", "label": "Mrs Sharma", "held_at": "...", "expires_policy": "today", "payload": {...}}]}` - replace-all for this store.

1. Gate + scope as above.
2. Delete this store's rows not in the list; upsert the rest.
3. Return 200 `{"count": 2}`. No document, no number, no money.

Errors: `VALIDATION`/400, `SCOPE_DENIED`/403.

**Amended 31 Jul 2026, after building it (#185).** Four things.

- **The 403 is `TILL_SCOPE`, not `SCOPE_DENIED`**, for the reason the dataset and register endpoints record: the capability refusal is `require_section`, which answers DRF's `{"detail": ...}`, and the scope refusal means "this login will never be a till", which the till must not retry.
This endpoint shares `till_store` with them, so it shares their vocabulary; `SCOPE_DENIED` is not emitted here either.
- **The upsert matches on `(store, held_uuid)`, and the table's unique key is that pair** rather than db-design's estate-wide `held_uuid unique`.
A key the till mints is unique in practice, but matching a hold by it alone lets one store's push find - and silently reparent - another store's row, taking that store's Dashboard count with it.
The scoped constraint is what makes the scoped lookup the only one the database will accept.
- **`held` is required**, not defaulted to an empty list: "I have nothing parked" clears the store's row, and a body that omitted the key should not be able to say it by accident.
- **The till keeps a sixth field the mirror never carries**, `reviewed_on` - the local day the store last answered "keep this" at day close.
Without it, `expires_policy: kept` would hide a hold for ever after one answer, and grill Q13's "nothing expires silently" would become "nothing is ever asked about again".
The server has no use for the answer, so it stays at the counter that made it.

---

## Step 4 - Offers (till-facing; HO authoring is summary-level here)

### GET `/api/offers` · POST `/api/offers` · PUT `/api/offers/{id}`

GET: `require_section("offers_price", CAP_VIEW)`; filters `live=true`, `store=`, `brand=`. Store logins get read-only rule summaries (what the Offers & Pricing section shows).
POST/PUT: `require_section("offers_price", CAP_MANAGE)` (HO); full rule body per the `offers_offer` columns; status flow draft -> approved (named approver, D5 Q9 gate 1) -> live.
Standard CRUD validation errors (`VALIDATION`/400, `SCOPE_DENIED`/403, `NOT_FOUND`/404); an offer in status `live` cannot be edited in place - it is ended and replaced (documents-snapshot discipline for rules the till already cached).
Detailed authoring screens and their finer endpoints belong to the step 4 tickets; this contract fixes the storage shape and the gate.

### The resolution algorithm (normative, runs identically at till and server)

1. Per item, collect layer-`brand` offers in scope (brand, item_scope, store, dates, no_discount excluded).
2. Compute each candidate's rupee outcome; B2G1 groups qualifying units dearest-first, first X full price, cheapest free.
3. Winner = largest customer benefit; ties -> lower `priority` number wins, then lower `id`. At most one brand offer per item.
4. Layer `storewide` then `bank` apply after, each only if `combinable=true`, computed on the already-reduced base (D5 Q13).
5. Evidence per line: winner id, layer, beaten candidates + amounts, saved_paise (feeds B3 and the daily check).
Deterministic by construction: same cart, same rulebook -> same paise, at till and at server (grill Q11).

---

## Step 5 - Returns & customer search

### POST `/api/sell/returns`

Plain return, no exchange: Return document + CreditNote, never cash (grill Q7).
Auth: sell>=operate; **manager override mandatory on every plain return** (the manager's tap).

Body: `{"idempotency_uuid": "...", "store": "DEO", "original": {"fy": "26-27", "till_seq": 40}, "lines": [{"original_line": 3, "qty": 1, "reason": "defect", "condition": "damaged"}], "override": {"user_id": 7}, "window_override": false}`.

1. Gate + single-store scope.
   -> mismatch -> `SCOPE_DENIED` (403)
2. Idempotent replay check (as sales).
3. Resolve original Sale + lines; refund per line = what was actually paid (D2); qty must not exceed unreturned qty on that line.
   -> original not found -> `ORIGINAL_NOT_FOUND` (404)
   -> qty exceeds -> `ALREADY_RETURNED` (422)
4. Window check against policy data (days since billed_at): outside window requires `window_override=true` (still the manager) and is flagged.
5. `override.user_id` must hold sell>=approve at this store (every plain return).
   -> missing/invalid -> `OVERRIDE_REQUIRED` (422)
6. Create Return (draft) -> post(): allocates `SRT` number server-side (returns need the network by design - they are rare and risky; the till disables plain return while offline, exchange still works in-bill).
7. Issue CreditNote (CRN series): value = Σ refunds; expiry from policy data.
8. Postings fire (§Postings): stock in (good->available / damaged->quarantine), revenue+GST reversal, SOR accrual reversal per the original piece's model, Cr credit-note liability.
9. Return 201 `{"doc_number": ".../SRT/5", "credit_note": ".../CRN/9", "value_paise": 129900}`.

| code | HTTP | trigger |
|---|---|---|
| VALIDATION | 400 | malformed |
| SCOPE_DENIED | 403 | store/capability |
| ORIGINAL_NOT_FOUND | 404 | no such original bill |
| ALREADY_RETURNED | 422 | line already fully returned |
| OVERRIDE_REQUIRED | 422 | manager evidence missing (any plain return) or window exceeded without window_override |

### GET `/api/sell/sales`

Customer search / reprint (E1, E2). Auth: sell>=view; store-scoped.
Query: `mobile=` | `name=` | `doc=` (fy/seq or full doc_number); at least one.
Response 200: `[{doc_number, billed_at, customer_name, net_paise, lines_summary}]`, cap 50.
Detail: GET `/api/sell/sales/{doc_number}` -> full read-only bill for reprint. **No mutation endpoint exists on a posted Sale anywhere in this contract** (A7).

Errors: `VALIDATION`/400 (no criterion), `SCOPE_DENIED`/403, `NOT_FOUND`/404 (detail only).

**Amended 31 Jul 2026, after building the screen (#185).** The detail carries `store_gstin`.
A reprint reached from customer search has no till behind it to borrow a registration from - the dataset is a *counter's* copy, and whoever is looking an old bill up may not be standing at one - and a tax invoice without a GSTIN on it is not a tax invoice.
Nothing else about the read shape moved, and it is still read-only: there is no writer in `sell/views.py` for a screen to call.

**Amended 31 Jul 2026 again, after building the B2B corner (#187).** The detail carries `irn`.
It reads off the queue row beside the bill (`sell_irnqueue.irn`) and is blank on every B2C bill and on a B2B bill head office has not raised yet - which is most of a bill's first month.
A reprint prints the reference when there is one and "IRN to follow" when there is not, which is what the counter's own copy said when it came off the printer.

---

## Step 5a - The IRN queue (NEW, #187)

Not in the original contract, which recorded the queue as a table (`db-design.md` §`sell_irnqueue`, "surfaces in an HO work queue") and gave it no endpoint.
A queue nothing can read and nothing can leave is a table, not a queue, so the two calls below are what make grill Q8's thirty-day clock a duty somebody can actually discharge.

### GET `/api/sell/irn-queue`

Auth: **`require_section("money", CAP_MANAGE)`** - and that is the one gate in `sell` that is not the `sell` section's.
Raising an IRN is a statutory filing, not shop-floor work, and the `sell` ladder cannot express that audience: `sell: operate` is the *store*, which would put a GST duty on a cashier's sidebar, and `sell: manage` is the IT administrator alone, who holds no money at all on the ratified sheet.
`money: manage` is exactly Owner and Accounts, the people who file the returns. Nothing on the ratified sheet moves to make this true.

Store-scoped by the bill's own store (`scope_by_store` on `sale__store_id`), so the top-bar unit switcher narrows it exactly as every other document list.
Query: `status=pending` (default) | `generated` | `failed` | `all`.

Response 200: `{"today": "2026-07-31", "rows": [...], "pending_count": 3, "overdue_count": 1}`.
Each row: `id, doc_number, store_code, store_name, billed_at, buyer_gstin, customer_name, b2b_tax_kind, net_paise, gst_paise, due_on, days_left, status, irn, handled_by_name, handled_at`.
Ordered by `due_on` then id - the oldest deadline is the next thing to do.
`days_left` is computed against the response's single `today` rather than per row, so thirty rows cannot disagree about what day it is because the clock ticked over mid-response; it is negative once the deadline has gone by.
Both counts are over the *pending* rows whatever is being listed: they are the header a clerk reads to know whether anything is on fire, and a filter must not move it.
The pending list is never truncated (it is the work); the settled tail behind it is capped at 200 (it is history, and history is what gets long).

Errors: `VALIDATION`/400 (a status nothing recognises), capability refusal 403 (DRF's `{"detail": ...}`, as every sibling gate).

### PUT `/api/sell/irn-queue/{id}`

Body: `{"status": "generated"|"failed", "irn": "..."}`; sets `handled_by`/`handled_at` from the caller and the clock.
One way only: `pending`/`failed` -> `generated` or `failed`, never back to `pending` - "we tried and it did not work" is a fact worth keeping.

| code | HTTP | trigger |
|---|---|---|
| VALIDATION | 400 | not one of the two statuses, or `generated` with no reference |
| NOT_FOUND | 404 | the row is outside the caller's stores (a 403 would confirm the bill exists) |
| IRN_ALREADY_RECORDED | 409 | the row already carries an IRN |

Nothing here can touch the Sale (A7). The row beside it is a fact about a filing, not a fact about a sale.

---

## Step 6 - Cash summary

### GET `/api/store/cash-summary`

Auth: `require_section("money", CAP_VIEW)`; store-scoped; `?date=` (default today).
Response 200: `{"date": "2026-07-30", "modes": {"cash": 0, "card": 0, "upi": 0, "credit_note": 0}, "bills": 12, "returns": 1, "credit_notes_issued_paise": 0, "flags_open": 2}` - from CashLedgerEntry receipt rows + tender aggregates; read-only.
The store's day-close confirmation (I3, store open/close) is deliberately NOT in this contract; it is its own designed flow, sequenced after.

---

## Access matrix editor (rider from grill Q8)

Amended 30 Jul 2026, after building it (#173). Three things in this section were wrong and are corrected below: the paths, the response to a PUT, and when a change takes effect.
The endpoints live under `/api/auth/admin/`, where the whole accounts admin surface already sits; `/api/accounts/` is a prefix this project does not mount.

### GET `/api/auth/admin/access-matrix`

Auth: `require_section("setup", CAP_MANAGE)` **and** the access-administrator floor (Owner or IT Admin), the same pair every sibling admin endpoint carries. Floor rule 4 caps `setup: manage` at those two roles anyway, so the pair is belt and braces against a legacy row.
Response: roles x sections grid from stored `Role.section_access`, the capability ladder with its wording, all four ratified rules, and per role a `locked` map of the floor cells with the ceiling and the reason (rendered greyed-out).

### PUT `/api/auth/admin/roles/{code}/access`

Auth: as above.
Body: `{"section_access": {"sell": {"capability": "operate"}, ...}}` - full replacement for one role. A section left out is removed, never kept.

1. Gate setup>=manage, and the access-administrator floor.
2. Validate every section code and capability value.
   -> unknown code/capability -> `VALIDATION` (400)
3. Check the four floor rules (code constant): a change that crosses a floor is refused cell-by-cell.
   -> floor crossed -> `FLOOR_LOCKED` (422), body names the cell and the reason
4. **Propose, do not write.** Floor rule 4 says users and roles change "never by one person alone", and `section_access` is the role. The edit becomes an `AccessChange` carrying the per-cell diff (who, when, role, section, old -> new) plus the row it was written against, and a second Owner or IT Admin applies it through the existing approvals machinery.
   -> nothing actually moved -> 200 `{"status": "unchanged"}`, and nobody is asked to approve nothing
5. Return **202** with the approval to clear and the cell diff. The floor is checked again at apply time, and the change is refused if that role moved since the proposal was written.

| code | HTTP | trigger |
|---|---|---|
| VALIDATION | 400 | unknown section/capability, or a setting this endpoint does not have |
| SCOPE_DENIED | 403 | lacks setup manage, or is not Owner / IT Admin |
| NOT_FOUND | 404 | unknown role code |
| FLOOR_LOCKED | 422 | edit crosses a hard-coded money floor |

**Timing: an approved change is live immediately (Anand's ruling, 30 Jul 2026).** This section previously said a change waited for the affected person's next login. It does not, and must not: the gate resolves every request against the stored row. Anand's reasoning - the mid-shift surprise is rare and two people had to agree to it, whereas a right you cannot withdraw until someone next logs out stays open for a whole shift, and a till may not log out for days. **Everything live, updated instantly.**

The contract tests move with this: gates are asserted against the STORED matrix (whatever it says), floors asserted unconditionally.

---

## Postings (extends the posting catalog; nothing parallel)

All value legs go through `post_entries` (balanced-or-fail, integer paise); all stock legs through the stock ledger with the two new kinds.
New GL accounts per `db-design.md`.
Actor: the till login (store-scoped) under the registered SAL/SRT floor exception - amounts are machine-computed, never store discretion.

### Sale (docstatus draft -> submitted, on server accept)

Stock ledger, all four models: `sale_out` -qty per priced line at `(barcode, season)`; `sale_return_in` +qty per exchange return leg (condition=good -> available; damaged -> quarantine projection).

Value GL - **event A, the money side** (posts for every bill, including sold-before-inward lines):

| Leg | Dr | Cr |
|---|---|---|
| Dr CASH / CARD_CLEARING / UPI_CLEARING per tender split | tender amounts | |
| Dr CREDIT_NOTE_LIABILITY (credit-note tender = the liability is extinguished) | note amount | |
| Cr SALES_REVENUE (net of GST, post-discount) | | Σ base |
| Cr OUTPUT_GST (per dated slab, back-calculated from MRP-inclusive, half-up) | | Σ gst |
| Dr/Cr ROUND_OFF (the rounding line) | balances to zero | |

Dimensions on every leg: store, state_gstin, brand, season (snapshotted).

Value GL - **event B, the cost side** (per priced line; deferred for sold-before-inward until GRN/PT prices the cohort, then posted as its own balanced event dated that day, linked `against_voucher` = the Sale):

| Model | Legs |
|---|---|
| Outright / Correction | Dr COGS (unit_cost x qty) · Cr INVENTORY |
| SOR / Consignment | Dr COGS (settlement rate x qty) · Cr VENDOR_PAYABLE (party=vendor) - **the liability accrues now, at the settlement rate, never the discounted price**; plus the memo reversal Dr SOR_CONTRA · Cr SOR_STOCK |

No leg ever posts at zero value (Rule 5); an unpriced line waits in `sell_deferredcosting`, visible on the Dashboard, aged by the daily check.
GST recognition for SOR/Consignment (`gst_recognised` once-only, F9) stays CA-gated: event B's vendor accrual posts, the Tally-side GST voucher treatment follows the CA ruling before live money.

### Exchange (inside a Sale)

Return leg: reverse of the original line - Stock `sale_return_in`; Dr SALES_REVENUE + Dr OUTPUT_GST (what was actually paid, D2) · Cr the tender/net position; cost side reversed per the ORIGINAL piece's model (SOR: Dr VENDOR_PAYABLE reversing the accrual · Cr COGS; owned: Dr INVENTORY · Cr COGS).
Sale legs: normal.
One balanced document; net cash movement equals the customer's actual payment. Net negative -> the difference posts Cr CREDIT_NOTE_LIABILITY (a CRN is issued), cash never exits.

### Plain Return (SRT, docstatus submitted)

Stock `sale_return_in` (good -> available / damaged -> quarantine).
Value: Dr SALES_REVENUE (contra) + Dr OUTPUT_GST · Cr CREDIT_NOTE_LIABILITY (the note issued); cost side reversed per the original piece's model exactly as the exchange return leg.
No cash leg exists on this document by construction (grill Q7).

### Credit note lifecycle

Issue (by Return/Exchange): the Cr CREDIT_NOTE_LIABILITY leg above; the CRN document carries value/remaining.
Redeem (by a Sale tender): Dr CREDIT_NOTE_LIABILITY inside the Sale's event A.
Expiry (policy data): a periodic job posts Dr CREDIT_NOTE_LIABILITY · Cr SUSPENSE per expired note with a reason code (breakage recognition account to be named with the CA before live money; SUSPENSE keeps it visible, not hidden).

### Cancellation

A submitted Sale/Return cancels only by the kernel's reversing transition (correct-by-reversal, period-locked); no edit path exists.
