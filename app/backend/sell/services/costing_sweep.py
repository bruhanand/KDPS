"""Paying off what a bill could not cost on the day (#186, grill Q5).

A piece can leave the shop before the books have ever heard of it. The tag is in
the customer's hand, the money is real, and the paperwork is three days behind -
so the bill is taken, the money side posts, and the *cost* side waits in
`DeferredCosting` rather than being guessed at or written as a nought (Rule 5,
Rule 8). This module is the other half of that bargain: when what was missing
arrives, it posts what was owed.

Three different things can be missing, and they arrive from two different
directions:

* **the price** - released by the PT that prices the cohort. Nothing has moved
  for this line at all: no cost event and no stock leg either, because a piece
  that was never inwarded cannot come off a shelf it was never on. Both post here.
* **the brand's commercial model**, and **the supplier a brand-owned piece is
  settled with** - released by *master data*, not by an inward. The piece was on
  the shelf and did leave it, so its stock leg is already written and only the
  value is missing. Re-posting the movement would take the piece out twice.

Which of the two a row is in is not read off its `reason`, because a reason
moves: a line waiting for its price can be priced by a PT and *still* not be
placeable, at which point it is waiting on the masters instead. What never moves
is the line's own `unit_cost_paise` - accept posted the stock leg for exactly the
lines that had one (`_priced_rows`), and this module writes that column only at
the moment it posts. So "has this piece moved yet" has one answer, on the row
itself, and it is the same answer the day after the bill and the year after it.

Everything posts under the **bill**, not under whatever released it: the cost is
the cost of that sale, and a COGS leg on the PT's voucher would say the arrival
incurred it. What makes the late voucher legible is `against_voucher` - it names
the bill, so a leg dated three days after the document it belongs to can be told
apart from one posted with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from sell.models import ContinuityFlag, DeferredCosting, SaleLine, SellPolicy
from sell.services.movements import post_stock_move
from sell.services.postings import (
    CostedLine,
    CostPlan,
    plan_from_original,
    post_cost_event,
    resolve_cost_plan,
)
from sell.services.resolve import resolve_piece

#: The queue rows a sweep may act on, oldest first.
#:
#: Oldest first is load-bearing rather than tidy. An exchange leg whose own sale
#: line is also waiting reads its cost off that line (`plan_from_original`, Rule
#: 3), so the sale has to be released before the piece coming back against it -
#: and on one bill the sale line is always the earlier row.
_WAITING = DeferredCosting.objects.filter(status=DeferredCosting.Status.WAITING).order_by("id")


@dataclass(frozen=True)
class _Replan:
    """What the books can say about a waiting line *now*."""

    plan: CostPlan
    unit_cost_paise: int
    #: The seven merchandising dims, for a line that had none to snapshot at
    #: billing. Empty when the line already describes itself.
    dims: dict[str, str]
    season: str


def sweep_deferred(barcode: str, season: str = "", *, actor: Any = None) -> int:
    """Release every line waiting on the price of this cohort. Returns how many.

    Called wherever a PT prices a cohort (`sell.signals`), which is once per
    valued row of the file - so it is written to be cheap on the overwhelmingly
    common answer, which is that nothing is waiting for this barcode at all.

    A season is honoured when the caller names one and ignored when it does not:
    the till may have billed the piece with no season on it, and that line is
    waiting for *any* price for this barcode.
    """
    rows = _WAITING.filter(barcode=barcode)
    if season:
        rows = rows.filter(season__in=("", season))
    return _release(rows, actor)


def sweep_brand(brand: str, *, actor: Any = None) -> int:
    """Release the lines waiting on master data about this brand. Returns how many.

    The other door into the queue, and the one no inward will ever open: a line
    whose brand the masters had never heard of, or whose brand-owned stock had no
    supplier of record, is waiting for somebody to type something into `masters`.
    Until that happens it sits in the queue deliberately - a guess about whose
    stock it was is the one outcome worse than a wait.
    """
    if not brand:
        return 0
    return _release(_WAITING.filter(sale_line__brand=brand), actor)


def _release(rows: Any, actor: Any) -> int:
    """Post what can now be posted, and re-label what still cannot.

    One transaction and one lock: the sweep runs from a signal, so two PTs
    posting the same barcode at once is an ordinary Tuesday, and without the lock
    both would read the same `waiting` row and post the cost twice. The trial
    balance would still be nought, which is exactly why the lock is here and not
    left to a later check to notice.
    """
    posted = 0
    with transaction.atomic():
        for row in rows.select_for_update().select_related("sale_line__sale", "store"):
            if _release_one(row, actor):
                posted += 1
    return posted


def _release_one(row: DeferredCosting, actor: Any) -> bool:
    """One waiting line: post it, or record what it is still waiting for."""
    line = row.sale_line
    replanned = _replan(row, line)
    # Written whether or not the line posts. A piece the books have just met for
    # the first time is worth describing even when they still cannot place it -
    # and the masters-side sweep looks the waiting line up *by its brand*, so a
    # line that stayed nameless would be one no brand edit could ever reach.
    _describe_piece(line, replanned)
    if not replanned.plan.postable:
        # Not a failure and not a no-op: a line that was waiting for its price and
        # is now waiting for its brand has learnt something, and the queue should
        # say which of the three waits it is in.
        if row.reason != replanned.plan.deferral:
            row.reason = replanned.plan.deferral
            row.save(update_fields=["reason", "updated_at"])
        return False

    sale = line.sale
    # Whose posting this is. Not the person whose edit released it - they added a
    # brand or sent a PT, and did not sell anything - but the bill's own author,
    # because this is the bill's own cost event arriving late. It has to be a
    # named someone: the posting floor refuses an anonymous payable to a brand
    # outright ("nobody anonymous owes a brand money", `core.posting`), and a
    # signal has no request behind it to borrow one from.
    posted_by = actor or sale.created_by
    # The piece never moved if it was never priced - accept wrote the stock leg
    # for exactly the lines that carried a cost. Read before the write below,
    # because the write is what destroys the evidence.
    moves_stock = int(line.unit_cost_paise or 0) <= 0
    _record_cost(line, replanned)
    if moves_stock:
        post_stock_move(sale, row.store, line, posted_by)
    post_cost_event(
        sale,
        [CostedLine(row=line, plan=replanned.plan)],
        posted_by,
        against_voucher=sale.doc_number or "",
    )
    row.status = DeferredCosting.Status.POSTED
    row.posted_doc_number = sale.doc_number or ""
    row.save(update_fields=["status", "posted_doc_number", "updated_at"])
    _close_aged_flag(sale)
    return True


def _replan(row: DeferredCosting, line: SaleLine) -> _Replan:
    """Ask the books again what this line costs and which book it comes out of.

    A cost already on the line is never re-derived. It was frozen at billing or by
    an earlier pass of this sweep, the stock leg was written against it, and a
    cohort that has since been re-priced by a second PT must not silently restate
    what a posted movement was worth (Rule 3). Only what is genuinely still
    unknown is asked for.
    """
    if line.original_line is not None:
        # A piece coming back unwinds its own sale's posting, so it waits for the
        # same thing that line waits for and posts at that line's frozen cost.
        original = line.original_line
        return _Replan(
            plan=plan_from_original(original),
            unit_cost_paise=int(original.unit_cost_paise or 0),
            dims={},
            season=line.season,
        )
    piece = resolve_piece(row.store, row.barcode, row.season or line.season)
    unit_cost = int(line.unit_cost_paise or 0) or piece.unit_cost_paise
    dims = dict(piece.dims)
    season = dims.pop("season", "") or line.season
    return _Replan(
        plan=resolve_cost_plan(
            brand=line.brand or dims.get("brand", ""),
            barcode=row.barcode,
            season=season,
            unit_cost_paise=unit_cost,
        ),
        unit_cost_paise=unit_cost,
        dims=dims,
        season=season,
    )


def _describe_piece(line: SaleLine, replanned: _Replan) -> None:
    """Write onto the line what the books have just learnt the piece *is*.

    Rule 3 says a document snapshots its masters, and this is not an exception to
    it: a sold-before-inward line had *nothing* to snapshot - no brand, no design,
    no season - and this is the first description that has ever existed. What is
    already on the line is left exactly as it is; only blanks are filled, so a
    later re-price of the cohort can never restate what a bill said it sold.
    """
    fields: list[str] = []
    for field, value in replanned.dims.items():
        if value and not getattr(line, field, ""):
            setattr(line, field, value)
            fields.append(field)
    if not line.season and replanned.season:
        line.season = replanned.season
        fields.append("season")
    if fields:
        line.save(update_fields=[*fields, "updated_at"])


def _record_cost(line: SaleLine, replanned: _Replan) -> None:
    """Freeze what the piece cost and which book it came out of, at the moment the
    cost event posts.

    The cost matters beyond this posting. An exchange against this line reads
    `unit_cost_paise` and `cost_book` back off it to unwind what the sale posted
    (`plan_from_original`), so a line that stayed at nought after its cost was
    known would send the piece back into the queue a second time. It is also the
    record of whether the stock leg has been written - see the module docstring -
    which is why nothing writes it before the posting it describes.
    """
    line.unit_cost_paise = replanned.unit_cost_paise
    line.cost_book = replanned.plan.book
    line.cost_vendor = replanned.plan.vendor
    line.costing_status = SaleLine.CostingStatus.POSTED
    line.save(
        update_fields=[
            "unit_cost_paise",
            "cost_book",
            "cost_vendor",
            "costing_status",
            "updated_at",
        ]
    )


def _close_aged_flag(sale: Any) -> None:
    """A bill whose last waiting line has posted is not waiting on anything.

    Scoped to the bill and to `aged_uncosted` alone: the other five flag kinds are
    about what happened at the counter, and nothing this module does answers any
    of them.
    """
    if DeferredCosting.objects.filter(
        sale_line__sale=sale, status=DeferredCosting.Status.WAITING
    ).exists():
        return
    ContinuityFlag.objects.filter(
        sale=sale,
        kind=ContinuityFlag.Kind.AGED_UNCOSTED,
        status=ContinuityFlag.Status.OPEN,
    ).update(status=ContinuityFlag.Status.RESOLVED, resolved_at=timezone.now())


# --- ageing ----------------------------------------------------------------


def age_deferred(today: date | None = None) -> int:
    """Flag every bill whose waiting lines have waited too long. Returns how many.

    The queue drains itself when the paperwork lands, so a row that is *still*
    there after the dial's number of days is telling you the paperwork is not
    coming - a PT nobody sent, a brand nobody added, a supplier nobody named. That
    is a person's job, and this is what puts it in front of one: the flag lands on
    the store's exception list, where the daily check reads it (#188).

    One flag per bill rather than per line, because "this bill has been waiting
    since Tuesday" is the sentence somebody acts on, and because a re-run must not
    lay a second copy of the same finding on top of the first.
    """
    day = today or timezone.localdate()
    cutoff = day - timedelta(days=SellPolicy.current().uncosted_aging_days)
    raised = 0
    for row in _WAITING.filter(created_at__date__lte=cutoff).select_related(
        "sale_line__sale", "store"
    ):
        sale = row.sale_line.sale
        _, created = ContinuityFlag.objects.get_or_create(
            sale=sale,
            kind=ContinuityFlag.Kind.AGED_UNCOSTED,
            status=ContinuityFlag.Status.OPEN,
            defaults={
                "store": row.store,
                "details": {
                    "barcode": row.barcode,
                    "reason": row.reason,
                    "waiting_since": row.created_at.date().isoformat(),
                },
            },
        )
        raised += int(created)
    return raised
