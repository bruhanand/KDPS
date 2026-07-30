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

### PUT `/api/sell/held-bills`

Best-effort mirror so the Dashboard sees holds (grill Q13); the till is authoritative.
Auth: sell>=operate, single-store scope.
Body: `{"held": [{"held_uuid": "...", "label": "Mrs Sharma", "held_at": "...", "expires_policy": "today", "payload": {...}}]}` - replace-all for this store.

1. Gate + scope as above.
2. Delete this store's rows not in the list; upsert the rest.
3. Return 200 `{"count": 2}`. No document, no number, no money.

Errors: `VALIDATION`/400, `SCOPE_DENIED`/403.

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
