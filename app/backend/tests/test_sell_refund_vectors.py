"""What a piece is worth back, as one file two engines answer to (#184, D2).

The cases are not written here. They live in `sell/vectors/refunds.json`, and the
TypeScript port reads the very same file (`src/till/refund.vectors.test.ts`) -
the "two engines, one set of golden files" shape the offer rulebook and the GSTIN
checker already hold to, and for the same reason.

The reason is the whole of it. A refund is worked out **at the counter**, offline,
on a bill that is about to print; the accept pipeline then works it out again and
refuses the whole bill where the two differ by a single paisa - with the customer
gone and every bill behind it stopped in the queue. Two hand-written suites would
agree until the day somebody "fixed" one of them, and that day would show up as a
store that could not sync.

No database here: this is arithmetic, and the rest of the pipeline is tested in
`test_sell_returns.py` where the database is the point.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sell.services.refunds import refund_share

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "sell" / "vectors" / "refunds.json").read_text()
)


@pytest.mark.parametrize(
    "case", VECTORS["cases"], ids=[case["why"][:60] for case in VECTORS["cases"]]
)
def test_what_a_piece_is_worth_back(case: dict[str, Any]) -> None:
    assert (
        refund_share(
            paid_paise=case["paid"],
            line_qty=case["line_qty"],
            returning=case["returning"],
            returned_qty=case["returned_qty"],
            returned_paise=case["returned_paise"],
        )
        == case["refund"]
    )


def test_the_parts_of_a_line_sum_to_what_was_paid() -> None:
    """The property the individual cases are examples of.

    Give a line back one piece at a time, in any size the arithmetic can produce,
    and the refunds have to come to exactly what the customer handed over - never
    a paisa more (money invented) and never a paisa less (money stranded).
    """
    for paid, qty in [(2999, 3), (1005, 2), (149900, 7), (100000, 3), (1, 3)]:
        returned_qty, returned_paise = 0, 0
        for _ in range(qty):
            share = refund_share(
                paid_paise=paid,
                line_qty=qty,
                returning=1,
                returned_qty=returned_qty,
                returned_paise=returned_paise,
            )
            returned_qty += 1
            returned_paise += share
        assert returned_paise == paid, f"{paid} over {qty} came to {returned_paise}"
