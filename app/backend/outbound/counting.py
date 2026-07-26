"""Blind stock counting — sessions, the merged variance, and its correction (#76).

Four ideas, in the order they happen:

**Blind.** A counter scans; nothing on the screen or in the API says how many
there should be. That is enforced here rather than in the PWA: the book quantity
is not *taken* until the session is submitted, so an open session has no number
to leak however the client is driven.

**Merged.** Several counters run parallel sessions over different parts of a
location. The book is one number per piece, not one per counter, so the variance
is computed over the stocktake — every submitted session pooled — and never per
session.

**Server-side.** The variance (book vs counted, in pieces *and* in value) is
computed here, from the ledger's own on-hand projection and the books' unit cost.
Nothing about the difference is typed or arithmetic'd by a client, which is what
this slice took away from the old "book vs counted" typing screen.

**Never a blind overwrite.** The book is snapshotted at submit. If a piece moves
between the count and the correction — sold, transferred, adjusted by someone
else — the live book no longer matches the snapshot, and that line is held back
until a person says to apply it anyway.

Value is shown to whoever counted, unmasked: they are counting their own
location's stock and can already read the PT that carries the rate, so hiding
the number stops them sizing their own problem and protects nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from approvals.models import CLEARED_STATUSES
from outbound.maker_checker import request_document_approval
from outbound.models import (
    AdjustmentReason,
    CountScope,
    CountSession,
    CountSessionLine,
    CountStatus,
    StockAdjustment,
    StockAdjustmentLine,
    Stocktake,
)
from outbound.posting import (
    OutboundPostingError,
    book_unit_cost,
    post_adjustment,
    resolve_line_identity,
)
from stockledger.models import MERCH_DIM_FIELDS, StockOnHand, merch_dims

if TYPE_CHECKING:
    from accounts.models import User


class CountError(Exception):
    """A counting action the state of the count does not allow."""


class MovedMidCountError(Exception):
    """Stock moved between the count and the correction on at least one line.

    Carries the offending lines so the caller can ask about them by name — the
    whole point is that the person deciding sees *which* piece moved and by how
    much, not a blanket "something changed, try again".
    """

    def __init__(self, lines: list[VarianceLine]) -> None:
        self.lines = lines
        super().__init__(
            f"{len(lines)} line{'' if len(lines) == 1 else 's'} moved since the count was "
            "submitted. Confirm each one before it is applied."
        )


# ---------------------------------------------------------------------------
# Opening and counting
# ---------------------------------------------------------------------------


def open_stocktake(store: Any, *, user: User | None, note: str = "") -> Stocktake:
    """Start a counting exercise at one location."""
    return Stocktake.objects.create(store=store, opened_by=user, note=note)


def open_session(
    stocktake: Stocktake, *, scope: str, scope_value: str = "", user: User | None
) -> CountSession:
    """Add one counter's scoped pass to an open stocktake."""
    if stocktake.status != CountStatus.OPEN:
        raise CountError("This count is closed — open a new one to count again.")
    if scope not in CountScope.values:
        raise CountError(f"Unknown count scope: {scope}")
    if scope != CountScope.STORE and not scope_value:
        raise CountError(f"A {CountScope(scope).label.lower()} count must say which one.")
    return CountSession.objects.create(
        stocktake=stocktake,
        scope=scope,
        scope_value=scope_value if scope != CountScope.STORE else "",
        counted_by=user,
    )


@transaction.atomic
def record_scans(session: CountSession, scans: dict[str, int]) -> list[CountSessionLine]:
    """Add scanned pieces to an open session — additive, so a phone that drops
    its connection mid-aisle resumes rather than restarts.

    Returns the session's lines. They carry no book quantity: this is the blind
    half of the count, and there is nothing here to withhold because nothing has
    been looked up.
    """
    if session.status != CountStatus.OPEN:
        raise CountError("This session has been submitted — its count can no longer change.")
    if not scans:
        raise CountError("No scans to record.")

    store_id = session.stocktake.store_id
    for barcode, qty in scans.items():
        if qty <= 0:
            raise CountError(f"{barcode}: a scanned quantity must be positive.")
        line, created = CountSessionLine.objects.select_for_update().get_or_create(
            session=session, sku_code=barcode, defaults={"counted_qty": 0}
        )
        if created:
            # Dims describe the piece, never its quantity — safe to read while
            # blind, and the counter needs them to see what they just scanned.
            for field_name, value in identity_dims(store_id, barcode).items():
                setattr(line, field_name, value)
        line.counted_qty += qty
        line.save()
    return list(session.lines.all())


def identity_dims(store_id: int, barcode: str) -> dict[str, str]:
    """What the books know this barcode *is* — from the location's stock where it
    holds some, else the SKU master (a surplus the books hold none of still has
    to be describable on the variance report)."""
    from masters.models import Sku

    on_hand = StockOnHand.objects.filter(store_id=store_id, sku_code=barcode).first()
    if on_hand is not None:
        return merch_dims(on_hand)
    sku = Sku.objects.filter(barcode=barcode).first()
    return merch_dims(sku) if sku is not None else dict.fromkeys(MERCH_DIM_FIELDS, "")


def book_quantities(store_id: int, sku_codes: Iterable[str]) -> dict[str, int]:
    """What the books say the location holds of each barcode, right now.

    One place, because two callers ask the same question for opposite reasons —
    the variance report asks in order to spot a piece that moved since the count,
    and an adjustment asks in order to have something to be a difference *from* —
    and they must never get different answers. A barcode the location holds none
    of is simply absent: zero is the caller's own reading of that.
    """
    return {
        row.sku_code: row.net_qty
        for row in StockOnHand.objects.filter(store_id=store_id, sku_code__in=list(sku_codes))
    }


def pieces_in_scope(session: CountSession) -> QuerySet[StockOnHand]:
    """Which pieces this session is entitled to speak about — see ``CountScope``.

    A store or brand session covers everything the books hold in that scope, so
    an unscanned piece is a real shortage. A section session covers only what was
    scanned: the books hold no floor plan, so it cannot honestly claim a piece is
    missing from a shelf the system cannot see.
    """
    held = StockOnHand.objects.filter(store_id=session.stocktake.store_id, net_qty__gt=0)
    if session.scope == CountScope.STORE:
        return held
    if session.scope == CountScope.BRAND:
        return held.filter(brand__iexact=session.scope_value)
    return held.filter(sku_code__in=session.lines.values_list("sku_code", flat=True))


@transaction.atomic
def submit_session(session: CountSession) -> CountSession:
    """Close a session and take its book snapshot — the moment counting stops
    being blind.

    Every piece in scope gets a line, not only the scanned ones: a piece the
    books hold and nobody found is exactly the shortage a count exists to find,
    and it has no scan to hang off.
    """
    if session.status != CountStatus.OPEN:
        raise CountError("This session has already been submitted.")

    scanned = {line.sku_code: line for line in session.lines.all()}
    for on_hand in pieces_in_scope(session):
        line = scanned.get(on_hand.sku_code)
        if line is None:
            line = CountSessionLine(session=session, sku_code=on_hand.sku_code, counted_qty=0)
            for field_name, value in merch_dims(on_hand).items():
                setattr(line, field_name, value)
        line.book_qty = on_hand.net_qty
        line.save()
        scanned.pop(on_hand.sku_code, None)
    # Scanned pieces the location's books hold none of — a surplus. Their book
    # is zero, which is a fact, not a missing snapshot.
    for line in scanned.values():
        line.book_qty = 0
        line.save(update_fields=["book_qty", "updated_at"])

    session.status = CountStatus.SUBMITTED
    session.submitted_at = timezone.now()
    session.save(update_fields=["status", "submitted_at", "updated_at"])
    return session


# ---------------------------------------------------------------------------
# The merged variance report
# ---------------------------------------------------------------------------


@dataclass
class VarianceLine:
    """One piece's answer, merged across every session that counted it."""

    sku_code: str
    dims: dict[str, str] = field(default_factory=dict)
    book_qty: int = 0
    counted_qty: int = 0
    #: The live book now, which is the snapshot unless the piece has since moved.
    live_book_qty: int = 0
    #: The books' cost for one piece. 0 means the books cannot price it — unknown,
    #: never free (#103).
    unit_cost_paise: int = 0

    @property
    def adj_qty(self) -> int:
        return self.counted_qty - self.book_qty

    @property
    def variance_paise(self) -> int:
        return self.adj_qty * self.unit_cost_paise

    @property
    def moved(self) -> bool:
        """Did this piece move between the count and now?"""
        return self.live_book_qty != self.book_qty

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku_code": self.sku_code,
            **self.dims,
            "book_qty": self.book_qty,
            "counted_qty": self.counted_qty,
            "adj_qty": self.adj_qty,
            "live_book_qty": self.live_book_qty,
            "moved": self.moved,
            "unit_cost_paise": self.unit_cost_paise,
            "variance_paise": self.variance_paise,
            "cost_known": self.unit_cost_paise > 0,
        }


def variance_report(stocktake: Stocktake) -> list[VarianceLine]:
    """Book against counted for the whole stocktake, in pieces and in value.

    Counted quantities add up across sessions — two counters covering two
    sections of the same store both contribute. Book quantities do not: the book
    is one number per piece, so the snapshot from the **latest** submitted
    session wins, which is also the one closest to the correction being applied.
    """
    sessions = [s for s in stocktake.sessions.all() if s.status != CountStatus.OPEN]
    sessions.sort(key=lambda s: (s.submitted_at or timezone.now(), s.id))

    merged: dict[str, VarianceLine] = {}
    for session in sessions:
        for line in session.lines.all():
            entry = merged.setdefault(line.sku_code, VarianceLine(sku_code=line.sku_code))
            entry.counted_qty += line.counted_qty
            entry.book_qty = line.book_qty or 0
            entry.dims = {f: getattr(line, f) or "" for f in MERCH_DIM_FIELDS}

    live = book_quantities(stocktake.store_id, merged.keys())
    for entry in merged.values():
        entry.live_book_qty = live.get(entry.sku_code, 0)
        entry.unit_cost_paise = book_unit_cost(
            stocktake.store_id, entry.sku_code, entry.dims.get("season", "")
        )
    return sorted(merged.values(), key=lambda v: v.sku_code)


# ---------------------------------------------------------------------------
# Applying the variance
# ---------------------------------------------------------------------------


@transaction.atomic
def apply_variance(
    stocktake: Stocktake, *, user: User | None, confirm_skus: frozenset[str] = frozenset()
) -> StockAdjustment:
    """Turn the merged variance into the one correction document, and post it if
    the count is allowed to correct itself.

    **Tolerance is the approval policy's, not a second number.** ``ApprovalKind``
    already carries a per-family tolerance the business tunes as data (Rule 12),
    and stock adjustments are the family it was written for — "a small variance
    auto-adjusts and is logged rather than queueing behind a second person". So a
    count within tolerance clears itself through the ordinary maker-checker seam
    (which writes the log entry saying why nobody was asked) and posts here;
    above it, the document waits for a person exactly as a typed adjustment does.
    Recount and banded approval above tolerance are #78.

    **The cost is the books' cost.** Lines are priced through
    ``resolve_line_identity``, the same derive-or-refuse seam every other
    outbound document uses, so a variance can never post at zero value (#103) and
    a caller cannot supply a number of their own.

    A line whose piece moved since the snapshot applies only if named in
    ``confirm_skus``; otherwise the whole call is refused with those lines named.
    A confirmed line still applies its *counted-minus-snapshot* difference — the
    later movement is somebody else's posted document and is already on the
    books, so re-deriving against the live book would book it twice.
    """
    if stocktake.adjustment_id is not None:
        raise CountError("This count's variance has already been applied.")

    sessions = list(stocktake.sessions.all())
    if not any(s.status != CountStatus.OPEN for s in sessions):
        raise CountError("Submit a count session before applying its variance.")
    # Correcting while someone is still counting would book *their* aisle as
    # shrinkage: the report only sees submitted sessions, so an unfinished
    # counter's pieces read as nobody having found them.
    if still_counting := [s for s in sessions if s.status == CountStatus.OPEN]:
        raise CountError(
            f"{len(still_counting)} session{'' if len(still_counting) == 1 else 's'} "
            f"({', '.join(s.scope_label for s in still_counting)}) "
            "have not been submitted. Their stock would be corrected as missing."
        )

    lines = [v for v in variance_report(stocktake) if v.adj_qty != 0]
    if not lines:
        raise CountError("The count agrees with the books — there is nothing to correct.")

    if moved := [v for v in lines if v.moved and v.sku_code not in confirm_skus]:
        raise MovedMidCountError(moved)

    adjustment = StockAdjustment.objects.create(
        store=stocktake.store,
        reason=AdjustmentReason.MISCOUNT,
        notes=f"Auto-adjustment from stock count #{stocktake.pk}.",
        created_by=user,
    )
    for v in lines:
        # Counted dims first, the books' answer over the top — the cost among
        # them, which is why it can never come from the count's own payload.
        identity = {f: v.dims.get(f, "") for f in MERCH_DIM_FIELDS}
        identity.update(resolve_line_identity(stocktake.store_id, v.sku_code, identity["season"]))
        StockAdjustmentLine.objects.create(
            adjustment=adjustment,
            sku_code=v.sku_code,
            book_qty=v.book_qty,
            counted_qty=v.counted_qty,
            adj_qty=v.adj_qty,
            **identity,
        )

    approval = request_document_approval(adjustment, requested_by=user)
    if approval is not None and approval.status in CLEARED_STATUSES:
        post_adjustment(adjustment, user=user)

    stocktake.adjustment = adjustment
    stocktake.status = CountStatus.CLOSED
    stocktake.save(update_fields=["adjustment", "status", "updated_at"])
    adjustment.refresh_from_db()
    return adjustment


__all__ = [
    "CountError",
    "MovedMidCountError",
    "OutboundPostingError",
    "VarianceLine",
    "apply_variance",
    "pieces_in_scope",
    "open_session",
    "open_stocktake",
    "record_scans",
    "submit_session",
    "variance_report",
]
