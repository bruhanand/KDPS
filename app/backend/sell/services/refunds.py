"""What a sold line is still worth back, and what has already been given back.

One module because there are **two** ways a piece comes back and they share one
ceiling. Inside a bill it is an exchange leg - a `SaleLine` with
`direction=return` pointing at the line it gives back (#178). On its own it is a
plain return - a `ReturnLine` on an `SRT` document (#184, grill Q7). A customer
who exchanges one of a pair and then brings the other back has used both paths
against the same sold line, and each path counting only its own table would
refund that line twice while every individual document stayed perfectly valid.

So the ledger of what has been given back is read from both tables, always, and
under the same lock. The lock is on the *original* line, which is what makes it
work: two returns of the last piece of a line, arriving at once by either route,
serialise behind it rather than both reading "none returned yet" and both paying
out. No constraint downstream would catch that - each refund is individually
correct - so the lock is the whole of the defence.

Cancelled documents are not counted, on either side. The books say that exchange
or that return never happened, and the customer is still holding the piece and
the receipt: counting it would refuse the next legitimate return as
`ALREADY_RETURNED` and under-pay the one after it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import IntegerField, OuterRef, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from core.documents import DocStatus
from sell.models import ReturnLine, SaleLine

#: What `with_returned_qty` annotates. Named here because two readers use it -
#: the bill's read shape, and any screen deciding what is still returnable - and
#: a string spelled twice is a rename waiting to break one of them.
RETURNED_QTY = "returned_qty"


def returned_so_far(original: SaleLine) -> tuple[int, int]:
    """`(quantity, paise)` already given back against one sold line, both ways.

    Locks the original line first - see the module docstring for why that lock is
    the ceiling rather than a nicety.
    """
    SaleLine.objects.select_for_update().filter(pk=original.pk).first()
    legs = (
        SaleLine.objects.filter(original_line=original, direction=SaleLine.Direction.RETURN)
        .exclude(sale__docstatus=DocStatus.CANCELLED)
        .aggregate(qty=Sum("qty"), paise=Sum("net_paise"))
    )
    plain = (
        ReturnLine.objects.filter(original_line=original)
        .exclude(return_doc__docstatus=DocStatus.CANCELLED)
        .aggregate(qty=Sum("qty"), paise=Sum("refund_paise"))
    )
    return (
        int(legs["qty"] or 0) + int(plain["qty"] or 0),
        int(legs["paise"] or 0) + int(plain["paise"] or 0),
    )


def with_returned_qty(lines: QuerySet[SaleLine]) -> QuerySet[SaleLine]:
    """`lines` with each one's already-given-back quantity worked out in SQL.

    The read-only twin of `returned_so_far`, and the only other place the "both
    tables, neither cancelled" rule is spelled. It exists because a *list* of
    lines must not pay two queries a row for a number the screen only needs in
    order to say "1 of 2 still returnable" - and because the fix for that must
    not be a third copy of the rule.

    Deliberately no lock: this is what a person is shown, not what a refund is
    decided against. The decision locks (`returned_so_far`), which is what makes
    the screen's figure advisory and the refusal authoritative.
    """
    legs = (
        SaleLine.objects.filter(original_line=OuterRef("pk"), direction=SaleLine.Direction.RETURN)
        .exclude(sale__docstatus=DocStatus.CANCELLED)
        .values("original_line")
        .annotate(total=Sum("qty"))
        .values("total")
    )
    plain = (
        ReturnLine.objects.filter(original_line=OuterRef("pk"))
        .exclude(return_doc__docstatus=DocStatus.CANCELLED)
        .values("original_line")
        .annotate(total=Sum("qty"))
        .values("total")
    )
    return lines.annotate(
        **{
            RETURNED_QTY: Coalesce(Subquery(legs, output_field=IntegerField()), Value(0))
            + Coalesce(Subquery(plain, output_field=IntegerField()), Value(0))
        }
    )


def entitled_refund(original: SaleLine, qty: int) -> int:
    """What `qty` of a sold line is worth back, in whole paise (D2).

    Two rules, and the second is the one that is easy to miss. A share of a line
    is rounded half-up, never by Python's `round()` - that is banker's rounding
    on a float, so a ₹10.05 pair refunds ₹5.02 instead of ₹5.03 and the till's
    correct figure is refused. And the *last* piece of a line is settled as the
    remainder of what has not been given back yet, so the parts always sum to
    exactly what the customer paid: three pieces at ₹10.00 refund 333 + 333 +
    334, not 333 three times with a paisa left in the books forever.
    """
    returned_qty, returned_paise = returned_so_far(original)
    paid = int(original.net_paise or 0)
    if returned_qty + qty >= original.qty:  # the last of it - settle the remainder
        return paid - returned_paise
    share = Decimal(paid) * qty / original.qty
    return int(share.quantize(Decimal(1), rounding=ROUND_HALF_UP))
