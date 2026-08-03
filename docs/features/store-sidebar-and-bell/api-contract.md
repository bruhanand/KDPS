# API contract - store-sidebar-and-bell

Phase 2 artifact.
Input: `feature-analysis.md` + `grill-decisions.md` (both confirmed 31 Jul 2026).

This feature is presentation-first: the sidebar folds, tab strips, icon rail, Receive unit-switch and popup UI are all client-side and carry no API surface of their own.
The whole backend contract is the bell's data: an alerts "seen" stamp, an alerts history read, and two filters on the existing approvals audit view.
**Postings: none.** No document, no ledger, no docstatus transition is touched anywhere in this feature; nothing here goes near `post_entries` or the posting catalog.

Conventions: all endpoints sit under `/api/`, JWT auth as everywhere else; times are UTC ISO-8601 in responses (IST is display-side); dates in query params are `YYYY-MM-DD` (IST calendar dates, the same convention the rest of the API uses).

---

## 1. `GET /api/alerts` - unchanged

Listed for orientation only: open alerts, scoped to the caller (`scope_by_store_or_brand`), gated `home: view`.
The bell's Alerts tab live list reads this exactly as Home's card does today.
Response shape untouched - existing consumers (`Home.tsx`) keep working.

## 2. `GET /api/alerts/seen` - new

Where the caller's alert-read stamp stands.

- **Auth/scope:** authenticated + `home: view` (the same gate as the alerts feed it interprets).
- **Params:** none.
- **Success `200`:**

```json
{ "seen_at": "2026-07-31T14:05:22Z" }
```

`seen_at` is `null` when the caller has never opened the Alerts tab (every open alert then counts as unread - right for a new user).

### Business logic

```
1. Authenticate; check home: view.
   -> not authenticated -> 401 (framework)
   -> section refused   -> 403 (framework)
2. Look up the caller's AlertSeen row.
3. Return { seen_at } - null when no row exists.
```

### Errors

| errorCode | HTTP | Trigger |
|---|---|---|
| (framework) | 401 | No/invalid token |
| (framework) | 403 | Caller lacks `home: view` |

## 3. `POST /api/alerts/seen` - new

Stamp "the caller has seen the alerts as of now".
The client calls it when the Alerts tab of the bell popup is opened.

- **Auth/scope:** authenticated + `home: view`.
- **Body:** none (the server's clock is the stamp - a client clock is not trusted for this).
- **Success `200`:**

```json
{ "seen_at": "2026-07-31T14:05:22Z" }
```

### Business logic

```
1. Authenticate; check home: view.
   -> not authenticated -> 401 (framework)
   -> section refused   -> 403 (framework)
2. Upsert the caller's AlertSeen row: seen_at = now() (server time).
   Idempotent - a second call a moment later just moves the stamp forward.
3. Return { seen_at } with the new value.
```

### Errors

| errorCode | HTTP | Trigger |
|---|---|---|
| (framework) | 401 | No/invalid token |
| (framework) | 403 | Caller lacks `home: view` |

### The unread rule (client-side, for the record)

Unread alert count = open alerts (from `GET /api/alerts`) whose `created_at` > `seen_at`; all of them when `seen_at` is null.
The bell badge = this count + the approvals-inbox count (`GET /api/approvals/inbox` length, unchanged).
The rule lives in one exported client function so the badge and the tab count cannot drift apart.

## 4. `GET /api/alerts/history` - new

Resolved alerts, for the History section of the bell's Alerts tab (grouped per day by the client) and for any later archive view.

- **Auth/scope:** authenticated + `home: view`; rows scoped by `scope_by_store_or_brand`, exactly like the open feed - history never shows a store you cannot see live.
- **Query params:**

| Param | Type | Required | Meaning |
|---|---|---|---|
| `since` | date `YYYY-MM-DD` | no | Only alerts with `resolved_at` on/after this date. Default: 7 days ago (the popup's default range). |

- **Success `200`:** a list in the existing `AlertReadSerializer` shape (it already carries `status` and every display field), plus `resolved_at`, ordered `-resolved_at`.
  `resolved_at` is added to the serializer's field list; on an open alert it serialises as `null`, so the existing open-feed consumers see one new nullable field and nothing else changes shape.

### Business logic

```
1. Authenticate; check home: view.
   -> not authenticated -> 401 (framework)
   -> section refused   -> 403 (framework)
2. Parse since; default = today (IST) - 7 days.
   -> malformed date -> INVALID_SINCE
3. Query Alert where status = resolved and resolved_at::date >= since,
   scoped by scope_by_store_or_brand, ordered -resolved_at.
4. Serialise with AlertReadSerializer (now including resolved_at) and return.
```

### Errors

| errorCode | HTTP | Trigger |
|---|---|---|
| `INVALID_SINCE` | 400 | `since` is not a valid `YYYY-MM-DD` date |
| (framework) | 401 | No/invalid token |
| (framework) | 403 | Caller lacks `home: view` |

## 5. `GET /api/approvals` - changed in place (two new filters)

The existing audit view (mine + my stores', `scope_by_store_or_brand`) grows two optional query params.
Existing params (`status`, `kind`, `q`) and the response shape are untouched.

- **New query params:**

| Param | Type | Required | Meaning |
|---|---|---|---|
| `decided` | `1` | no | Only rows a person decided: `status in (approved, rejected)`. `not_required` rows (auto-cleared, logged) stay out of the bell history and remain reachable on the full screen via the existing `status` filter. |
| `since` | date `YYYY-MM-DD` | no | Only rows with `decided_at` on/after this date. A row with `decided_at` null (pending) is excluded whenever `since` is present - the param is about decisions. |

The bell's Approvals History section calls `GET /api/approvals?decided=1&since=<range start>`.

### Business logic (the changed steps only)

```
1. (unchanged) Authenticate; scope by store-or-brand.
2. (unchanged) Apply status / kind filters if present.
3. NEW: if decided=1, filter status in (approved, rejected).
4. NEW: if since present, parse it, then filter decided_at::date >= since
   (implicitly dropping decided_at-null rows).
   -> malformed date -> INVALID_SINCE
5. (unchanged) Apply the text search last; serialise and return.
```

### Errors

| errorCode | HTTP | Trigger |
|---|---|---|
| `INVALID_SINCE` | 400 | `since` is not a valid `YYYY-MM-DD` date |
| (framework) | 401 | No/invalid token |

## 6. Range filter mapping (client-side, for the record)

The popup's range filter maps to `since` as: Today = today; 7 days = today - 7; 30 days = today - 30; 1 year = today - 365 - all computed in IST via the existing `tillToday()` convention, never UTC `new Date()` (the till-dates-were-UTC lesson).

---

## What is deliberately *not* in this contract

- **No sidebar/RBAC payload change.** The #85 sections payload, section codes and capabilities are untouched; folds, relabels ("Dashboard", "Attendance", "Receive") and tab strips are client presentation over the same payload.
- **No Receive endpoint change.** The server already accepts non-branded receipts only at a warehouse; the client stops offering what the server would refuse.
- **No count endpoint.** The bell computes its badge from the two lists it already fetches; at alpha scale a dedicated count endpoint is premature.
- **No pagination.** Both history reads follow the app-wide unpaginated-list convention; the range filter is the size guard.
