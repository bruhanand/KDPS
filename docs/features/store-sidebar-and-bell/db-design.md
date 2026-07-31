# DB design - store-sidebar-and-bell

Phase 2 artifact.
One new table, one new serialised field, no changed columns, no backfill.
Nothing here is a ledger, a document, or money - plain state, normal Django migration.

## New: `alerts_seen`

The per-user alert-read stamp behind the bell badge (`grill-decisions.md` s2).

Lives in the **`alerts` app**, not on `accounts.User`: the stamp is alerts semantics, and ADR-0002 keeps a module's data in the module that owns it - `accounts` should not grow a column for every feature that wants a per-user cursor.

| Column | Type | Constraints | Why |
|---|---|---|---|
| `id` | bigint | PK | House standard surrogate key. |
| `user_id` | bigint | FK -> `accounts_user`, **unique**, not null, `on_delete=CASCADE` | One stamp per person; the row dies with the user. |
| `seen_at` | timestamptz | not null | When they last opened the Alerts tab. UTC, as everywhere. |
| `created_at` / `updated_at` | timestamptz | not null | `TimeStampedModel` house base. |

- **Indexes:** the unique constraint on `user_id` is the only lookup path (always fetched by caller) - no further index needed.
- **Backfill:** none. An absent row means "never seen", which the API serialises as `seen_at: null` and the client treats as all-unread - the correct cold-start for existing and new users alike.
- **Table name:** `alerts_seen`, following the app's `alerts_alert` / `alerts_policy` pattern.

Django model sketch (matches the app's existing style):

```python
class AlertSeen(TimeStampedModel):
    """Per-user read cursor for the bell's Alerts tab (store-sidebar-and-bell)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_seen"
    )
    seen_at = models.DateTimeField()

    class Meta:
        db_table = "alerts_seen"
```

## Changed: none

- `alerts_alert` already carries everything history needs (`status`, `resolved_at`, all display snapshots).
  The only change is serialiser-level: `resolved_at` joins `AlertReadSerializer.fields` (nullable; open-feed consumers see one new null field).
- `approvals_approval` already carries `status` and `decided_at`; the two new filters in `GET /api/approvals` are query-level only.
  Existing indexes cover the access paths at alpha scale (both lists are already scoped and unpaginated today); if approvals history ever slows, an index on `(status, decided_at)` is the first move - noted, not built.

## Explicitly untouched

No change to `accounts` tables (roles, sections, capabilities), no change to any ledger or document table, no change to `inbound` tables.
The rest of the feature is frontend presentation with no persistence beyond the existing localStorage conventions (rail collapsed state joins the sidebar's existing `NAV_COLLAPSED_KEY`-style client-side memory - deliberately not server state, per grill s7 "remembered per person" on the device they collapsed it).
