# Grill decisions - store-sidebar-and-bell

Phase 1 artifact.
Grilled and confirmed by Anand, 31 Jul 2026.
Input was the seven open questions in `feature-analysis.md`; two more decisions (the Receive relabel, the warehouse both-flows correction) arose during the grill.

## 1. Tabs are navigation, not new pages

All five new folds (Sell, Transfer, Money, Offers & Price, Reports) are single-section folds whose screens already share a URL prefix.
So: no new URLs and no `?tab=` panel pages.
The horizontal strip is a row of links between the existing canonical routes; the active tab is the active route.
The strip renders only for personas whose sidebar folds that section (a store person sees tabs, an owner with the expanded sidebar sees no redundant copy of their menu).
A strip with a single surviving tab draws no strip at all.
Tab visibility reads the same access-filter output the sidebar reads (`foldTabs`), so a fold can never show a tab the sidebar would have hidden.
Inventory keeps its existing `/inventory?tab=` page unchanged; it merged three sections and its shape stays.

## 2. The bell is a two-tab popup with in-place history

- Bell click opens a popup anchored to the bell. Two tabs: **Alerts** first, **Approvals** second.
- Each tab is badged: alerts = unread count, approvals = undecided count. The bell badge = the two combined.
- The two counts mean different things: approvals clear by deciding (exists today), alerts clear by reading (new).
- "Read" lives server-side: one `alerts_seen_at` timestamp per user; unread = open alerts newer than it; opening the Alerts tab stamps it. Survives logout and follows the person across devices.
- Below each live list sits a **History** button that expands in place: resolved alerts grouped per day; decided approvals with their decision record.
- History carries a range filter: Today, 7 days, 30 days, 1 year. Default 7 days. Fetched on demand so the popup opens fast.
- Server facts this rides on: alerts already have an open/resolved lifecycle (the inbox endpoint filters to open), and `GET /api/approvals` is already the filterable audit view. History is a read of what exists plus a small resolved-alerts query and the `alerts_seen_at` field + stamp endpoint.
- The full `/approvals` and `/alerts` screens stay for deep links and old bookmarks.
- The popup is for **all users**.

## 3. The dashboard cards stay

The Approvals and Alerts cards remain on the dashboard for every role.
The bell is a second path to the same places, not a replacement.
`Home.tsx` / `StoreDashboard.tsx` are untouched by this feature.

## 4. HRMS is deferred; the row is a placeholder

The HRMS module gets its own design discussion later.
For now the store persona's row 10 reads **Attendance** and links to the attendance stub - no tabs, nothing else designed.
Member Details and Payroll are unbuilt stubs, so the store manager loses nothing real today.

## 5. Upload Bill is removed for everyone; the label is "Receive"

The receive flow already takes the bill upload inside "New receipt" (invoice attach + AI line-match onto the booking), so the separate planned "Upload Bill" entry is a redundant promise.
Remove it from the manifest for all roles; `/receive/upload-bill` redirects to `/receive`.
The menu line and page title become plain **"Receive"** (was "Receive (GRN)"); GRN stays in the working vocabulary where it names the document (numbers, table columns).

## 6. Receive follows the unit

- **Store unit:** the branded flow renders directly - no tabs.
- **Warehouse unit:** two tabs, relabelled plain **Branded** / **Non-branded** (the "(at store)" / "(at warehouse)" suffixes go - the unit context already says where you are). A warehouse receives both.
- Visibility keys on the **active unit** (the `X-KDPS-Unit` switcher), not the role - matching what the API will actually accept, with no role list (#94).
- The server already refuses non-branded receipts anywhere but a warehouse; nothing changes server-side.

## 7. Icon rail

- Manual collapse toggle, desktop only; the rail state is remembered per person across sessions.
- Mobile keeps the existing hamburger drawer untouched.
- In the rail, a single-link row navigates on click; a multi-item section (non-store personas) opens a click-flyout with its items next to the rail.
- Tooltips with the row name on hover, either way.
- For **all users**.

## Frame carried from Phase 0 (unchanged)

- Ten flat store links, in order: Dashboard, Sell, Inventory, Receive Goods, Transfer, Booking, Money, Offers & Price, Reports, Attendance.
- The flat sidebar applies to the store persona only (`store_manager`, `store_staff`); every other role keeps its current sidebar.
- Home becomes "Dashboard" and HRMS becomes "Attendance" for the store persona - a conscious amendment of the D10 "names never change" rule, by Anand.
- Store tab sets: Sell = Billing, Return & Exchange, Customers, Till & Sync. Transfer = Transfer, Stock Request, In-Transit (Distribution stops being its own tab and becomes a rare-case feature of a transfer). Money = Day Summary, Store Targets, Expenses. Offers & Price = Price List, Offers, Discounts, EOSS. Reports = the five report screens.
- No section code, capability, or gate moves. Folding stays presentation-only. Not a money slice.

## Scope deltas against `feature-analysis.md`

- Dashboard cards: **kept** (the analysis assumed removal; grill Q3 reversed it).
- Upload Bill: removed for **all** roles, not store-hidden.
- Receive at warehouse: **both** flows as tabs (the analysis assumed non-branded only at warehouse).
- One backend addition after all: `alerts_seen_at` per user + its stamp endpoint + a resolved-alerts history query with a range param. Everything else stays frontend-only.

## Next phase

Contract design is nearly empty for this slice (one field, one stamp endpoint, one history query param) - fold it into a light design note, then `/to-tickets`.

---

## Amendments - 1 August 2026

The feature shipped, Anand used it, and the shell got a second look on the `logo-and-sidebar-revamp-v2` branch.
Seven of the decisions above were changed by ruling on 1 August.
They are recorded here rather than edited into the text above, so the 31 July record of what was decided - and the 1 August record of what replaced it - both survive.

**1. The bell splits into two buttons** (amends decision 2).
One bell carrying one combined count could not say which of its two feeds wanted you, and opening it to read approvals put the alerts list on screen as well.
Alerts and Approvals are now two top-bar buttons, each with its own count, its own popup and its own title row where the tab strip used to be.
Everything else in decision 2 stands: the counts still mean different things, "read" still lives server-side as one `alerts_seen_at` stamp, History still expands in place behind each live list, and the full screens still exist for deep links.
The guarantee that reading approvals never marks alerts read is now structural rather than careful - `ApprovalsButton` has no stamping call to make.

**2. Page tabs sit above the title, drawn as buttons** (amends the `SectionTabsProvider` row in `design.md`).
The tabs are where you can go and the title is where you are, so the choice reads before its consequence.
They are free-standing buttons, rust when active, deliberately not the joined navy `.seg` tray a screen uses for its own groupings - the two controls must never read as one.
This moved one line in `PageHeader`, which fixes both call sites at once: the strip and the Inventory fold.

**3. The profile moves to the foot of the sidebar card** (new).
The sidebar owns who you are; the bar owns where you are.
Avatar, name and role sit under the nav - the avatar alone in the rail - and open a panel with the theme switch and Sign out, the same two actions the old top-bar menu offered.

**4. The rail toggle moves to the head of the card** (amends decision 7's "toggle button at the sidebar foot").
The foot is now the profile's, and a control at the foot of a scrolling menu is a control you have to scroll to reach.
Decision 7 otherwise stands unchanged.

**5. The mobile drawer does change after all** (amends decision 7's "mobile keeps the existing hamburger drawer untouched").
The profile lives in the sidebar now, and on a phone the sidebar *is* the drawer - so the drawer gains the profile row and the top bar loses the user menu.
The rail itself is still desktop-only and the drawer still ignores rail state entirely, which is what that decision was actually protecting.

**6. The top bar reads identity, search, what wants you, where you are** (new).
Logo hard left; the search box centred against the window between two equal flexible halves; then Alerts, Approvals and the unit chip in the right corner.
The chip carries the unit's name alone behind a pin - no store code, no state pill, no lock icon.
The code moves into the menu as a hint beside each name, and the state a unit bills under is not the chrome's to say at all: it belongs to the page, where it matters.

**7. `Home.tsx` gets the unit-context line** (amends decision 3's "`Home.tsx` / `StoreDashboard.tsx` are untouched by this feature").
The dashboard names the unit whose numbers are on screen, as code and name - a report heading, not a chip - or "All business units" for the aggregate.
That is one line, and it is the consequence of amendment 6: the state name came off the chrome, so the one screen that was reading the chip's old string had to be told what to say instead.
Decision 3 itself is untouched - the Approvals and Alerts cards stay on the dashboard for every role, and the buttons remain a second path to the same two places.
