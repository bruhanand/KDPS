"""What a bill line does to the shelf, and the one table that says which (#186).

Extracted from the accept pipeline because a second caller arrived. A line sold
before its paperwork moved *nothing* when the bill was taken - the piece was
never inwarded, so there was no shelf to take it off - and the movement posts
later, when the PT prices the cohort and the sweep releases it. Two places
writing stock legs for a bill means the mapping from "what kind of line is this"
to "which bucket, which ledger kind, which sign" has to live in one of them or in
neither, and a duplicated table is exactly the failure the original comment
warned about: two conditions choosing the bucket independently, and a damaged
return going back on the shelf on one path but not the other.

The value side of the same line lives in `sell.services.postings`; this module
never touches money beyond the unit cost it hands the ledger.
"""

from __future__ import annotations

from typing import Any

from sell.models import Sale, SaleLine
from stockledger.models import StockLedgerEntry
from stockledger.projections import post_on_hand_movement, post_quarantine_movement


def movement_of(row: SaleLine) -> str:
    """Which of the three things a bill line does to stock."""
    if row.direction != SaleLine.Direction.RETURN:
        return "sold"
    return "returned_damaged" if row.condition == SaleLine.Condition.DAMAGED else "returned_good"


#: The three movements a bill can make, each as `(writer, ledger kind, sign)`.
#: One table rather than a pair of branches, so the bucket a piece lands in and
#: the kind that names it can never be chosen by two different conditions and
#: disagree - which is the failure that would put a damaged return on the shelf.
MOVEMENTS = {
    "sold": (post_on_hand_movement, StockLedgerEntry.Kind.SALE_OUT, -1),
    "returned_good": (post_on_hand_movement, StockLedgerEntry.Kind.SALE_RETURN_IN, 1),
    "returned_damaged": (post_quarantine_movement, StockLedgerEntry.Kind.QUARANTINE_IN, 1),
}


def post_stock_move(sale: Sale, store: Any, row: SaleLine, actor: Any) -> StockLedgerEntry:
    """Move one bill line's piece, at the cost frozen on the line.

    The row describes itself (Rule 9): the seven merchandising dims are
    snapshotted off it onto the leg, so a ledger read years later does not depend
    on the masters still saying what they said. Nothing here checks the cost -
    the ledger refuses a movement at nought value on its own (`ZeroValueMovement`,
    Rule 5), which is what keeps the "never at zero" law in one place.
    """
    mover, kind, sign = MOVEMENTS[movement_of(row)]
    return mover(
        store=store,
        gstin=store.gstin,
        sku_code=row.barcode,
        source=row,
        qty=sign * row.qty,
        unit_cost_paise=row.unit_cost_paise,
        kind=kind,
        doc_number=sale.doc_number or "",
        line_no=row.line_no,
        posted_by=actor,
    )
