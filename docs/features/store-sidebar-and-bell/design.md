# Technical design - store-sidebar-and-bell

Phase 3 artifact.
Input: `grill-decisions.md` + `api-contract.md` + `db-design.md`, all approved 31 Jul 2026.

## Summary

Everything hangs off the navigation manifest, which is already the single source for the sidebar, the route guards, and page captions.
The store persona's layout rows grow a third row shape - the **strip**: a section drawn as one sidebar link whose sub-screens become a horizontal tab row on the screens themselves (tabs are links between the existing canonical URLs, decision 1).
The strip is injected shell-side through the existing `HostedPageContext`, so no screen is edited to receive its tabs - the same trick the Inventory fold already uses.
The bell grows from an approvals link into a two-tab popup (Alerts / Approvals, live list + expandable history) backed by the three small API additions in the contract.
The sidebar gains a desktop icon-rail collapse with a flyout for multi-item sections.
Receive drops its toggle and renders the flow of the active unit.
No access rule, section code, or server payload moves anywhere.

## Component breakdown

### Backend (small, all in existing apps)

| Piece | New/changed | What |
|---|---|---|
| `alerts/models.py` `AlertSeen` | new | One-to-one user -> `seen_at`, per `db-design.md`. |
| `alerts/serializers.py` | changed | `resolved_at` joins `AlertReadSerializer.fields` (nullable). |
| `alerts/views.py` `AlertSeenView` | new | GET/POST `/api/alerts/seen` - read/upsert the stamp; gate `home: view`. |
| `alerts/views.py` `AlertHistoryView` | new | GET `/api/alerts/history?since=` - resolved, scoped `scope_by_store_or_brand`, ordered `-resolved_at`; `INVALID_SINCE` on a bad date. |
| `alerts/urls.py` | changed | Two new paths under `alerts/`. |
| `approvals/views.py` `ApprovalListView` | changed in place | Two optional filters: `decided=1` (status in approved/rejected), `since=` (on `decided_at`, excludes undecided rows); `INVALID_SINCE` on a bad date. |
| Migration | new | `alerts_seen` table only. No backfill. |

Shared date parsing: one tiny helper (in `core` if one does not already exist) parses `since` and raises the 400; both views use it so the two `INVALID_SINCE` behaviours cannot drift.

### Frontend - navigation manifest (`shell/navConfig.ts`)

| Piece | New/changed | What |
|---|---|---|
| `NavStripDef` (new row shape) | new | `{ section: string; label?: string; tabs: string[] }` - a section drawn as one link; `tabs` lists entry paths (`to` values) in display order; `label` is the persona's name for the row (the Dashboard/Attendance renames live here, per-persona, never in `SECTIONS`). |
| `LayoutRow` | changed | `string \| NavFoldDef \| NavStripDef`. A bare string keeps meaning "flat section, expandable" for non-store personas. |
| `STORE_LAYOUT` | changed | The ten rows: `{home, label "Dashboard", tabs ["/"]}`, `{sell, tabs [/sell, /sell/returns, /sell/customers, /sell/till]}`, `INVENTORY_FOLD` (unchanged), `{receive_goods, tabs ["/receive"]}`, `{transfer, tabs [/transfer, /transfer/requests, /transfer/in-transit]}`, `{booking, tabs ["/booking"]}`, `{money, tabs [/money/day-summary, /money/store-targets, /money/expenses]}`, `{offers_price, tabs [/offers/price-list, /offers, /offers/discounts, /offers/eoss]}`, `{reports, tabs [all five]}`, `{hrms, label "Attendance", tabs ["/staff/attendance"]}`. |
| `stripTabsFor(strip, user)` | new | The strip's visible tabs = its `tabs` filtered to entries that survived `visibleSections` - the same only-subtract rule as `foldTabs`. One surviving tab -> the strip draws no tab row (grill: single-tab strips hide). |
| `stripOwning(pathname, roleCode)` | new | The strip whose section owns this URL for this persona - what the shell wrapper and the sidebar highlight both ask. Active tab = the tab whose path is the deepest prefix of the pathname (`/transfer/new` lights the Transfer tab). |
| Row link target | new rule | A strip row links to its first *visible* tab; a row with no visible tab is not drawn (same rule as folds). |
| Manifest edits | changed | "Receive (GRN)" -> "Receive". `Upload Bill` item deleted. `Distribution` item deleted. `LEGACY_PREFIXES` += `/receive/upload-bill -> /receive`, `/transfer/distribution -> /transfer`. |
| `plannedPages.ts` | changed | The two deleted stubs' promises removed. |

`SECTIONS` itself keeps every label and item otherwise unchanged - other personas' sidebars stay byte-identical.

### Frontend - shell (`shell/AppShell.tsx` + CSS)

| Piece | New/changed | What |
|---|---|---|
| `SectionTabsProvider` | new | Shell-level wrapper around `children`. If the signed-in persona has a strip owning the current URL (and >1 visible tab), it provides `HostedPageContext` `{crumb: strip label, title: active entry's label, tabs: <the strip row>}` - `PageHeader` then draws the tab row under the title exactly as it does for Inventory panels. **No screen edits.** The Inventory page's own inner provider wins by React context nesting, so the fold keeps working untouched. |
| Tab row markup | new | Same `page-tabs`/`page-tab` classes the Inventory fold uses - one look everywhere. Tabs are `<Link>`s to canonical URLs; active = `stripOwning`'s answer; `data-testid="section-tab-<path tail>"`. |
| Sidebar strip rows | changed | `renderStrip` draws a one-line row (like `renderFold`): label = strip label ?? section label, `to` = first visible tab, active = any owning item in the section. Test id `nav-strip-<section>`. |
| `NotificationBell` | new (replaces `ApprovalsBell`) | Popup anchored to the bell. Two tabs: Alerts (unread badge) then Approvals (undecided badge); bell badge = sum. Live lists reuse the row shapes of the existing Alerts/Approvals screens in compact form; each row links into the full screen (popup closes). Below each list a History button expands in place: lazy-fetches `/api/alerts/history` / `/api/approvals?decided=1&since=`, range filter Today/7d/30d/1y (default 7d) computed via `tillToday()`. Opening the Alerts tab fires `POST /api/alerts/seen` and zeroes the unread count locally. Listens to `APPROVALS_CHANGED` + refetches per navigation, as today. Outside-click and Esc close it. Mobile: same component, full-width sheet under the topbar via CSS only. |
| `unreadAlerts(alerts, seenAt)` | new | The one exported client rule (contract s3): badge and tab count both call it. |
| Icon rail | new | `railCollapsed` state in `Sidebar`, persisted under a new localStorage key. Toggle button at the sidebar foot (chevron, `data-testid="sidebar-rail-toggle"`). Rail mode: fixed ~64px width, brand mark only; each row draws its icon with `title` tooltip; the drag-resizer hides. Single-link rows (store persona rows, folds, one-item sections) navigate on click. Multi-item sections: click opens a flyout popover beside the rail listing the section's items (the same `nav-item` links), closed by outside click/Esc/navigation. Mobile drawer ignores rail state entirely (`mobile-open` always renders expanded). |

### Frontend - screens

| Piece | New/changed | What |
|---|---|---|
| `pages/Inbound.tsx` | changed | The Branded/Non-branded toggle keys on the active unit: `activeStore?.store_type === "store"` -> branded flow only, no toggle; warehouse -> two tabs relabelled **Branded** / **Non-branded**; no single active unit (owner on "All units") -> both tabs too (the choice still exists there, and the server enforces the rest). The "New receipt" flow is untouched - the bill upload already lives inside it. |
| `pages/sell/*`, transfer/money/offers/reports screens | unchanged | The strip arrives via context; zero edits. That is the point of the design. |
| `routes.tsx` | changed | Routes for the two deleted planned pages go; everything else stays (tabs are ordinary navigation). |

### Tests

- `navConfig.test.ts`: strip rows subtract-only (a tab never shows what the sidebar hid); single-tab strips hide the tab row; row links to first visible tab; renames are persona-scoped (other personas still read "Home"/"HRMS"/section labels unchanged); legacy redirects for the two deleted stubs; store layout is exactly the ten rows in order.
- Shell tests: bell badge = unread + undecided; opening Alerts stamps seen; history fetch is lazy; rail state persists; flyout only for multi-item sections.
- `pageVocabulary.test.ts` keeps passing (captions still derive from the manifest).
- Backend: `AlertSeen` upsert idempotency; history scoping (a store user never sees another store's resolved alerts); `INVALID_SINCE` on both endpoints; `decided=1` excludes `not_required` and pending; RBAC/nav contract tests re-run after rebase (the #146 rule).

## Request flow (the two main ones)

**Store cashier clicks "Sell", then the Customers tab.**
1. Sidebar row "Sell" (a strip row) links to `/sell` - Billing renders, untouched.
2. `SectionTabsProvider` sees the store persona's sell strip owns `/sell`, provides `HostedPageContext` with the four-tab row (each tab pre-filtered by the access rules the sidebar already applied - a `view`-only user has no Billing tab to see).
3. `PageHeader` inside Billing draws crumb "Sell", title "Billing", and the tab row.
4. Clicking "Customers" is plain navigation to `/sell/customers`; the route guard consults the same manifest; the strip re-renders with Customers active.

**Anyone clicks the bell.**
1. `NotificationBell` has already fetched `/api/approvals/inbox`, `/api/alerts`, `/api/alerts/seen` (per navigation, as the old bell did) and shows badge = undecided + `unreadAlerts(...)`.
2. Click opens the popup on the Alerts tab; `POST /api/alerts/seen` fires; the unread badge clears (server truth follows on the next fetch).
3. "History" click fetches `/api/alerts/history?since=<today-7d>`; changing the range refetches; rows group client-side per day.
4. The Approvals tab lists the inbox; deciding still happens on the full screen (a row click navigates there); history = `/api/approvals?decided=1&since=...` with the decision record per row.

## Error handling

- Backend: the two new views return the contract's `INVALID_SINCE` (400); everything else is framework 401/403. No new error vocabulary.
- Bell fetch failures degrade exactly as the old bell did: no badge, popup shows a quiet "could not load" line per tab with the full-screen link - never a thrown screen.
- A strip URL the user cannot open is impossible by construction (tabs are filtered by the same access output), so no new guard branches exist to fail.

## Assumptions (veto any)

1. **Owner on "All units" sees both Receive tabs** - only a single store-type unit hides Non-branded.
2. **The rail toggle sits at the sidebar foot**; rail width ~64px; tooltips native (`title`), no tooltip library.
3. **Rail and drag-width are separate memories** - expanding restores your last dragged width.
4. **Popup histories are fetch-on-expand**, not preloaded; range filter refetches rather than client-filtering.
5. **Approvals are decided on the full screen**, not inside the popup - the popup is a reader/launcher (keeps maker-checker on one screen with its step trail).
6. **`/approvals` and `/alerts` stay in the manifest** as items of `home` for non-store personas' sidebars, unchanged.
7. The **`sell` strip's Billing tab** requires `sell: operate` (as its menu entry does); a `view`-only visitor on `/sell/customers` simply sees Customers/Till-less tabs per their rungs.
8. Deleting the Distribution stub removes its `plannedPages` promise; the distribution *capability* returns later as a feature of the transfer flow, as grilled.

## Out of scope (unchanged by this design)

Inventory fold internals, the dashboard and its cards, all posting paths, the access matrix, the server sidebar payload, mobile drawer behaviour.
