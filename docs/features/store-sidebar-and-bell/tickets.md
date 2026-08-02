# Tickets - store-sidebar-and-bell

Phase 4 artifact.
Published to GitHub (`bruhanand/KDPS`) 31 Jul 2026, all labelled `ready-for-agent`.

| Issue | Title | Blocked by |
|---|---|---|
| #226 | Bell: alerts and approvals in one popup, with history | - |
| #227 | Sidebar strips: the tab-row mechanism, proven on Sell | - |
| #228 | Receive: the screen follows the unit | - |
| #229 | Sidebar strips: the ten-link store sidebar | #227 |
| #230 | Sidebar: the icon rail | #227 |

Frontier: #226, #227, #228 can start immediately, each in its own workspace.
#229 and #230 open once #227 merges; they both touch the sidebar renderer, so whichever lands second rebases onto main and re-runs the full suite before pushing (the #146 rule).

Each issue carries its own spec pointers into this folder (`grill-decisions.md`, `api-contract.md`, `db-design.md`, `design.md`).
None is a money slice.
