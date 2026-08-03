# pos-store-front - tickets (Phase 4)

> Historical build plan. POS counter redesign issues #272/#273 supersede the counter credit-note and standalone-return slices listed below: the current counter is exchange-only, equal-or-up, with no credit-note issue or redemption.

Published 31 Jul 2026 to GitHub (`bruhanand/KDPS`), all `ready-for-agent` except #190 (`ready-for-human`, hardware).
Work the frontier: any ticket whose blockers are done.

| # | Ticket | Blocked by |
|---|---|---|
| #170 | Store sidebar fold | - |
| #171 | Store-wise monthly targets | - |
| #172 | Approval routes as data | - |
| #173 | Access-matrix editor (RBAC, supervised) | - |
| #174 | Store Dashboard v1 | #170 #171 |
| #175 | Cross-store search + request | #172 |
| #176 | Kernel: till numbers + GL accounts + floor exception (money) | - |
| #177 | Sale document: accept pipeline + stock ledger (money) | #176 |
| #178 | Sale value postings + golden files (money) | #177 |
| #179 | Dataset sync-down | #177 |
| #180 | Till spine: Dexie, queue, numbering, sync (supervised) | #179 |
| #181 | Billing screen: clean cash sale offline (supervised) | #180 |
| #182 | Split tender + credit notes + manager PIN (money) | #181 |
| #183 | Offer engine + auto-apply (money) | #181 |
| #184 | Exchange + plain return + credit-note issue (money) | #178 #182 |
| #185 | Customer search + reprint + Hold Bill | #181 |
| #186 | Sold-before-inward + deferred costing (money) | #178 #181 |
| #187 | B2B GSTIN + IRN queue (money) | #181 |
| #188 | Cash summary + daily check (money) | #178 #183 |
| #189 | PWA hardening + register handover (supervised) | #181 |
| #190 | Printer spike (ready-for-human, hardware) | - |

Starting frontier: #170, #171, #172, #173, #176, and #190 (hardware in hand).
The money spine is the strict chain #176 → #177 → #178 → (#179 → #180 → #181) → the fan-out.
The daily check (#188) is the pilot's go/no-go gate; the pilot does not start without the offer engine (#183).
