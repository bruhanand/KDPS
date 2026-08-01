# Billing screen revamp - Phase 4: tickets

Published 2 Aug 2026, all labelled `ready-for-agent`.
Work the frontier: any ticket whose blockers are done.

| Issue | Title | Blocked by |
|---|---|---|
| #240 | Prefactor - split the Billing page into components | - |
| #241 | UPI stamp end to end (confirmed/manual + day-close split) | - |
| #242 | The customer master is born (model, backfill, upsert) | - |
| #243 | The fixed one-screen frame | #240 |
| #244 | Cart safety - rescan increments, autosave draft, undo | #240 |
| #245 | Customers ride the till dataset | #242 |
| #246 | Payment card - prefill, chips, one balance line | #243 |
| #247 | Polish - GST badge + breakup popover, scan sounds | #243 |
| #248 | UPI charge card on the mock payment adapter | #241, #246 |
| #249 | Customer typeahead at the counter | #243, #245 |

Two tracks meet at #249:

- Frontend chain: #240 → #243 → #246 → #248, with #244 and #247 parallel off their blockers.
- Backend chain: #242 → #245; #241 independent.

Starting frontier: **#240, #241, #242** (no blockers).

At closeout: update `store-front-design.html` §4's region table to the shipped frame (design.md assumption 7).
