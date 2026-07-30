"""What one store's Home is made of (D10 §2, ticket #174).

A read-only aggregator: it imports other apps' models, writes nothing, and owns
no table of its own. Living in its own app keeps every one of those cross-app
imports on one side of a seam, so no domain app grows a dependency on another
just to draw a card (ADR-0002) - the same shape `search` already has.

**Every count here is a count of something that exists today.** The nine
`action_queue` keys in `api-contract.md` include three that read `sell_heldbill`,
`sell_deferredcosting` and `sell_continuityflag`, and the `sell` app is not built
until #177-#186. Those three keys are *absent* rather than reported as nought:
a row saying "0 bills on hold" would be a sentence about a store's morning, and
what is actually true is that nothing can be put on hold yet. The ticket's own
words are "counting what already exists". They arrive with the tables they read.

The same honesty runs through the money tiles, which the contract does fix at
zero: `sales_live` says whether a Sale can exist at all, so the screen can label
a zero that means "no bills yet today" differently from one that means "billing
is not live here".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from accounts.permissions import user_can
from accounts.sections import CAP_APPROVE
from alerts.models import Alert, AlertKind, AlertStatus
from approvals.services import inbox_for
from core.documents import DocStatus
from inbound.models import Grn
from masters.models import Store, StoreTarget
from masters.scoping import active_store_ids, scope_by_entitlement
from outbound.models import CountStatus, MarkDamaged, Stocktake, StoreTransfer
from ptmapper.models import PtFile

#: How many in-transit cartons the "live in store" card names before it stops
#: listing and the action-queue row carries the rest. Four fits the card; the
#: count above it is never truncated.
IN_TRANSIT_SHOWN = 4

#: Days on the sparkline, today included.
SPARKLINE_DAYS = 7


@dataclass(frozen=True)
class InTransitTransfer:
    """One carton on the road to this store, and how many pieces are on it."""

    doc_number: str
    pieces: int
    expected: str


def resolve_store(user: Any, requested_code: str) -> Store | None:
    """The one store this dashboard is about, or ``None`` when there isn't one.

    Two ways in, and they gate differently on purpose. A named ``?store=`` is
    checked against **entitlement**, not against the top-bar switcher: asking for
    a store by name is itself the pick, and narrowing an explicit ask by an
    implicit header would answer "you may not" about a store the person holds.
    With no name, the switcher *is* the ask - `active_store_ids` is scope already
    intersected with it - and the answer only exists if it comes to exactly one
    store.

    A network person who has picked no unit therefore gets ``None``, not the
    first of their fifty stores. "The store's Home" is a question about a store;
    with fifty in view there is no honest answer, only an arbitrary one.
    """
    if requested_code:
        return scope_by_entitlement(
            Store.objects.filter(code__iexact=requested_code, is_active=True), user, "id"
        ).first()
    try:
        ids = active_store_ids(user)
    except PermissionDenied:
        # An unknown or out-of-scope `X-KDPS-Unit`. The caller gets this endpoint's
        # own refusal shape rather than DRF's, because the contract says this
        # endpoint answers with `{"error", "code"}` and nothing else.
        return None
    if ids is None or len(ids) != 1:
        return None
    return Store.objects.filter(pk=ids[0], is_active=True).first()


# --- the action queue -----------------------------------------------------


def _approvals_pending(user: Any, store: Store) -> int:
    """Rows in this person's own approvals inbox that belong to this store.

    Deliberately `inbox_for`, not a hand-rolled count of pending approvals: the
    inbox already refuses one's own requests and matches the approver role, and a
    Home card promising "2 waiting for you" that opens onto an empty screen is
    worse than no card. Network-level approvals (no store) are not this store's.
    """
    return int(inbox_for(user).filter(store_id=store.id).count())


def inbound_in_transit(store: Store) -> list[InTransitTransfer]:
    """Cartons dispatched to this store and not yet scanned in, newest first.

    A transfer with a receipt is done; one whose gap has been closed has nothing
    left on the road. Pieces are summed in SQL from the same three columns
    `StoreTransferLine.qty_in_transit` derives from, so the card and the line
    cannot disagree.
    """
    rows = (
        StoreTransfer.objects.filter(
            docstatus=DocStatus.SUBMITTED,
            destination_store_id=store.id,
            receipt__isnull=True,
        )
        .exclude(dispatch_date__isnull=True)
        .annotate(
            pieces=Sum(
                F("lines__qty_dispatched") - F("lines__qty_received") - F("lines__qty_resolved")
            )
        )
        .filter(pieces__gt=0)
        .order_by("-dispatch_date")
    )
    return [
        InTransitTransfer(
            doc_number=transfer.doc_number or "",
            pieces=int(transfer.pieces or 0),
            # There is no expected-arrival *date* on a transfer, only the
            # dispatcher's note ("by Friday", "bus 7pm"). The card shows what the
            # store was actually told rather than inventing a date from it.
            expected=transfer.expected_arrival_note,
        )
        for transfer in rows
    ]


def _grn_pt_pending(store: Store) -> int:
    """Arrivals at this store still owed a PT, plus PTs still being made from
    them - the two halves `/api/inbound/queue` already counts, for one store."""
    awaiting = (
        Grn.objects.filter(
            docstatus=DocStatus.SUBMITTED, kind=Grn.Kind.NON_BRANDED, store_id=store.id
        )
        .exclude(pt_files__docstatus__in=[DocStatus.DRAFT, DocStatus.SUBMITTED])
        .count()
    )
    in_progress = PtFile.objects.filter(
        grn__isnull=False, docstatus=DocStatus.DRAFT, grn__store_id=store.id
    ).count()
    return int(awaiting + in_progress)


def _quarantine_to_confirm(store: Store) -> int:
    """Damage reported at this store and still a draft (#138): the pieces are
    sellable until somebody senior confirms, which is the work this row is for."""
    return int(MarkDamaged.objects.filter(store_id=store.id, docstatus=DocStatus.DRAFT).count())


def _rtb_windows_closing(store: Store) -> int:
    """Open return-window countdowns at this store.

    Read off `alerts_alert` rather than recomputed from the returnable pool: the
    nightly check already walks every brand's holdings and applies the configured
    thresholds, and a dashboard that re-derived it would drift from the Alerts
    screen the row sends you to.
    """
    return int(
        Alert.objects.filter(
            kind=AlertKind.RETURN_WINDOW, status=AlertStatus.OPEN, store_id=store.id
        ).count()
    )


def _open_count_session(store: Store) -> int:
    """Counts open at this store - the exercise, not the counter's pass, because
    that is the row `/stock-count` lists and clicking through must match."""
    return int(Stocktake.objects.filter(store_id=store.id, status=CountStatus.OPEN).count())


def action_queue(user: Any, store: Store, in_transit_count: int) -> list[dict[str, Any]]:
    """The needs-your-action rows, in the contract's order.

    Every row ships with its count even when that count is nought: unlike the
    three `sell` keys, these all read a table that exists, so nought is a fact
    about the store and not about the build. The screen greys a nought row rather
    than hiding it - a queue that changes length as work is cleared is one you
    stop trusting to be the whole list.
    """
    return [
        {"key": "approvals_pending", "count": _approvals_pending(user, store)},
        {"key": "transfers_to_receive", "count": in_transit_count},
        {"key": "grn_pt_pending", "count": _grn_pt_pending(store)},
        {"key": "quarantine_to_confirm", "count": _quarantine_to_confirm(store)},
        {"key": "rtb_windows_closing", "count": _rtb_windows_closing(store)},
        {"key": "open_count_session", "count": _open_count_session(store)},
    ]


# --- the rest of the payload ----------------------------------------------


def today_block() -> dict[str, Any]:
    """The four money tiles. Zeros until the Sale document lands (#177/#178).

    The contract fixes these at zero for a fresh store, and a store with no POS
    yet is the same arithmetic - `sales_live` beside them is what tells the two
    apart, so nobody reads a quiet morning into a screen that cannot count.
    """
    return {
        "net_sales_paise": 0,
        "bills": 0,
        "avg_bill_paise": 0,
        "pieces": 0,
        "collections": {"cash": 0, "card": 0, "upi": 0, "credit_note": 0},
        "vs_yesterday_pct": None,
    }


def last7(today: date) -> list[dict[str, Any]]:
    """Seven dated points, oldest first, so the sparkline has an x-axis before it
    has any y values."""
    return [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "net_sales_paise": 0,
        }
        for offset in range(SPARKLINE_DAYS - 1, -1, -1)
    ]


def manager_block(user: Any, store: Store, today: date) -> dict[str, Any] | None:
    """Month-to-date against the store's target, or ``None`` for a cashier.

    ``None`` means the key is absent from the payload entirely, not present and
    empty: the screen decides whether to draw the row by asking whether the row
    is there, so a cashier's browser is never handed a number it must remember
    not to render. The gate is the stored matrix (`sell >= approve`), never a
    role name - which role holds it is admin-editable data (#173).
    """
    if not user_can(user, "sell", CAP_APPROVE):
        return None
    target = StoreTarget.objects.filter(store_id=store.id, month=today.replace(day=1)).first()
    return {
        # Day close (I3, store open/close) is its own designed flow, sequenced
        # after this one. The key is here with an honest state rather than
        # missing, so the row has its shape from the first day.
        "day_close": {"date": today.isoformat(), "state": "not_built"},
        "mtd_net_paise": 0,
        "target_paise": int(target.target_paise) if target else 0,
    }


def build(user: Any, store: Store) -> dict[str, Any]:
    """One store's whole Home, in the contract's shape."""
    today = timezone.localdate()
    in_transit = inbound_in_transit(store)
    payload: dict[str, Any] = {
        "store": store.code,
        # False until the Sale document and the till land. Not in the contract's
        # sketch, which was written as if `sell` existed; without it the money
        # tiles would read as a real nought.
        "sales_live": False,
        "today": today_block(),
        "action_queue": action_queue(user, store, len(in_transit)),
        "live": {
            # The rulebook is #183. Empty rather than absent: "no offers running"
            # is a card a store reads every morning, and it should not appear the
            # day the table does.
            "offers": [],
            "in_transit": [
                {"doc_number": row.doc_number, "pieces": row.pieces, "expected": row.expected}
                for row in in_transit[:IN_TRANSIT_SHOWN]
            ],
        },
        "last7": last7(today),
    }
    manager = manager_block(user, store, today)
    if manager is not None:
        payload["manager"] = manager
    return payload
