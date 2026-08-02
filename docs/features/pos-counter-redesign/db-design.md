# POS counter redesign - Phase 2: DB design

Drafted 2 Aug 2026.
One column on one existing table, one data migration, nothing else server-side.
The counter's own storage (Dexie) changes ride the frontend and are listed for completeness.

## `sell_sellpolicy` - existing, one column added

The singleton money-dials row (Rule 12). Existing columns unchanged: `manual_discount_cap_percent NUMERIC(5,2) NOT NULL DEFAULT 0`, `credit_note_validity_days`, `uncosted_aging_days`, `return_window_days`, `return_review_count`, timestamps.

| Column | Type | Constraints | New? |
|---|---|---|---|
| `manual_discount_on_offer_lines` | `boolean` | `NOT NULL DEFAULT false` | **new** |

`false` = an offer-discounted line takes no manual discount on top (grill Q5 rule 3); `true` = the HO allowance is on.
No index - the table is one row, read whole.

**Granularity note, recorded deliberately:** the allowance is one chain-wide dial, matching the ruling's words ("configured from the admin section"). If a *per-offer* allowance is ever wanted, it becomes a flag on the Offer row (D5's combine-flag pattern) and this dial becomes the default - additive later, not built now.

## Data migration

1. Add the column (default `false` - the safe end; no backfill needed).
2. Set `manual_discount_cap_percent = 10.00` **where it is still `0`** - the ruled default (grill Q5: "a maximum discount of 10% as a default"). A row an owner has already moved off zero is respected and untouched. New installs seed at `10.00` (the model default moves from `0` to `10.00`).

## What deliberately does not change

- **`sell_creditnote`** - stays as-is, append-only history. Nothing writes it after this feature; `refunds.returned_so_far` keeps reading `sell_returnline` + return-direction `sell_saleline` rows so the double-refund ceiling holds over any pre-existing rows.
- **`sell_return` / `sell_returnline`** - stay; the endpoint retires, the tables are history (Rule: documents are never deleted).
- **`sell_saletender`** - unchanged; the `credit_note` mode value stays in the DB enum for historical rows, the serializer stops accepting it.
- **`masters_customer`** - unchanged; already built (#242) and riding the dataset (#245).

## Frontend storage (Dexie, informational - detailed in Phase 3)

- New till table for none; the **cached credit-notes table stops being written and its dataset feed disappears** - dropping the table is a new Dexie version (the till convention: a new table or dropped table is always a new version).
- The dataset's `policy` object (already persisted in `meta`) carries the new boolean alongside the cap string.
