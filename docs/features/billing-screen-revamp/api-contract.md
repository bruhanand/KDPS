# Billing screen revamp - Phase 2: API contract

Scope: the server-visible part of the revamp.
Most of this feature is frontend (the fixed frame, payment card, autosave, undo, sounds, GST badge, floating prompts) and deliberately has **no API surface**; this contract covers the three endpoints that change and the seams that exist only on the till.
Base behaviour of the touched endpoints is specified in `docs/features/pos-store-front/api-contract.md`; this document updates those endpoints in place - where the two disagree, this one wins.

No new endpoints are created.
No endpoint is removed.

---

## 1. `GET /api/sell/dataset` (updated: customers join the till's world)

- **Auth/scope**: unchanged - `sell: operate`, till-scoped (`TILL_SCOPE` refusal outside the till's store).
- **Query params**: unchanged - `since` (opaque cursor; unreadable since = full bootstrap).

### Response change

One new top-level section, riding the existing single-timestamp `Sync` machinery:

```json
{
  "...": "existing sections unchanged (items, stock, offers, credit_notes, salesmen, ...)",
  "customers": [
    {"mobile": "9835211442", "name": "Sunita Devi", "gstin": ""}
  ]
}
```

- Delta rules are the standard ones: full list on bootstrap, rows with `updated_at` after the cursor on a delta pull.
- **No `deleted.customers` section**: customer rows are never deleted in v1 (there is no merge/cleanup flow yet); the section is added only when one exists.
- Rows are all-KDPS (grill Q6): the customer list is deliberately **not** store-scoped, unlike stock - a Deoghar regular must be recognised in Ranchi.
- The till stores names and numbers only; no purchase history is shipped.

### Business logic (added step in `build_dataset`)

```
1. (existing) build Sync with one timestamp for the whole answer
2. (new) customers = Customer rows, all stores, updated_at > since (all rows on bootstrap)
3. (existing) assemble payload; customers ride under the same cursor
```

### Error table

Unchanged: `TILL_SCOPE` / 403 / caller has no till store.

---

## 2. `POST /api/sell/sales` (updated: UPI stamp in, customer upsert out)

- **Auth/scope**: unchanged - `sell: operate`, till-scoped; idempotency-keyed offline sync.

### Request body change

Each tender row with `mode: "upi"` now carries a stamp (grill Q5):

```json
{
  "tenders": [
    {"mode": "cash", "amount_paise": 84800},
    {"mode": "upi", "amount_paise": 200000,
     "upi_state": "confirmed", "upi_reference": "417223918811"}
  ]
}
```

- `upi_state`: `"confirmed"` (the bank answered through the QR charge flow) or `"manual"` (the cashier vouched - soundbox, static QR, offline).
  **Required when `mode` is `upi`; forbidden on every other mode.**
- `upi_reference`: the acquirer's transaction reference.
  **Required when `upi_state` is `confirmed`; forbidden otherwise** (a manual entry has nothing trustworthy to record; an empty string on a confirmed tender is a validation error).
- Until the hardware slice lands, the till only ever sends `manual` - the mock adapter never reports `confirmed` to the server.

### Response

Unchanged (the accepted bill; retry with the same idempotency key returns the same bill).

### Business logic (the changed steps, numbered against the existing accept pipeline)

```
1. (existing) validate envelope, lines, idempotency key
2. (new, inside tender validation) for each tender row:
   -> mode == "upi" and upi_state missing or not in {confirmed, manual} -> VALIDATION
   -> mode != "upi" and (upi_state or upi_reference present) -> VALIDATION
   -> upi_state == "confirmed" and upi_reference blank -> VALIDATION
   -> upi_state == "manual" and upi_reference present -> VALIDATION
3. (existing) tenders must sum to net -> VALIDATION (unchanged)
4. (existing) plan tenders, write Sale, write SaleTender rows
   (new) each UPI tender row persists upi_state + upi_reference
5. (existing) apply tenders, flags, credit notes, deferred costing - unchanged
6. (new, after the sale is committed) customer upsert - never blocks:
   a. mobile = digits of payload customer.mobile; skip the whole step when blank
   b. get-or-create masters.Customer by mobile
   c. payload name non-blank and different -> overwrite (latest wins)
   d. payload gstin non-blank -> overwrite
   e. any failure in 6a-6d is logged and swallowed - the bill is already
      printed and in the customer's hand; a master-data hiccup must not
      refuse it (Rule 5). No errorCode exists for this step by design.
7. (existing) respond with the accepted bill
```

### Error table

| errorCode | HTTP | Trigger |
|---|---|---|
| `VALIDATION` | 400 | `upi_state` missing/invalid on a UPI tender |
| `VALIDATION` | 400 | `upi_state`/`upi_reference` present on a non-UPI tender |
| `VALIDATION` | 400 | `upi_state=confirmed` with a blank `upi_reference` |
| `VALIDATION` | 400 | `upi_state=manual` with a `upi_reference` |
| (existing) | 400/403/... | all existing accept refusals unchanged |

House style kept: coarse `VALIDATION` code, precise human message (`first_message` pattern).

---

## 3. `GET /api/storefront/cash-summary` (updated: the UPI split surfaces)

- **Auth/scope**: unchanged.

### Response change

The per-day collections keep the existing `upi` total (nothing downstream breaks) and gain a sibling breakdown:

```json
{
  "collections": {"cash": 0, "card": 0, "upi": 200000, "credit_note": 0},
  "upi_split": {"confirmed": 0, "manual": 200000}
}
```

- `upi_split.confirmed + upi_split.manual == collections.upi` by construction (both derive from the same tender rows in one query).
- This is the grill Q5 control: a pattern of manual UPI entries is visible per till, per day, the same evening.
- The store dashboard's collections tile is unchanged (it reads the totals); only the cash-summary day view gains the split.

### Business logic (added step)

```
1. (existing) collect the day's bills, sum tenders by mode
2. (new) sum UPI tenders again grouped by upi_state into upi_split
```

### Error table

Unchanged.

---

## 4. Till-only seams (no API, recorded so nobody looks for one)

- **Payment adapter**: the UPI charge card talks to a `PaymentAdapter` interface (same shape as the print adapter) with one implementation for now: a mock that walks Generating → Awaiting → Success/Failed/Unknown on a timer and never returns `confirmed` to the real bill. The hardware slice later adds a real adapter and, only then, any charge-initiation API this contract does not define.
- **Customer typeahead**: reads the till's local `customers` table only. There is deliberately no search endpoint - offline-first (grill Q6).
- **Autosave draft, undo stack, scan sounds, GST badge/breakup, quantity-increment-on-rescan, floating prompts**: till-local behaviour, no server involvement. The draft never syncs; only Save & Print does.

---

## 5. Postings

**None.**
This feature writes no ledger: tenders post exactly as before, the UPI stamp is descriptive data on the tender row, and the customer master is master data outside the money path.
The cash-summary split reads existing tender rows.
Phase 0's money-slice call (**No**) stands; nothing here extends the posting catalog.
