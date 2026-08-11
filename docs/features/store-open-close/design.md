# Store open/close - design

Phase 2 of the dev process (`docs/agents/phases/design.md`).
Input: `spec.md` beside this file. Issue #296.
**Money slice**, so this phase was never skippable and every posting below carries both legs.

---

## Summary

Four new documents in `storefront`, which gains its first models: `DayOpen` (`DOP`), `StoreCashOut` (`CSO`), `DayClose` (`DCL`) and `DayVarianceCorrection` (`DVC`).
Each is a `core.documents.Document`, so each takes a gap-free number, walks the `draft → submitted` FSM, and posts through `post_entries` or posts nothing at all.

The drawer's arithmetic is `expected = opening counted + the day's cash tenders - the day's cash out`, and the day's cash tenders come from `storefront.day.money_for`, which already exists and which the Day Summary already reads.
Nothing recomputes the day a second way.

Two new GL accounts carry the money: `CASH_SHORT_OVER` for the drawer difference at both ends of the day, and `CASH_IN_TRANSIT` for cash handed to the bank before the credit lands.
Both must also be added to `finledger.health.ACCOUNTS`, or `test_books_health_covers_every_gl_account` fails.

One new screen at `/money/day`, four new endpoints under `/api/store/day`, and two existing endpoints updated in place.

### Three decisions this phase took that the spec did not

**The screen lives in Money, not Sell.**
`spec.md` put it under Sell with a deep link from Money.
That breaks the one-gate contract: the nav item's declared section and rung are the pair the server mirrors, and every endpoint here is gated on `money`.
So the item is **Money → "Open / Close Day"** at `minCapability: "operate"`, which `store_person` holds ("Expenses only (create)"), and Sell carries a `deepLink: true` entry, which owns no route and no access rule.

**The variance raises a `ContinuityFlag`, not an `Approval`.**
`spec.md` FR12 says the close completes whether or not anybody approves.
`approvals.services.request_approval` exists to make a document "born pending" and gate it, so an Approval that gates nothing is a gate wearing the wrong name.
`ContinuityFlag` is documented as exactly this: "something a human should look at, on a bill that was taken anyway", with `resolved_by` and `cleared_note` as the acknowledgement.
**The `approvals` app therefore drops out of the blast radius entirely.**

**Held-bill answers get mirrored to the server after all.**
`till/held.ts::mirrorRow` deliberately strips `reviewed_on`, with the comment "the day-close answer is the counter's own bookkeeping".
That was written when no day close existed.
It does now, it is server-side and online-only (NFR2), and it cannot enforce FR13 against a fact it is not told.
So `reviewed_on` and `kept_count` join the mirror, and `mirrorRow` stops stripping them.

## Endpoints

### `GET /api/store/day`

The whole Open / Close Day screen, for one store and one day.

**Auth:** `IsAuthenticated` + `require_section("money", CAP_VIEW)`.
**Scope:** the store comes from `storefront.dashboard.resolve_store`, narrowed by the `X-KDPS-Unit` switcher exactly as the Dashboard and cash summary are. `?store=` narrows within the active unit, never overrides it.

**Query params**

| Param | Type | Required | Meaning |
|---|---|---|---|
| `store` | string | optional | Store code, narrowing within the active unit. |
| `date` | string `YYYY-MM-DD` | optional | Defaults to `timezone.localdate()` (IST). |

**200 response**

```jsonc
{
  "store": "DEO",
  "date": "2026-08-11",
  "state": "not_opened" | "open" | "closed",
  "float_paise": 500000,
  "open": null,                       // or the block below
  "close": null,                      // or the block below
  "expected_now_paise": 4835000,      // opening + cash in - cash out, as it stands
  "cash_in_paise": 4520000,           // storefront.day.money_for(...).collections["cash"]
  "cash_out_paise": 185000,
  "cash_outs": [ {"id": 12, "doc_number": "26-27/DEO/CSO/3",
                  "amount_paise": 185000, "reason_code": "bank_deposit",
                  "note": "", "made_by_name": "Ravi"} ],
  "other_tenders": {"card": 910000, "upi": 1240000, "credit_note": 0},
  "holds_to_review": [ {"held_uuid": "…", "label": "blue kurta",
                        "held_at": "2026-08-09T12:04:00Z", "kept_count": 1} ],
  "variance_threshold_paise": 50000,
  "back_close_limit_days": 7,
  "may_close": true,
  "may_back_close": false             // true only when the caller holds money: manage
}
```

`open` when present: `{"doc_number", "counted_paise", "expected_paise", "variance_paise", "source", "opened_by_name", "reason"}`.
`close` when present: the same shape plus `{"cash_in_paise", "cash_out_paise", "back_close", "closed_by_name", "corrections": [{"doc_number", "amount_paise", "reason_code", "created_at"}]}`.

**Errors**

| errorCode | HTTP | Trigger |
|---|---|---|
| `SCOPE_DENIED` | 403 | No store resolved: no unit picked, a store outside the switcher, or a brand-scoped caller. |
| `VALIDATION` | 400 | `date` is not a parseable date. |

**Business logic**

```
1. Parse `date`; default to timezone.localdate().
   -> not a date -> VALIDATION
2. Resolve the store through resolve_store(user, ?store).
   -> pick.store is None -> SCOPE_DENIED
3. Read the DayOpen for (store, day), submitted only. Absent -> state "not_opened".
4. Read the DayClose for (store, day), submitted only. Present -> state "closed", else "open" when 3 found one.
5. Read the day's cash tenders via storefront.day.money_for(store, day).collections.
6. Sum submitted StoreCashOut for (store, day) and list them.
7. expected_now = (open.counted_paise if open else store.opening_float_paise) + cash_in - cash_out.
8. List holds to review: sell_heldbill for the store where held_at::date < day and coalesce(reviewed_on,'0001-01-01') < day.
9. may_back_close = user_can(user, "money", CAP_MANAGE).
10. Return the body.
```

---

### `POST /api/store/day/open`

**Auth:** `IsAuthenticated` + `require_section("money", CAP_OPERATE)`.
**Scope:** as above.

**Body**

| Field | Type | Required | Meaning |
|---|---|---|---|
| `store` | string | optional | Narrows within the active unit. |
| `date` | string `YYYY-MM-DD` | optional | Defaults to today (IST). |
| `counted_paise` | integer | **required** | What is in the drawer. `>= 0`. |
| `reason` | string | optional | Free text, max 240. |
| `idempotency_uuid` | uuid | **required** | Retry key, per `Document`. |

**201 response:** the `open` block from `GET /api/store/day`, plus `"created": true`. A replay of a known `idempotency_uuid` returns **200** with `"created": false` and the same block.

**Errors**

| errorCode | HTTP | Trigger |
|---|---|---|
| `SCOPE_DENIED` | 403 | No store resolved (as above). |
| `VALIDATION` | 400 | Bad date, missing or non-integer `counted_paise`, `counted_paise < 0`, missing `idempotency_uuid`. |
| `DAY_IN_FUTURE` | 400 | `date` is after today (IST). |
| `DAY_ALREADY_OPEN` | 409 | A submitted `DayOpen` exists for `(store, date)`. |
| `DAY_ALREADY_CLOSED` | 409 | A submitted `DayClose` exists for `(store, date)`. |

**Business logic**

```
1. Replay check: a DayOpen with this idempotency_uuid already exists -> return it, 200, created=false.
2. Validate the body.
   -> bad/absent counted_paise, negative, bad date, no uuid -> VALIDATION
3. Parse the day; refuse a future one.
   -> date > today (IST) -> DAY_IN_FUTURE
4. Resolve the store.
   -> pick.store is None -> SCOPE_DENIED
5. Refuse a day already closed.
   -> a submitted DayClose exists for (store, day) -> DAY_ALREADY_CLOSED
6. Refuse a second open.
   -> a submitted DayOpen exists for (store, day) -> DAY_ALREADY_OPEN
7. expected = previous submitted DayClose's counted_paise for this store, by day desc;
   where none exists, store.opening_float_paise.
8. variance = counted_paise - expected.
9. Open a transaction. get_or_create the VoucherSeries for (fy, store.code, "DOP").
10. Create the DayOpen draft (source="counted", opened_by=user) and post() it, minting the number.
11. Where variance != 0, post the two legs (see Postings) and write the mirroring CashLedgerEntry.
    Where variance == 0, post nothing: post_entries refuses fewer than two legs, and a zero
    variance is not an event.
12. Commit. Return 201.
```

An `IntegrityError` on the `(store, day)` unique constraint, from two people opening at once, is caught outside the transaction and re-read exactly as `sell.services.accept.accept_sale` does: the honest answer to "somebody got there first" is the answer they got, so it returns `DAY_ALREADY_OPEN` naming who opened it.

---

### `POST /api/store/day/cash-out`

**Auth:** `IsAuthenticated` + `require_section("money", CAP_OPERATE)`.

**Body**

| Field | Type | Required | Meaning |
|---|---|---|---|
| `store` | string | optional | Narrows within the active unit. |
| `date` | string `YYYY-MM-DD` | optional | Defaults to today (IST). |
| `amount_paise` | integer | **required** | `> 0`. |
| `reason_code` | string | **required** | `bank_deposit` or `other`. |
| `note` | string | conditional | Required, `>= 10` characters, when `reason_code == "other"`. Max 240. |
| `idempotency_uuid` | uuid | **required** | Retry key. |

**201 response:** the cash-out row shape from `GET /api/store/day`, plus `"created": true`. Replay returns 200, `created: false`.

**Errors**

| errorCode | HTTP | Trigger |
|---|---|---|
| `SCOPE_DENIED` | 403 | No store resolved. |
| `VALIDATION` | 400 | Bad date, `amount_paise` absent/non-integer/`<= 0`, unknown `reason_code`, missing `idempotency_uuid`. |
| `REASON_REQUIRED` | 400 | `reason_code == "other"` and `note` is shorter than 10 characters. |
| `DAY_IN_FUTURE` | 400 | `date` is after today (IST). |
| `DAY_ALREADY_CLOSED` | 409 | A submitted `DayClose` exists for `(store, date)`. Money cannot leave a drawer somebody has already counted. |

**Business logic**

```
1. Replay check on idempotency_uuid -> return the existing row, 200, created=false.
2. Validate amount, reason_code, uuid, date.
   -> any invalid -> VALIDATION
3. Where reason_code == "other", require a note of 10+ characters.
   -> shorter -> REASON_REQUIRED
4. Refuse a future day.
   -> date > today (IST) -> DAY_IN_FUTURE
5. Resolve the store.
   -> pick.store is None -> SCOPE_DENIED
6. Refuse a closed day.
   -> a submitted DayClose exists for (store, day) -> DAY_ALREADY_CLOSED
7. Open a transaction. get_or_create the VoucherSeries for (fy, store.code, "CSO").
8. Create the StoreCashOut draft (made_by=user) and post() it.
9. Post the two legs (see Postings) and write the mirroring CashLedgerEntry (PAYMENT, -amount,
   account CASH, store set).
10. Commit. Return 201.
```

There is deliberately **no cash-in document**. Cash reaches a drawer only by a sale, and a sale already posts it.

---

### `POST /api/store/day/close`

**Auth:** `IsAuthenticated` + `require_section("money", CAP_OPERATE)`.
A day older than `BACK_CLOSE_LIMIT_DAYS` additionally requires `money: manage`, checked in the view (`user_can(user, "money", CAP_MANAGE)`), because it is a branch inside one endpoint rather than a second door.

**Body**

| Field | Type | Required | Meaning |
|---|---|---|---|
| `store` | string | optional | Narrows within the active unit. |
| `date` | string `YYYY-MM-DD` | optional | Defaults to today (IST). |
| `counted_paise` | integer | **required** | What is in the drawer. `>= 0`. |
| `reason` | string | conditional | Required, `>= 10` characters, when `abs(variance) >= 50000` **or** the close is a back-close beyond the limit. Max 240. |
| `hold_answers` | array | **required** | `[{"held_uuid": uuid, "action": "keep" \| "expire"}]`. May be empty when nothing is up for review. |
| `idempotency_uuid` | uuid | **required** | Retry key. |

**201 response:** the `close` block from `GET /api/store/day`, plus `"created": true` and `"flag_raised": bool`. Replay returns 200, `created: false`.

**Errors**

| errorCode | HTTP | Trigger |
|---|---|---|
| `SCOPE_DENIED` | 403 | No store resolved. |
| `VALIDATION` | 400 | Bad date, `counted_paise` absent/non-integer/negative, `hold_answers` absent or malformed, missing `idempotency_uuid`. |
| `DAY_IN_FUTURE` | 400 | `date` is after today (IST). |
| `DAY_NOT_OPEN` | 409 | No submitted `DayOpen` for `(store, date)`. A day that never opened has nothing to close. |
| `DAY_ALREADY_CLOSED` | 409 | A submitted `DayClose` exists for `(store, date)`. |
| `HOLDS_UNANSWERED` | 409 | A hold in the review list has no answer in `hold_answers`. The message names how many. |
| `HOLD_KEEP_EXHAUSTED` | 409 | An answer says `keep` for a hold already at `kept_count >= 3`. |
| `REASON_REQUIRED` | 400 | A reason is required (variance at or above threshold, or a back-close beyond the limit) and is absent or shorter than 10 characters. |
| `BACK_CLOSE_DENIED` | 403 | The day is older than 7 days and the caller does not hold `money: manage`. |

**Business logic**

```
1. Replay check on idempotency_uuid -> return the existing close, 200, created=false.
2. Validate counted_paise, hold_answers shape, uuid, date.
   -> any invalid -> VALIDATION
3. Refuse a future day.
   -> date > today (IST) -> DAY_IN_FUTURE
4. Resolve the store.
   -> pick.store is None -> SCOPE_DENIED
5. Age check: (today - date).days > 7 requires money: manage.
   -> older and the caller does not hold it -> BACK_CLOSE_DENIED
6. Load the submitted DayOpen for (store, day).
   -> absent -> DAY_NOT_OPEN
7. Refuse a second close.
   -> a submitted DayClose exists -> DAY_ALREADY_CLOSED
8. Compute cash_in = storefront.day.money_for(store, day).collections["cash"].
9. Compute cash_out = Σ submitted StoreCashOut.amount_paise for (store, day).
10. expected = day_open.counted_paise + cash_in - cash_out; variance = counted_paise - expected.
11. Build the review list (same query as GET step 8). Every uuid in it must appear in hold_answers.
    -> any unanswered -> HOLDS_UNANSWERED
    -> an answer names a uuid not in the list -> ignored, not an error (the till may have resumed it)
12. Reject a keep that would exceed the limit.
    -> an answered "keep" whose hold is already at kept_count >= 3 -> HOLD_KEEP_EXHAUSTED
13. Require a reason when abs(variance) >= 50000 or the close is a back-close beyond the limit.
    -> absent or under 10 characters -> REASON_REQUIRED
14. Open a transaction. get_or_create the VoucherSeries for (fy, store.code, "DCL").
15. Create the DayClose draft, snapshotting opening/cash_in/cash_out/expected/counted/variance
    and back_close, and post() it.
16. Where variance != 0, post the two legs (see Postings) and write the mirroring CashLedgerEntry.
17. Apply the hold answers: "expire" deletes the mirror row, "keep" sets reviewed_on = day and
    increments kept_count.
18. Where abs(variance) >= 50000, raise a ContinuityFlag of kind cash_variance, store-scoped,
    sale=None, details {day, expected_paise, counted_paise, variance_paise, doc_number}.
19. Commit. Return 201.
```

Step 17 changes the server's mirror, and the till reconciles to it on its next hold push, which is the direction the mirror already runs.

---

### `GET /api/store/dashboard` - **changed, not new**

`storefront/dashboard.py` currently returns the literal `{"date": today.isoformat(), "state": "not_built"}` for `manager.day_close`.
That key now reports the real state, and gains two fields:

```jsonc
"day_close": {"date": "2026-08-11", "state": "not_opened" | "open" | "closed",
              "variance_paise": 0, "unclosed_days": 0}
```

`unclosed_days` counts days in the last 30 with bills but no submitted `DayClose`, so the card can say "2 days still to close".
Auth, scope, errors and every other key are unchanged.

### `GET /api/store/cash-summary` - **changed, not new**

Gains one read-only key beside the existing ones, so the Day Summary can say whether the day was agreed without growing a second front door to agreeing it:

```jsonc
"day_close": {"state": "not_opened" | "open" | "closed",
              "counted_paise": 0, "variance_paise": 0, "doc_number": ""}
```

Auth (`money: view`), scope, errors and every other key are unchanged.

## Schema

### New: `storefront_day_open`

Inherits `core.documents.Document` (`doc_number`, `idempotency_uuid`, `docstatus`, `series`, `created_at`, `updated_at`, and the two inherited CHECK constraints).

| Column | Type | Constraints |
|---|---|---|
| `store_id` | bigint | **NOT NULL**, FK `masters_store` `ON DELETE PROTECT` |
| `day` | date | **NOT NULL** |
| `expected_paise` | bigint (`MoneyField`) | NOT NULL |
| `counted_paise` | bigint (`MoneyField`) | NOT NULL, `CHECK (counted_paise >= 0)` - a drawer cannot hold minus |
| `variance_paise` | bigint (`MoneyField`) | NOT NULL. Stored, not derived: it is what *posted*, and `expected` moves later when a late bill lands |
| `source` | varchar(8) | NOT NULL, choices `counted` / `auto`, default `counted` |
| `reason` | varchar(240) | NOT NULL, blank default `""` |
| `opened_by_id` | bigint | NULL, FK `accounts_user` `ON DELETE SET NULL` |

Constraints and indexes:

- `UNIQUE (store_id, day)` - one open per store per day (FR5), and the constraint two racing callers actually collide on.
- `INDEX (store_id, day DESC)` named `dayopen_store_day_idx` - every read is "this store's day", and the previous-close lookup at open walks the same order.

### New: `storefront_day_close`

Inherits `Document`.

| Column | Type | Constraints |
|---|---|---|
| `store_id` | bigint | **NOT NULL**, FK `masters_store` PROTECT |
| `day` | date | **NOT NULL** |
| `day_open_id` | bigint | **NOT NULL**, FK `storefront_day_open` PROTECT - the close cannot outlive its open |
| `opening_counted_paise` | bigint | NOT NULL - snapshot, Rule 3 |
| `cash_in_paise` | bigint | NOT NULL - snapshot of the day's cash tenders at close time |
| `cash_out_paise` | bigint | NOT NULL - snapshot |
| `expected_paise` | bigint | NOT NULL |
| `counted_paise` | bigint | NOT NULL, `CHECK (counted_paise >= 0)` |
| `variance_paise` | bigint | NOT NULL |
| `reason` | varchar(240) | NOT NULL, blank default `""` |
| `back_close` | boolean | NOT NULL, default `false` |
| `closed_by_id` | bigint | NULL, FK `accounts_user` SET_NULL |

- `UNIQUE (store_id, day)` - FR14.
- `INDEX (store_id, day DESC)` named `dayclose_store_day_idx`.

### New: `storefront_store_cash_out`

Inherits `Document`.

| Column | Type | Constraints |
|---|---|---|
| `store_id` | bigint | **NOT NULL**, FK `masters_store` PROTECT |
| `day` | date | **NOT NULL** |
| `amount_paise` | bigint | NOT NULL, `CHECK (amount_paise > 0)` |
| `reason_code` | varchar(16) | NOT NULL, choices `bank_deposit` / `other` |
| `note` | varchar(240) | NOT NULL, blank default `""` |
| `made_by_id` | bigint | NULL, FK `accounts_user` SET_NULL |

- `INDEX (store_id, day)` named `cashout_store_day_idx` - summed once per screen load and once per close.
- No unique key: a store may bank twice in a day.

### New: `storefront_day_variance_correction`

Inherits `Document`.

| Column | Type | Constraints |
|---|---|---|
| `day_close_id` | bigint | **NOT NULL**, FK `storefront_day_close` PROTECT |
| `store_id` | bigint | **NOT NULL**, FK `masters_store` PROTECT |
| `day` | date | **NOT NULL** - the day being corrected, not the day the correction was made |
| `amount_paise` | bigint | NOT NULL - signed; the amount `expected` moved by |
| `reason_code` | varchar(32) | NOT NULL, default `late_bill_after_close` |
| `source_doc_number` | varchar(128) | NOT NULL, blank default `""` - the bill that moved it |

- `INDEX (day_close_id)` named `dvc_close_idx`.
- No unique key: a closed day can move more than once.

### Changed: `masters_store`

| Column | Type | Constraints |
|---|---|---|
| `opening_float_paise` | bigint (`MoneyField`) | NOT NULL, default `500000` (₹5,000), `CHECK (opening_float_paise >= 0)` |

Plain `AddField` with a default; every existing row takes ₹5,000. **The stores must confirm the real number** (spec open question 1).

### Changed: `finledger_cash_entry`

| Column | Type | Constraints |
|---|---|---|
| `store_id` | bigint | **NULL**, FK `masters_store` `ON DELETE PROTECT` |

- `INDEX (store_id, created_at DESC)` named `cashentry_store_idx`.

**No backfill, and this is not an oversight.**
The table is append-only in earnest: a `BEFORE UPDATE` trigger plus a `REVOKE`, installed by `core.ledger.append_only_sql`.
A backfill is an UPDATE, which is precisely what the table exists to refuse.
Existing rows keep `NULL` and read as "unattributed (pre-Aug 2026)".
Nothing in this feature depends on the history: the day's cash-in comes from `sell_saletender`, and every row this feature writes sets the column.

### Changed: `sell_held_bill`

| Column | Type | Constraints |
|---|---|---|
| `reviewed_on` | date | NULL - the day the store last answered for this hold |
| `kept_count` | smallint | NOT NULL, default `0`, `CHECK (kept_count >= 0)` |

Both are till-owned and arrive through the existing `PUT /api/sell/held-bills` push, except that step 17 of the close writes them server-side; the till reconciles on its next push.
`till/held.ts::mirrorRow` stops stripping `reviewed_on` and starts sending `kept_count`.
**A new till column is a new Dexie version** (known trap).

### Changed: `sell_continuityflag`

Four new `Kind` choices. A `TextChoices` change generates an `AlterField` migration that touches no data.

| Value | Label |
|---|---|
| `day_opened_without_count` | Day opened by the first bill, drawer never counted |
| `cash_variance` | Drawer did not agree with the books |
| `day_moved_after_close` | A bill changed a day that was already closed |
| `day_not_closed` | A trading day nobody has closed |

`cash_variance`, `day_moved_after_close` and `day_not_closed` are **store-level** flags about no particular bill, so they carry `ContinuityFlag.DAY_KEY` in `details` and must be added to `sell.services.daily_check.STORE_LEVEL_KINDS`.
`day_opened_without_count` hangs off the bill that auto-opened the day, so it does not.

### Changed: `core.gl.GLAccount`

Two new codes. These are code constants, not rows, per the class docstring.

| Code | Meaning | Side |
|---|---|---|
| `CASH_SHORT_OVER` | Drawer difference, at open or close | expense |
| `CASH_IN_TRANSIT` | Cash handed to the bank, credit not yet landed | asset |

**Both must be added to `finledger.health.ACCOUNTS` with those sides.**
`test_books_health_covers_every_gl_account` is exhaustive by design and fails otherwise, and the comment there says why: a missing code does not break the trial balance, it quietly vanishes from the equation of state, which is a wrong number rather than a missing one.

`finledger.posting.CASH_CONTROL_ACCOUNTS` is **not** touched.
`CashLedgerEntry.Account.BANK` still maps to `GLAccount.CASH`; remapping it would break the per-account tie in `finledger.health._cash_reconciliation` against a GL account with no history.
That drift is spec open question 7 and is deliberately left alone here.

### New `VoucherSeries` rows

Doc types `DOP`, `DCL`, `CSO`, `DVC`, per `(fy, store_code)`.
Created lazily with `VoucherSeries.objects.get_or_create(fy=…, store_code=…, doc_type=…)` immediately before `post()`, inside the posting transaction, which is the pattern `vendors/views.py` already uses for `BK`.
No seed migration, so a store added next year needs no release.

## Postings

Every posting below goes through `core.posting.post_entries`, is balanced by construction, and fires on the `draft → submitted` transition of the named document.
`store` is on both legs.
There is **no branching by commercial model** anywhere in this feature: a drawer is a drawer whoever owns the stock, and nothing here touches ownership, valuation or GST.

Let `X = abs(variance_paise)`.

### `DayOpen`, on `draft → submitted`

| Condition | Leg 1 | Leg 2 |
|---|---|---|
| `variance < 0` (drawer short) | `dr(CASH_SHORT_OVER, X, store=store)` | `cr(CASH, X, store=store)` |
| `variance > 0` (drawer over) | `dr(CASH, X, store=store)` | `cr(CASH_SHORT_OVER, X, store=store)` |
| `variance == 0` | **nothing posts** | - |

The zero case posts nothing at all rather than a pair of zero legs: `post_entries` refuses fewer than two legs and a zero-value posting says nothing.
The document is still created, numbered and submitted, because "we counted and it agreed" is a fact worth having.

Subledger mirror, written directly (not through `post_cash_movement`, which would book its own voucher against `SUSPENSE` and double the rupees - the same reason `post_sale_collection` gives):

`CashLedgerEntry(account=CASH, store=store, doc_number=<the DOP number>, mode="", description="Opening count", kind=RECEIPT if variance > 0 else PAYMENT, amount=+X or -X)`.

### `StoreCashOut`, on `draft → submitted`

| `reason_code` | Leg 1 | Leg 2 |
|---|---|---|
| `bank_deposit` | `dr(CASH_IN_TRANSIT, amount, store=store)` | `cr(CASH, amount, store=store)` |
| `other` | `dr(SUSPENSE, amount, store=store)` | `cr(CASH, amount, store=store)` |

`SUSPENSE` is where an unclassified cash movement already goes (`post_cash_movement`), and the Expenses slice reclassifies it later.

Subledger mirror: `CashLedgerEntry(account=CASH, store=store, doc_number=<the CSO number>, kind=PAYMENT, amount=-amount, description=<reason label>)`.

### `DayClose`, on `draft → submitted`

Identical legs to `DayOpen`, with `X = abs(variance_paise)` computed from the close's own snapshot.
Subledger mirror as above, described "Day close count".

### `DayVarianceCorrection`, on `draft → submitted`

This is the one that is easy to get backwards, so the arithmetic is spelled out.

`variance = counted - expected`, and `expected = opening + cash_in - cash_out`.
A late bill **raises** `cash_in`, which raises `expected`, which makes the variance **more negative**.

Worked example. Counted ₹10,000, expected ₹12,000, so the close posted a short of ₹2,000: `Dr CASH_SHORT_OVER 2000 / Cr CASH 2000`.
A Tuesday bill of ₹500 cash then syncs on Wednesday.
The customer paid that ₹500 into the drawer on Tuesday, so the ₹10,000 already contained it; the books simply did not know.
Had the bill synced on time, expected would have been ₹12,500 and the store would have been short ₹2,500.
So the close **understated** the short by ₹500.

Let `C` = the amount `expected` moved by (`+` when the day's cash tenders rose, `-` when they fell).

| Condition | Leg 1 | Leg 2 |
|---|---|---|
| `C > 0` (a late bill; the day is more short) | `dr(CASH_SHORT_OVER, C, store=store)` | `cr(CASH, C, store=store)` |
| `C < 0` (a bill cancelled; the day is less short) | `dr(CASH, abs(C), store=store)` | `cr(CASH_SHORT_OVER, abs(C), store=store)` |

The GL check that proves the direction: the late sale's own posting debits `CASH` by ₹500, and this correction credits `CASH` by ₹500, so the net effect on the store's cash balance is nil.
That is right, because the drawer physically holds what the count already said it holds.

The correction is **dated today** and carries `reason_code`, per the correct-by-reversal contract.
`amount_paise` is stored signed so the audit trail says which way it went.

Subledger mirror as above, described "Late change to a closed day".

**One rule fires this, not two.** The trigger is "the day's cash-tender total for a day that already has a submitted `DayClose` no longer equals the `cash_in_paise` that close snapshotted".
`storefront.day.money_for` excludes cancelled sales, so a late bill and a late cancellation both move it, and one comparison covers both.

## Components

### Backend - new

| File | What |
|---|---|
| `storefront/models.py` | `DayOpen`, `DayClose`, `StoreCashOut`, `DayVarianceCorrection`. The app's first models. |
| `storefront/migrations/0001_initial.py` | The four tables. |
| `storefront/services/day_book.py` | `open_day()`, `close_day()`, `record_cash_out()`, `correct_closed_day()`, `expected_for()`, `holds_to_review()`. All the business logic; the views stay thin, as `sell/services/accept.py` is thin-viewed. |
| `storefront/serializers.py` | Request validation for the three POST bodies. |
| `storefront/day_views.py` | `StoreDayView`, `DayOpenView`, `DayCashOutView`, `DayCloseView`. Kept out of `views.py`, which its own docstring calls "the store-facing **read-only** aggregator". |

### Backend - changed

| File | What |
|---|---|
| `core/gl.py` | The two new `GLAccount` codes. |
| `finledger/health.py` | Both codes added to `ACCOUNTS`. |
| `finledger/models.py` | `CashLedgerEntry.store`. |
| `finledger/posting.py` | `post_drawer_variance()` and `post_store_cash_out()`, beside `post_sale_collection`. |
| `masters/models.py` | `Store.opening_float_paise`. |
| `masters/serializers.py` | The float exposed on the store master so Setup → Stores can edit it. |
| `sell/models.py` | Four `ContinuityFlag.Kind` values; `HeldBill.reviewed_on`, `HeldBill.kept_count`. |
| `sell/serializers.py` | The held-bill push accepts the two new columns. |
| `sell/services/accept.py` | Auto-open (FR4) and the closed-day correction (FR17), both after the sale is written and inside its transaction. |
| `sell/services/daily_check.py` | The `day_not_closed` escalation; three kinds added to `STORE_LEVEL_KINDS`. |
| `storefront/dashboard.py` | `day_close` reports the real state. |
| `storefront/cash_summary.py` | The new read-only `day_close` key. |
| `storefront/urls.py` | Four new paths under `day`. |

### Frontend - new

| File | What |
|---|---|
| `pages/StoreDay.tsx` | The screen. Renders, top to bottom: the state banner; the morning card (expected, a counted input, Open); the day's money (cash in, the cash-out list with an Add control, card/UPI/credit-note read-only); the holds-to-review list with keep/expire per row; the evening card (expected, a counted input, the live variance, a reason box that appears at ₹500, Close). Calls `GET /api/store/day` on load and after every write, and the three POSTs. |
| `pages/StoreDay.css` | House style, following `DaySummary.css`. |

### Frontend - changed

| File | What |
|---|---|
| `shell/navConfig.ts` | Money gains `{ label: "Open / Close Day", to: "/money/day", minCapability: "operate" }`. Sell gains `{ label: "Open / Close Day", to: "/money/day", deepLink: true }`, which owns no route and no access rule. |
| `routes.tsx` | `{ id: "store-day", path: "/money/day", element: <StoreDayPage /> }`. |
| `pages/DaySummary.tsx` | Reads the new `day_close` key and shows one read-only line. No confirm button, ever. |
| `pages/Home.tsx` | The dashboard's `day_close` card comes alive. |
| `till/db.ts` | **New Dexie version**: `reviewed_on`, `kept_count` on the held table. |
| `till/held.ts` | `mirrorRow` stops stripping `reviewed_on` and sends `kept_count`; `keepHold` increments the count. |
| `lib/api-schema.ts` | **Regenerated, never hand-edited**, with `npm run api:client`, in the same commit as the serializer/view/URL changes (the API-client drift gate). |

### Request flow, click to posting

**Closing a day.** The store taps Close on `/money/day` → `POST /api/store/day/close` with the counted figure, the hold answers and a fresh `idempotency_uuid` → `DayCloseView` validates and resolves the store → `day_book.close_day()` opens one transaction → `money_for` gives the day's cash, `StoreCashOut` gives the outflow, the difference against the counted figure gives the variance → `VoucherSeries.get_or_create` then `DayClose.post()` mints `26-27/DEO/DCL/12` → `post_entries` writes the two legs → the `CashLedgerEntry` mirror is written → the hold answers are applied → a `ContinuityFlag` is raised where the variance reaches the threshold → commit → 201 → the screen refetches `GET /api/store/day` and paints the closed state.

**A late bill on a closed day.** The till syncs → `accept_sale` writes the bill and posts it as it always has → still inside that transaction, `day_book.correct_closed_day(store, billed_on)` compares the day's cash total against the `cash_in_paise` the `DayClose` snapshotted → where they differ, it mints a `DVC`, posts the correcting legs and raises a `day_moved_after_close` flag → the bill is accepted either way, and a failure to correct must never refuse the bill.

### Error handling

Every endpoint answers `Response(refusal_body(code, message), status=…)`, the D10 convention in `core/refusals.py`: a sentence for the person, a code the caller routes on.
Not DRF's `{"detail": …}`, which `finledger/views.py` still uses and which this feature does not copy.

Concurrency is handled the way `accept_sale` handles it: the unique key is the thing that actually binds, an `IntegrityError` is caught outside the aborted transaction, the row is re-read, and the second caller is told what the first one did rather than shown a clash.

### Three requirements with nowhere else to live

**FR16, never auto-close.** There is no scheduled job, no management command and no cron entry that creates a `DayClose`.
The only writer is `POST /api/store/day/close`, driven by a person.
`sell_daily_check` **reads** unclosed days to raise `day_not_closed` and must never close one; that is the difference between the nightly check reporting a fact and inventing one.

**NFR1, the close screen's budget.** `GET /api/store/day` runs at most **5 queries**: the `DayOpen`, the `DayClose` (with its corrections prefetched), `money_for`'s tender aggregate, the `StoreCashOut` sum-and-list, and the holds-to-review.
`money_for` is three aggregates today, so the endpoint calls only the `collections` half rather than building a whole `DayMoney` - the other tenders come off the same tender aggregate in one pass.
A test asserts the count with `assertNumQueries`, because a budget nothing measures is a comment.

**NFR6, the golden-file suite.** `app/backend/tests/test_store_day_golden.py`, over a fixture of **20 constructed store-days** spanning: agrees exactly; short under the threshold; short at the threshold; short over it; over; no opening count (auto-opened); one cash-out; two cash-outs; a bank deposit and an `other` together; a day with no bills; a late bill after close; a cancelled bill after close; two late bills on one closed day; a back-close inside 7 days; a back-close beyond 7 days; a close with holds to answer; a keep at the limit; a zero-variance close; a day closed then corrected to zero variance; and a store on its first ever day.
Each case asserts the documents minted, both legs of every posting, the subledger mirror, the flags raised, and that the trial balance still sums to nought.

### Assumptions

1. **One drawer per store.** The `(store, day)` unique key is this assumption made structural. Spec open question 2; if a store runs two counters, the key grows a third column and every screen changes.
2. **The float is per store, not per person.** A handover mid-day does not re-count the drawer.
3. **`money_for` is the only reading of a day's cash.** If a second reading ever appears, the close and the Day Summary can disagree, which is the failure the shared module was built to prevent.
4. **`store_person` covers both store seats.** A cashier can close (spec D10); the ratified sheet gives both the same rung, and changing that is an access change, not a code change.
5. **The auto-open uses the expected figure.** It never guesses at a count.
6. **Card and UPI are never counted here.** They settle in the D4 bank edge.

## The completeness gate

Checked before showing this document.

- [x] **Every endpoint has a role scope, an error table, and a numbered step flow.** Four new (`GET /api/store/day`, `POST …/open`, `POST …/cash-out`, `POST …/close`) and two changed in place (`dashboard`, `cash-summary`), whose auth, scope and errors are stated as unchanged.
- [x] **Every `-> errorCode` in a flow has a row in its error table, and the reverse.** Walked in both directions for all four new endpoints.
- [x] **Every new column has a type and its constraints.** Four new tables and four changed ones, with PK/FK/unique/not-null/default/CHECK and a reason on every index.
- [x] **Every screen names what it renders and which endpoint it calls.** `StoreDay.tsx` renders five blocks and calls the four `day` endpoints; the three changed screens name the key they read.
- [x] **Money only: every ledger entry is listed with both legs and the transition that fires it.** Four documents, all on `draft → submitted`, with the zero-variance no-post case stated and the `DVC` direction proved by a worked example and a GL check.
- [x] **No requirement in `spec.md` is unaccounted for.** FR1-FR21 and NFR1-NFR7 all land somewhere above; walking the list found three with nowhere to live (FR16, NFR1, NFR6) and they now have their own section rather than being left to the implementer. Three others landed differently from the spec's suggestion, and each says so and why: the screen's section (FR20), the variance mechanism (FR12), the held-bill mirror (FR13).
- [x] **Nothing here needs a CA ruling that has not been given.** No GST, no valuation, no commercial model. `spec.md` recorded no CA questions for this feature.

Two things this design **carries rather than resolves**, both already spec open questions with named owners, neither blocking implementation: the `BANK` to `CASH` mapping (routed round with `CASH_IN_TRANSIT`), and the absence of a central `audit_log` (actor and reason live on each document row).

---

Phase 2 ends here.
Phase 3 is `to-tickets`, and Anand starts it.
