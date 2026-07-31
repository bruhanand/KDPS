# Feature analysis - store-sidebar-and-bell

Phase 0 artifact (impact analysis).
Written 31 Jul 2026, confirmed by Anand in session.

## Source

- Anand's session brief of 31 Jul 2026, with four screenshots: the current store sidebar, the bell in the top bar, the Sell section's subsections, and the Receive Goods screen with its Branded/Non-branded toggle.
- D10 ground it extends: `docs/features/pos-store-front/feature-analysis.md` ruling 4 ("ten flat sections, no subsections") and ticket #170, which folded Inventory only.
  This feature finishes the fold-out D10 started and adds a notification centre.
- Clarifications confirmed in session:
  - Item 10 of the sidebar list is Reports (the transcript said "Potter").
  - The flat no-subsection sidebar applies to the store persona only (`store_manager`, `store_staff`); every other role keeps its current sidebar.
  - Non-branded receiving stays for warehouse/HO users but disappears at a store.
  - The Home-to-Dashboard and HRMS-to-Attendance renames are a conscious amendment of the D10 "names never change" rule, by Anand.
  - Tabs are horizontal, Inventory-style.
  - The bell notification centre (Approvals + Alerts combined) is for all users.
  - The sidebar gains an icon-only collapse (rail mode), for all users.

## The ask, in one place

**A. Store sidebar: ten flat links, zero subsections** (store persona only):

1. Dashboard (was "Home") - opens the dashboard directly.
2. Sell - one page, horizontal tabs: Billing, Return & Exchange, Customers, Till & Sync.
3. Inventory - already folded (#170), unchanged.
4. Receive Goods - one screen, branded flow only at a store, bill upload part of the GRN flow, no separate Upload Bill entry.
5. Transfer - tabs: Transfer, Stock Request, In-Transit. Distribution stops being its own tab and becomes a rare-case feature of a transfer (send to multiple stores).
6. Booking - as is.
7. Money - tabs: Day Summary, Store Targets, Expenses (higher-rung items keep their per-tab gates as today).
8. Offers & Price - tabs: Price List, Offers, Discounts, EOSS.
9. Reports - tabs (all stubs today).
10. Attendance (the HRMS section, relabelled for the store persona).

**B. Bell notification centre** (all users): the bell opens a panel combining Approvals and Alerts - side by side on desktop, stacked on mobile.
The Approvals and Alerts cards leave the dashboard; the `/approvals` and `/alerts` URLs stay alive.

**C. Non-branded receiving** hidden at a store; unchanged for warehouse/HO.

**D. Icon-rail collapse** (all users): the sidebar collapses to icons only, with a toggle and tooltips; state remembered across sessions.

## Impact table

| Area | What changes | Why |
|---|---|---|
| `accounts` (Django) | Nothing. Section codes, capabilities, the #94 one-gate contract and the #85 sidebar payload are untouched. | Folding is presentation; the server stays the single authority on access. |
| Approvals/alerts APIs (Django) | Nothing. `/approvals/inbox` and `/alerts` already exist. | The bell panel only reads them. |
| `inbound` (Django) | Nothing. Non-branded receiving is already warehouse-only server-side. | Only the tab's visibility changes, client-side. |
| `shell/navConfig.ts` | The core change. Five new folds (Sell, Transfer, Money, Offers & Price, Reports) on the existing `NavFoldDef` mechanism; Receive Goods and Home collapse to single links; the store layout relabels Home to Dashboard and HRMS to Attendance. Store persona only. | The nav manifest is the single source the sidebar, route guards and fold pages all derive from. |
| Fold pages (new) | Sell, Transfer, Money, Offers, Reports pages, each following the `Inventory.tsx` pattern: one URL, horizontal tabs, each tab an existing screen rendered unchanged, each tab gated by the menu entry it draws. | D10 s1: divide inside the page, never the sidebar. |
| `shell/AppShell.tsx` + `AppShell.css` | The bell becomes a notification centre (Approvals + Alerts panel, side by side on desktop, stacked on mobile), for all users. The sidebar gains an icon-rail collapse with a toggle, tooltips, and remembered state, for all users. | Both live in the shell and neither depends on the folds. |
| `Home.tsx` / `StoreDashboard.tsx` | The Approvals and Alerts cards come off the dashboard (pending grill Q3 on whether that is all roles or store only). | They move into the bell. |
| `Inbound.tsx` | The Non-branded tab hides when the active unit is a store (pending grill Q6 on the exact rule); Upload Bill stops being a separate entry. | Only branded goods arrive at a store. |
| Tests | `navConfig.test.ts`, fold-page panel tests (the `Inventory.test.ts` pattern), and the RBAC/nav contract tests. | The #146-class rebase-then-retest rule applies; two green PRs have broken main at these tests before. |

Not impacted: every Django app, every ledger, every posting path, the document FSM, the access matrix, the route-guard mechanism (folds already register with `foldOwning`).

## Money slice

**No.**
No documents, no postings, no ledgers, no GST, no valuation, no FSM - pure navigation and presentation.
The one sensitive edge is RBAC presentation: a fold must never show a tab the sidebar would have hidden.
The existing fold mechanism already enforces this (`foldTabs` reads the output of the access filter), and the contract tests pin it.

## Build order

1. **Shell work: bell notification centre + icon-rail collapse** (all users), plus the dashboard cards coming off. Independent of everything else.
2. **Manifest folds + store layout** - the ten-link sidebar in `navConfig.ts`.
3. **Fold pages** - Sell, Transfer, Money, Offers, Reports. Parallel-friendly once step 2 lands, one page per fold.
4. **Receive Goods** - single screen, store hides non-branded, Upload Bill folded into the receive flow.

## Open questions (input for the phase 1 grill)

1. **Fold URLs.** Inventory got a new URL (`/inventory?tab=`). Sell's screens already own canonical URLs (`/sell`, `/sell/returns`, ...). New `/sell?tab=` style fold page, or draw tabs onto the existing URLs?
2. **Badge count.** Approvals only, or approvals + alerts? A number that includes standing alerts risks reviving the permanent-red-dot problem the current bell was built to kill. Lean: badge counts approvals, panel shows both.
3. **Dashboard cards.** Off the dashboard for all roles, or only store? The bell is universal, so the lean is all roles.
4. **Attendance section.** The HRMS section also holds Member Details (store manager's `manage` rung) and Payroll. Does the store manager's Member Details become a second tab inside "Attendance", or does the link go straight to the attendance screen?
5. **Upload Bill.** It is a planned stub today. Is "upload the bill while making the GRN" already satisfied by the existing receipt flow's file attachment, or is that new work in this slice?
6. **Non-branded visibility rule.** Hide by active unit (store unit means hidden), so a HO/warehouse person switched onto a store unit also does not see it? That is the lean.
7. **Collapse behaviour.** Manual toggle only, or also auto-collapse on narrow screens? (Mobile already uses the hamburger drawer; the lean is the rail stays a desktop thing.) And on the icon rail, do non-store users' multi-item sections open as a flyout on hover/click, or does clicking the icon navigate to the section's first screen?

## Next phase

Phase 1 is a grill (`/grilling` - this is not a money slice, so `/grill-with-docs` is not required).
The seven questions above are its input.
