# pos-store-front - DB design (Phase 2)

> **Superseded in part on 2 Aug 2026.** `docs/features/pos-counter-redesign/db-design.md` wins for counter returns, credit notes, and discount authority. `sell_creditnote`, `sell_return`, `sell_returnline`, the `credit_note` tender enum, and discount-override evidence remain only for append-only historical rows; the counter has no issue/redeem/plain-return path, exchanges are equal-or-up, and the HO-configured manual-discount cap has no till override (Q5/Q5b).

Companion to `api-contract.md`.
Everything is marked **NEW** (table/column that does not exist) or **CHANGED** (existing table extended).
Money is integer paise (`MoneyField`); every ledger-adjacent row carries actor + timestamps per Rule 10.
All new documents subclass the abstract `core.Document` (three keys: `doc_number` unique nullable-until-post, `idempotency_uuid` unique, `docstatus` FSM) and get a `series_lookup()`.

## 1. Kernel extension (CHANGED: `core`)

### `VoucherSeries` - external (till-assigned) numbers

The Sale is the one document whose number is assigned at the till, offline (grill Q1).
New classmethod, no schema change:

- `VoucherSeries.accept_external(*, fy, store_code, doc_type, seq) -> str`
  Accepts a till-assigned sequence exactly once: rejects `seq <= 0`; the `doc_number` unique constraint rejects reuse; `next_seq` advances to `max(next_seq, seq + 1)` under the same `SELECT ... FOR UPDATE` discipline as `allocate()`.
  A `seq` greater than `next_seq` (a hole: earlier bills still unsynced or lost) is accepted and the hole is flagged (see `sell_continuityflag`), never blocked.
  Only `doc_type="SAL"` may use this path; everything else still uses `allocate()`.

Seed: one `VoucherSeries` row per `(fy, store, "SAL")`, plus `("CRN")` and `("SRT")` series (server-allocated, normal path).

### `GLAccount` (CHANGED: new codes)

Existing: INVENTORY, SOR_STOCK, SOR_CONTRA, VENDOR_PAYABLE, GRNI, INPUT_GST, CASH, SUSPENSE.
NEW codes: `SALES_REVENUE`, `OUTPUT_GST`, `COGS`, `CARD_CLEARING`, `UPI_CLEARING`, `CREDIT_NOTE_LIABILITY`, `ROUND_OFF`.

### Posting floor (CHANGED: registered exception, code not schema)

`_refuse_actor_outside_floor` refuses store-scoped actors posting value.
The Sale/Return are store-native money documents whose amounts are machine-computed (scan + dated slab + rulebook + settlement rate), not store discretion.
Register a documented exception: doc_types `SAL`/`SRT` may post with a store-scoped actor, restricted to the account set {CASH, CARD_CLEARING, UPI_CLEARING, CREDIT_NOTE_LIABILITY, SALES_REVENUE, OUTPUT_GST, COGS, INVENTORY, SOR_STOCK, SOR_CONTRA, ROUND_OFF, VENDOR_PAYABLE(party=vendor, SOR/Consignment accrual only)}.
The reason is written next to the registration (same pattern as `REGISTERED_ROLE_LISTS`); the PT/V-flip floor itself is untouched.

## 2. New app: `sell`

### `sell_sale` (NEW, subclasses Document)

| Column | Type / constraint | Notes |
|---|---|---|
| store | FK masters.Store PROTECT, not null | the till's store |
| fy | CharField(8), not null | e.g. `26-27`; part of the till number key |
| till_seq | IntegerField, not null | till-assigned; `doc_number = {fy}/{store}/SAL/{till_seq}` |
| origin | CharField choices `online/offline/paper`, not null | stamped at commit (grill Q2); `paper` = re-entered paper bill |
| billed_at | DateTimeField, not null | till clock at Save & Print |
| customer_name / customer_mobile | CharField(120)/CharField(15), blank | E3; mobile indexed for bill search |
| buyer_gstin | CharField(15), blank | flips bill to B2B (grill Q8) |
| b2b_tax_kind | CharField choices `none/cgst_sgst/igst`, default none | derived from buyer_gstin state vs store state |
| gross_paise / discount_paise / net_paise / gst_paise / round_paise | MoneyField, not null | totals; net = Σ tenders |
| exchange_of | FK self SET_NULL, null | original bill when the bill contains an exchange return leg |
| salesman_default | FK sell.Salesman SET_NULL, null | last-picked default at commit, per D10 |
| created_by | FK accounts.User PROTECT | the till login |

Constraints: `UniqueConstraint(store, fy, till_seq)` `uq_sale_store_fy_seq`; the database still carries historical negative-net/credit-note rows, while the current accept contract hard-refuses a new `net_paise < 0` exchange (`EXCHANGE_SHORT`, counter redesign Q3b).
Indexes: (store, billed_at), customer_mobile, (store, origin).

**Historical amendment, 31 Jul 2026 (#182).** Three columns were added: `override_by` (FK accounts.User SET_NULL, null), `override_kind` (CharField 40, blank), `override_at` (DateTimeField, null) - migration `sell.0005`. Existing rows retain that evidence. Counter redesign Q3b/Q5b later retired the discount and credit-note override kinds; new counter bills use manager evidence only for a late-exchange-window override.

### `sell_saleline` (NEW)

| Column | Type / constraint |
|---|---|
| sale | FK Sale CASCADE, not null |
| line_no | IntegerField; unique(sale, line_no) |
| direction | CharField choices `sale/return`; `return` = the exchange leg |
| barcode / season | CharField(64)/CharField(120); season resolved (oldest live) or as scanned |
| sku snapshot | design/color/size/brand/item/hsn CharFields, blank | snapshot at billing (Rule 3) |
| qty | IntegerField, CHECK `qty > 0` (direction carries sign) |
| mrp_paise / disc_paise / net_paise / gst_rate (Decimal 5,2) / gst_paise | MoneyFields / Decimal, not null | MRP-inclusive back-calculation |
| salesman | FK sell.Salesman PROTECT, not null on direction=sale | per line, locked D10 |
| offer | FK offers.Offer SET_NULL, null | the rule that won |
| offer_evidence | JSONField default dict | `{beat: [...], layer, saved_paise}` (B3, grill Q11) |
| manual_desc | CharField(200), blank | the tagless / sold-before-inward line |
| sold_before_inward | BooleanField default false | grill Q5 |
| costing_status | CharField choices `posted/deferred`, default posted | deferred until GRN/PT prices the cohort |
| return_reason | CharField(40), blank; condition CharField choices `good/damaged`, blank | return legs only |
| override_by | FK accounts.User SET_NULL, null | historical discount/credit-note evidence; current counter uses manager evidence only for a late-exchange-window override (Q5b) |

### `sell_saletender` (NEW)

sale FK CASCADE · mode CharField choices `cash/card/upi/credit_note` · amount_paise MoneyField CHECK `> 0` · credit_note FK sell.CreditNote PROTECT null (required when mode=credit_note).
Constraint: sum-of-tenders == sale.net_paise is enforced in code at accept (not DB).

### `sell_return` (NEW, subclasses Document, doc_type `SRT`)

Plain return without exchange (grill Q7).
store FK · original_sale FK Sale PROTECT · window_override BooleanField default false · override_by FK User null · credit_note FK CreditNote null (set at post) · created_by.
Lines: `sell_returnline` - return FK CASCADE · original_line FK SaleLine PROTECT · qty CHECK `> 0` · reason CharField(40) · condition `good/damaged` · refund_paise MoneyField (what the customer actually paid, computed).

**Amended 31 Jul 2026, after building it (#184).** Five things.

- **The note points at the return, not the return at the note.** `credit_note FK ... (set at post)` would be a column on a *posted* document, and the FSM trigger refuses every change to one - so the link is `CreditNote.source_return`, the mirror of the `source_sale` the negative-net exchange already uses. Same fact, written on the row that is still being created when it becomes true.
- **The line column is `return_doc`, not `return`.** `return` is a Python keyword, so `line.return` is not something any caller could write.
- **A return line carries the same seven merchandising dims a bill line does**, plus `gst_rate`/`gst_paise` and the `unit_cost_paise`/`cost_book`/`cost_vendor` triple. All of them are snapshots off the original line (Rule 3): the ledger legs are filed by brand and season, the reversal gives back the tax the bill charged rather than today's slab, and the cost unwinds out of the book the *sale* posted to even if the brand's terms have changed since.
- **`SellPolicy` gains `return_window_days`** (default 30) - see the api-contract's amendment for why 30 and why it is a dial.
- **`sell_continuityflag.kind` gains `return_late` and `return_uncosted`**, and **`sell_deferredcosting.status` gains `returned`**. The first two are exceptions this document raises; the third is how a sold-before-inward line stops waiting for a cost that will never be owed, because the piece came back before anything priced it.

### `sell_creditnote` (NEW, subclasses Document, doc_type `CRN`)

store FK (issuing store; redemption same-store only in v1, grill Q4) · customer_name/mobile · value_paise · remaining_paise CHECK `0 <= remaining <= value` · status choices `open/spent/expired/cancelled` · expires_on DateField (validity is data; default from policy) · source_return FK sell.Return null · source_sale FK Sale null (negative-net exchange).
`sell_creditnoteredemption` (NEW): credit_note FK PROTECT · sale FK PROTECT · amount_paise CHECK `> 0`; unique(credit_note, sale).

### `sell_salesman` (NEW)

The store's named sellers (not system logins; the per-line popup list).
store FK · code CharField(16) · name CharField(120) · is_active bool · updated_at.
Unique(store, code).
When HRMS lands this becomes the staff master's till view; shaped so it can gain a FK then.

### `sell_heldbill` (NEW, non-financial mirror)

Till-authoritative; server copy exists only so the Dashboard can show holds (grill Q13).
store FK · held_uuid UUID unique · label CharField(120) blank · payload JSONField (the cart) · held_at · expires_policy CharField choices `today/kept`.
Replaced wholesale by each till push; no ledger, no document, no number.

### `sell_registerhandover` (NEW, added 31 Jul 2026 with #189)

The audit row the api-contract's handover step 2 calls for, as its own table rather than an `AccessChange`.
`AccessChange` is a maker-checker *proposal* waiting for a second administrator to apply it; a handover is something that has already happened, and borrowing that row would have put a dead till in an approval queue.

store FK PROTECT · fy CharField(7) · reason CharField(240) · last_accepted_seq Integer · hole_count Integer · actor FK User PROTECT · created_at/updated_at.
Index (store, -created_at).

`last_accepted_seq` and `hole_count` are **stored, not derived**: the whole value of the row is that it says what was true at the moment the machine changed, and by tomorrow neither will be.
The hole *list* is not stored - it is derivable, it can be five thousand long, and what somebody asks of this row a month later is "how bad was it".
Nothing updates or deletes a row here.

### `sell_continuityflag` (NEW, exception rows)

kind choices `number_hole/cn_unverified/return_orig_missing/offer_mismatch/gst_mismatch/gstin_invalid/aged_uncosted/employee_returns` · sale FK null · store FK · details JSONField · status `open/resolved/ignored` · **cleared_note CharField(240) blank** · resolved_by/at.

*`gstin_invalid` added 31 Jul 2026 while building #187* - the B2B ticket asks for the buyer's GSTIN to be validated softly, and none of the original six means that. See the api-contract's step-11 amendment for why it is its own kind rather than another `gst_mismatch`.

*`employee_returns` and `cleared_note` added 31 Jul 2026 with #188* (migration `sell.0011`).
Grill Q7 asks for returns to be counted per employee in the daily check, and none of the seven existing kinds means "one seller took back an unusual number today"; it is deliberately its own because the finding is a pattern *across* bills, so there is no one bill to hang it on and no one bill that answers it.
`cleared_note` is what the person who cleared a flag said about it, and it is a column rather than a key in `details` because `details` is the machine's finding - rewritten on every nightly run - and a person's sentence about it must not be something a later pass can overwrite.

**Which day a flag belongs to** (`ContinuityFlag.DAY_KEY` / `for_day`, #188). Most flags are about a bill, and a bill has the day the counter printed it. The two the nightly check raises are about no bill - a hole is a bill that never arrived, and a return count is about a shop's afternoon - so they carry `day` in their details. The check runs in the small hours of the *next* morning, and `created_at` would file yesterday's finding under today. The hole flag's `day` is the day the gap first survived and never moves afterwards: it is a fact about a shop that goes on being true, not a fact about a day.
This is the sell face of the exception-queue pattern (`TransferReceiptException`/`ReviewItem` precedent); the daily reconciliation and the Dashboard action queue read it.

*`SellPolicy.return_review_count` added 31 Jul 2026 with #188* (same migration): how many pieces one seller may take back in a day before the daily check puts their name on the list. Five is a starting number in exactly the sense `uncosted_aging_days`' three days is - nothing in the corpus fixes one, and it is a dial so head office moves it rather than a store learning to ignore the list (Rule 12).

### `sell_deferredcosting` (NEW)

One row per sold-before-inward line awaiting price: sale_line OneToOne · barcode/season · qty · status `waiting/posted` · posted_doc_number CharField blank.
A hook on PT posting (and cohort creation) sweeps `waiting` rows for matching barcodes and fires posting event B (see contract §Postings).

### `sell_irnqueue` (NEW)

B2B bills awaiting HO's IRN run (grill Q8): sale OneToOne · due_on DateField (billed_at + 30 days) · status `pending/generated/failed` · irn CharField(64) blank · handled_by/at.
Deadline-as-data (Rule 11); surfaces in an HO work queue, not at the store.

## 3. New app: `offers` (the D5 rulebook, till-facing minimum)

### `offers_offer` (NEW)

One open-model rule row = trigger + reward + dials (D5 Q1), Rule 12 throughout.

| Column | Type / constraint |
|---|---|
| name | CharField(160) |
| brand | FK masters.Brand PROTECT, null | null = storewide/KDPS |
| funder | CharField choices `brand/kdps` | margin attribution only, no claim |
| layer | CharField choices `brand/storewide/bank` | grill Q11 three layers |
| trigger_type | CharField choices `none/spend/qty/group` |
| trigger_config | JSONField | slabs, thresholds, group defs |
| reward_type | CharField choices `pct_off/amt_off/item_free/fixed_price/gift` |
| reward_config | JSONField | incl. gift SKU + token price + out-of-stock fallback |
| item_scope | JSONField | store-wide/brand/category/styles/size-colour + season/age + exclusions |
| store_scope | JSONField | all/specific/groups; new store never auto-enrolled (D5 Q4) |
| starts_on | DateField, not null; ends_on DateField null | no end = rolls; dates ride to the till (grill Q3) |
| combinable | BooleanField default false | stacking is opt-in per offer (grill Q11) |
| priority | IntegerField default 100 | residual tie-break, then id |
| is_fallback | BooleanField default false | the named default offer filling gaps (D5 Q5) |
| status | CharField `draft/approved/live/ended` ; approved_by FK User null | authoring sign-off (D5 Q9 gate 1) |
| updated_at | auto_now, indexed | dataset delta |

Index: (layer, starts_on, ends_on), brand.

## 4. `masters` (CHANGED)

- `masters_storetarget` (NEW): store FK · month DateField (first of month) · target_paise · set_by FK User · updated_at. Unique(store, month). Written by the Operations Head (matrix cell), read by the Dashboard.
- `Sku.no_discount` (NEW column): BooleanField default false - the AMM/NOD no-discount flag (B4/D5 Q3).
- `updated_at` (NEW column, auto_now + index) on `Sku`, `Cohort`, `GstSlab` - dataset delta watermark. Backfill: set to migration time.

## 5. `stockledger` (CHANGED)

- `StockLedgerEntry.Kind` gains `sale_out`, `sale_return_in` (enum values + any CHECK/choices migration).
- `StockOnHand` unchanged (keyed store × sku_code); sale decrements through the same projection maintenance as existing kinds; local negative is allowed and reconciled by counts (grill Q5).

## 6. `finledger` (CHANGED)

- `CashLedgerEntry.account` choices gain `CARD` (exists: CASH/BANK/UPI).
- Per-tender receipt rows are written alongside the value-GL clearing legs so the store Cash Summary and the D4 3-way audit read one place.
(The single-entry-caveat status of finledger is unchanged; the Sale's double-entry truth is the value GL.)

## 7. `approvals` (CHANGED) - routes as data

- `approvals_approvalroute` (NEW): kind CharField unique · steps JSONField - ordered `[{order, roles: [...] | roles_from_policy: true, label, later_step_may_short_circuit: bool}]`.
  A step sets **either** its own `roles` **or** `roles_from_policy`, which reads the family's live `ApprovalPolicy` (including its value band) instead - so a route never freezes a second copy of an approver list that Setup can still edit (Rule 12).
- `Approval` (CHANGED): + `route` FK ApprovalRoute **PROTECT** null, + `current_step` IntegerField default 0. Null route = today's single-step behaviour, untouched.
  PROTECT rather than SET_NULL (as built, 30 Jul): nulling a route under a live request would silently turn a two-step approval into a one-step one, and a route a request has walked is part of that request's audit trail.
- `approvals_step_decision` (NEW): approval FK CASCADE · step_order Integer · step_label Char snapshot · decided_by FK User PROTECT · decided_at · short_circuited bool · note. Unique on (approval, step_order).
  Needed because `Approval` carries one `decided_by`, and the kernel's `approval_decision_is_complete` constraint keeps it empty while the request is pending - so the steps cleared along the way have nowhere else to live, and "the Approvals screen shows the step trail" has nothing to read.
- Seed one route for `kind="stock_request"`: step 1 requesting store's manager, step 2 Operations Head (short-circuit allowed = the direct-approve ruling); the conversation with the holding store's manager is step 2's human work, not a system step.
- Consequence in `outbound` (as built): a stock request's approval row moves from the fulfilling store to the **requesting** store, since step 1 is that store's manager and the inbox is store-scoped (ADR-0003).
  What the ask is *worth* is still priced from the fulfilling store's books - `ApprovalKind` gains `pricing_store_field` to keep the two apart.

## 8. `outbound` (CHANGED)

- `StockRequest` + `expected_arrival_at` DateTimeField null (the time quoted to the waiting customer; how it is computed is parked) and + `source` CharField choices `manual/cross_store_search` default manual.

## 9. `accounts` (CHANGED)

- `User.till_pin_hash` CharField(128) blank (NEW) - the manager-override PIN verified at the till while offline; synced down as part of the dataset (hash only, manager-capability users of that store only).
  **Amended 31 Jul 2026 (#182):** the column is written by `PUT /api/auth/me/till-pin` (new, self-service - see the api-contract), and hashed with PBKDF2-SHA256 rather than the project's default bcrypt, because a browser can verify the first offline and cannot verify the second. Who may hold one lives in `accounts/till_pin.py`, shared with the dataset's `managers` section so the two cannot drift.
- Role matrix editing reuses `Role.section_access` + existing `AccessChange` log; no schema change.
- The four floor rules live in code (`FLOORS` constant) - not rows, deliberately (grill Q8: floors are constitution).

## 10. Migrations and seeds

1. New apps `sell`, `offers` (initial migrations).
2. `VoucherSeries` rows for SAL/CRN/SRT per store per FY (seed command extension).
3. GLAccount new codes (data migration).
4. StockLedgerEntry Kind + CashLedgerEntry account choices (migration).
5. `updated_at` columns + backfill on Sku/Cohort/GstSlab.
6. `Sku.no_discount` default false (backfill from AMM/NOD import comes with the offers slice).
7. ApprovalRoute + ApprovalStepDecision tables + stock_request route seed; Approval route/current_step columns (null-safe).
   One backfill after all: pending stock-request approvals are moved onto the requesting store and attached to the route, so in-flight asks do not run under the old single-step rules in the old store's inbox (same treatment as the transfer and return gates got).
8. `sell` KINDS entry + ApprovalPolicy rows (plain return kind) for maker-checker.
9. No destructive change anywhere; nothing existing is renamed.
