# Billing screen revamp - Phase 2: DB design

Two server-side changes (one new table, one changed table) and the till's local schema bump.
Everything else in the feature stores nothing new on the server.

---

## NEW · `masters_customer` (app: `masters`)

The first customer master (grill Q6).
Lives in `masters` because it is master data that will outlive the counter (loyalty, WhatsApp, regulars reporting); `sell` already imports from `masters` (`Gstin`), so the dependency direction is established.

| Column | Type | Constraints | Why |
|---|---|---|---|
| `id` | bigint | PK | House surrogate key |
| `mobile` | varchar(15) | NOT NULL, **UNIQUE** | The natural key; stored as digits only, canonicalised at the accept boundary to the bare 10-digit Indian form (leading `91` on 12 digits / leading `0` on 11 digits stripped, so `+91 98765-43210`, `09876543210` and `9876543210` are one row; other lengths pass through). One row per mobile - a changed number is a new customer row (v1 ruling) |
| `name` | varchar(120) | NOT NULL, default `''` | Latest non-blank name wins (grill Q6) |
| `gstin` | varchar(15) | NOT NULL, default `''` | Filled when a business bill supplies it; normalised uppercase |
| `created_at` | timestamptz | NOT NULL (auto) | `TimeStampedModel` base |
| `updated_at` | timestamptz | NOT NULL (auto) | `TimeStampedModel` base; drives dataset delta sync |

Indexes:

- `UNIQUE (mobile)` - the upsert key and the till's lookup key.
- `INDEX (updated_at)` - the dataset delta query (`updated_at > since`) is the only hot read path on the server.

Notes:

- **No FK from `Sale`.**
  Bills keep snapshotting `customer_name`/`customer_mobile` as text (Rule 3); a later name correction on the master never rewrites a bill, and linkage for analytics is by mobile at query time (`sell_sale.customer_mobile` is already indexed).
- **Provenance** (Rule 10): the row is only ever written by the sale-accept step, so "who touched it" is derivable from the bills carrying that mobile at that time; no actor columns on the row itself in v1.
- **No SCD-2**: no money derives from customer history.
- Rows are never deleted in v1; no soft-delete column until a merge/cleanup flow exists.

### Backfill

One data migration after the table lands: seed from existing bills -

```
one row per distinct non-blank customer_mobile in sell_sale,
name = the customer_name of the newest bill carrying that mobile whose name is
  non-blank (a blank name never overwrites - same "latest non-blank wins" rule
  as the live upsert, so the two paths cannot drift; AC1),
gstin = the buyer_gstin of the newest B2B bill carrying it, else ''
```

Idempotent (keyed on mobile), so re-running is safe.

---

## CHANGED · `sell_sale_tender` (app: `sell`)

Two new columns for the UPI stamp (grill Q5).
Existing columns, constraints, and the `ck_saletender_*` checks are untouched.

| Column | Type | Constraints | Why |
|---|---|---|---|
| `upi_state` | varchar(10) | NOT NULL, default `''` | `''` on non-UPI rows; `confirmed` or `manual` on UPI rows |
| `upi_reference` | varchar(64) | NOT NULL, default `''` | The acquirer's transaction reference; only on confirmed UPI rows |

New check constraints (added **after** the backfill below):

- `ck_saletender_upi_state_values`: `upi_state IN ('', 'confirmed', 'manual')`.
- `ck_saletender_upi_state_iff_upi`: `(mode = 'upi') = (upi_state <> '')` - every UPI tender is stamped, no other tender is.
- `ck_saletender_reference_confirmed_only`: `upi_reference = '' OR upi_state = 'confirmed'` - a reference can only ride a confirmed stamp (the required-when-confirmed half is enforced at the API layer, where the human message lives).

Index: none - the cash-summary split groups a day's tenders, already reached via the sale FK; no new read path warrants one.

### Backfill

`UPDATE sell_sale_tender SET upi_state = 'manual' WHERE mode = 'upi'` - every historic UPI tender was cashier-vouched by definition, which is exactly what `manual` means.
Runs in the same migration, before the check constraints are added.

---

## Till-local schema (Dexie, `src/till/db.ts`) - version 3

Not a server database, but it is a real schema with migrations, so it is designed here rather than improvised.

| Table | Key | Value | Why |
|---|---|---|---|
| `customers` (new) | `mobile` | `{mobile, name, gstin}` | The synced all-KDPS list the typeahead reads; replaced/merged on dataset pull like items and offers |
| `draft` (new) | fixed key `"current"` | the whole in-progress cart: lines, customer fields, exchange legs, started-at | Continuous autosave (grill Q2-Q3); written on every cart action, cleared at Save & Print / New bill / Hold bill (Hold moves it to `held` as today) |

Notes:

- Typeahead search is a prefix scan on `mobile` plus an in-memory filter on `name`; acceptable at current list sizes, revisit only if the list crosses ~10⁵ rows.
- The **undo stack is in-memory only**, deliberately: after a crash the draft restores but undo history does not - undoing across a restart would undo actions the cashier can no longer see the context of.
- `queue`, `held`, `meta` and all existing tables are unchanged; the version-3 migration only adds the two tables.
