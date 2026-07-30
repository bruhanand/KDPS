"""Who may work the counter (the `sell` section of the ratified access matrix).

| Role | sell | What it means here |
|---|---|---|
| Store manager / store staff | operate | bills, and reads back what they billed |
| Owner / brand manager / accounts | view | reads bills, never writes one |
| Admin (IT) | manage | everything |
| Warehouse / HO ops / data steward | none | no access at all |

The rungs come from `Role.section_access` — the stored matrix, which an
administrator edits at runtime (#173) — so nothing here names a role. What is
*not* expressible on that ladder stays out of it: the manager's OK on an over-cap
discount is checked person by person inside the accept pipeline, because it asks
"could this named person have been standing at this counter", which is a question
about one human and one store rather than about a rung.
"""

from __future__ import annotations

from accounts.permissions import require_section
from accounts.sections import CAP_OPERATE, CAP_VIEW

#: Reading a bill back is `view`; billing is `operate`. One view carries both
#: because `GET`/`POST` on `/api/sell/sales` are the search and the till.
CanReadOrBill = require_section("sell", CAP_VIEW, write_minimum=CAP_OPERATE)

#: Reading one bill for reprint.
CanReadSales = require_section("sell", CAP_VIEW)
