# POS counter redesign - Phase 2: API contract

Drafted 2 Aug 2026 against `grill-decisions.md`.
Four endpoints change or arrive; one retires; nothing posts.
House error style throughout: refusals are `refusal_body` codes (`{"error": {"code", "message"}}`), auth failures are the standard 401/403.

## 1 · `GET` + `PUT /api/sell/policy` - new

The owner's dials for the counter, in-app instead of Django admin (grill Q5: "configurable through the admin section, owner section").

**Auth:** GET `require_section("sell", CAP_VIEW)`; PUT `require_section("sell", CAP_MANAGE)`.
Per the one-gate rule, no role is named in code. Today `sell: manage` is held by IT admin only; giving the Operations Head and the owner this dial is an **access-matrix data change** (their `sell` cell raised to `manage`), made in-app under the two-admin flow - recorded here, not coded here.

**GET response `200`:**

```json
{
  "manual_discount_cap_percent": "10.00",
  "manual_discount_on_offer_lines": false
}
```

**PUT request** - both fields required (the row is one decision, sent whole):

| Field | Type | Rule |
|---|---|---|
| `manual_discount_cap_percent` | string, two decimals | `0.00` - `100.00` |
| `manual_discount_on_offer_lines` | boolean | may an offer-discounted line take manual discount on top |

**PUT success:** `200`, the saved shape (same as GET).

**Errors:**

| errorCode | HTTP | Trigger |
|---|---|---|
| `VALIDATION` | 400 | missing field, non-decimal cap, cap outside 0-100 |

**Business logic (PUT):**

1. Parse body; both fields present and typed.
   -> malformed -> `VALIDATION`
2. `SellPolicy.current()` (the singleton, created if absent).
3. Write both fields; save. Cap stored as `Decimal` two-places.
4. Return the saved shape.

The percent travels as a **string** both ways, same reason `_policy()` gives for tax rates: the till multiplies by it, and `7.499999` puts the counter and the server on opposite sides of a cap.

## 2 · `POST /api/sell/sales` (accept pipeline) - changed

Three steps change, one step dies. Everything else - idempotent replay, bill-number guard, customer upsert, flags - is untouched.

**Step 3 `_check_totals` - the equal-or-up gate (grill Q3b).**
Today a bill may net negative (tenders = 0, change-note issued at step 8). Now:

```
3. Sum lines against declared totals (unchanged arithmetic).
   -> any figure disagrees -> TENDER_MISMATCH (422, unchanged)
   -> totals.net_paise < 0 -> EXCHANGE_SHORT (422, new)
3b. tendered must equal net_paise exactly (the max(net, 0) floor goes).
   -> mismatch -> TENDER_MISMATCH (422, unchanged)
```

**Step 6 `_check_discount_policy` - the absolute cap (grill Q5/Q5b).**
The manager-override door for discounts closes. Per sale (non-return) line:

```
6. credit = rulebook's own resolution for the line (unchanged);
   manual = given - min(credit, given).
   -> manual > 0 AND credit > 0 AND NOT policy.manual_discount_on_offer_lines
      -> DISCOUNT_ON_OFFER_LINE (422, new)
   -> manual > cap% of (mrp_paise x qty)
      -> DISCOUNT_OVER_CAP (422, new; replaces OVERRIDE_REQUIRED - no override is read)
   The rulebook-drift door (a cited rule re-run server-side) stays exactly as is.
```

**Step 7 `_plan_tenders` - the credit-note tender dies (grill Q3b).**
`mode: "credit_note"` leaves the serializer's vocabulary; a payload carrying it is refused `VALIDATION` (400) before the pipeline runs. `CREDIT_NOTE_INVALID` and the note-recognition walk are removed.

**Step 8 `_issue_change_note` - removed.** Dead by step 3's refusal; no code path can reach a negative net.

**The `manager_override` request field stays** - its one remaining job is the late-exchange window override (`return_window_days`, untouched by any ruling). This is the answer to the grill's "verify what still rides on the PIN": window overrides do; discounts and credit notes no longer exist as override kinds. `_authorised_kind` shrinks accordingly.

**Changed error table (this endpoint, deltas only):**

| errorCode | HTTP | Trigger | Status |
|---|---|---|---|
| `EXCHANGE_SHORT` | 422 | `totals.net_paise < 0` - the pieces coming back outweigh the pieces going out | new |
| `DISCOUNT_OVER_CAP` | 422 | manual share of a line's discount exceeds cap% of MRP x qty | new |
| `DISCOUNT_ON_OFFER_LINE` | 422 | manual discount on a rulebook-discounted line while the allowance is off | new |
| `VALIDATION` | 400 | tender `mode: "credit_note"` in the payload | new trigger |
| `OVERRIDE_REQUIRED` | 422 | *(discount flavour)* | **retired** |
| `CREDIT_NOTE_INVALID` | 422 | | **retired** |

A refusal here is a **backstop against a tampered or stale till**, not the normal path: the counter enforces the same three rules offline from the same dataset dials, so an honest till cannot produce these payloads. A refused bill lands in the till's failed-sync queue for a human, as today.

## 3 · `POST /api/sell/returns` - retired

The standalone plain return (SRT + credit note) has no surface left: no cash refunds, no credit notes, returns exist only as exchange legs inside a bill (grill Q2/Q3/Q3b).
Route and view removed; `CanTakeReturns` removed; the `Return`/`ReturnLine` models and any historical rows **stay** (append-only history), and `refunds.returned_so_far` keeps reading both tables so the double-refund ceiling still holds over history.

## 4 · `GET /api/sell/dataset` - changed

| Section | Change |
|---|---|
| `credit_notes` | **removed** - nothing issues, nothing redeems |
| `deleted.credit_notes` | **removed** |
| `policy` | gains `"manual_discount_on_offer_lines": boolean` beside the cap string |
| everything else | unchanged, cursor semantics unchanged |

The till treats an absent section as empty on bootstrap (existing behaviour), so a new server serving an old till is harmless; a new till against an old server bootstraps the flag as `false` (the safe end).

## 5 · `GET /api/sell/sales` - unchanged, noted

The existing bill search (`mobile` / `name` / `doc` params) is find-bill **door 3** for the counter's return mode (grill Q2). No contract change; the counter simply calls it from a new place. Offline, doors 1-2 read the till's own queue and shelf; door 3 requires the line, and says so.

## Postings

**None.** No ledger, no `post_entries`, no docstatus transition changes.
The equal-or-up gate only narrows the accepted range of an existing document (net >= 0); the Sale's existing postings are untouched, and the store-day Tally voucher still nets exchanges inside the sale exactly as the posting catalog records.
The credit-note *model* keeps its posting behaviour for historical rows; no new row is ever created.
