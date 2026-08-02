# POS counter redesign - Phase 4: tickets

Published 2 Aug 2026, all labelled `ready-for-agent`.
Work the frontier: any ticket whose blockers are done.

| Issue | Slice | Title | Blocked by |
|---|---|---|---|
| #266 | 1 | The dark room (skin, fonts, chrome dressing) | - |
| #267 | 2 | The bill bar and the bands (header out, F-keys, bill-level Sold by) | #266 |
| #268 | 3 | The scan hero and the line grid | #267 |
| #269 | 4 | The rail (payment tile, customer tile, Save & Print at the foot) | #267 |
| #270 | 5 | Finish overlay + Code 128 bill barcode | #269 |
| #271 | 6 | The discount dials end to end | #268 |
| #272 | 7 | Money only comes in (equal-or-up, credit note retires) | #269 |
| #273 | 8 | Returns fold onto the counter | #267, #270, #272 |
| #274 | 9 | The doc pass | - (region table waits for #273) |

Starting frontier: **#266, #274**. Then #267 → #268 ∥ #269 → #270/#271/#272 → #273 capstone.

Review posture: slices 1-5 are presentation - reviewed for **subtraction** against the Rule 5 checklist in `grill-decisions.md`; slices 6-8 carry the money-slice posture.
