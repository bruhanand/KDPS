"""What the counter knows: the till's bootstrap and its delta feed (#179, D10).

The till bills **offline**. Everything it needs to price a scan, name a piece,
tax it, credit a salesman, honour a credit note and let a manager override a
discount has to be sitting on the device before the network goes away - so this
module is the whole of the till's knowledge, and a row missing from it is a
counter that cannot sell a shirt it can see on the shelf.

Three shapes are worth reading before the code.

**The payload has no cost in it, by construction.** H2: a store person may know
the ticket price of everything and the cost of nothing. The hazard is not
carelessness, it is convenience - `StockOnHand` carries `net_value_paise` on the
very row the `stock` section is built from, and `Cohort` carries
`unit_cost_paise` on the row the `items` section is built from. So neither
section is built by serialising a model: both go through `values_list` naming
exactly the columns that may leave, which means a cost cannot ride along by
having been on the object. A test walks the finished payload and fails on any
cost-shaped key or number, and that test is the belt to this braces.

**Big sections are deltaed; small ones are sent whole.** Items and stock are
20,000 rows and get a watermark. The store's own registration, its tax slabs, its
salesmen and its manager PINs are a handful of rows each: a delta over five rows
saves nothing and would need a deletion channel the contract does not give it, so
they are replaced wholesale on every response. `deleted` therefore names exactly
the three sections that can lose a row invisibly - items, offers, credit notes.

**The cursor deliberately laps backwards.** `updated_at` is stamped when a
transaction starts writing, not when it commits, so a cursor set to "now" can
step over a row that was already stamped and had not landed yet - the classic
watermark hole. The till upserts every section by key, so re-sending a row costs
nothing and missing one costs a wrong price at a counter. It is the cheap side of
an unfair trade, so the cursor is held one lap behind the clock.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import ScopeType, User
from accounts.permissions import user_can
from accounts.sections import CAP_APPROVE
from core.documents import DocStatus
from masters.models import Cohort, GstSlab, Sku, Store
from masters.scoping import actionable_store_ids
from sell.models import CreditNote, CreditNoteRedemption, Salesman
from stockledger.models import StockOnHand

#: How far behind the clock the returned cursor sits. See the module docstring:
#: an overlap re-sends a few rows, a gap sells at the wrong price. One minute is
#: comfortably longer than any write transaction in this system.
CURSOR_LAP = timedelta(minutes=1)

#: Scopes whose boundary genuinely *is* a set of stores. A manager PIN hash goes
#: down to a shop-floor device, so "this store's managers" is read as narrowly as
#: it can honestly be read: somebody explicitly assigned to this store. A
#: network-wide or entity-wide administrator whose matrix cell happens to say
#: `sell: manage` is not one of this counter's people, and shipping their hash to
#: fifty tills would be a worse answer than shipping nobody's.
STORE_BOUND_SCOPES = (ScopeType.STORE, ScopeType.STORE_GROUP, ScopeType.REGION)


class TillScopeError(Exception):
    """This login is not a till. Carries the sentence the person should read."""


def resolve_till_store(user: Any) -> Store:
    """The one store this dataset is about, or a refusal.

    Deliberately the caller's *scope* rather than the top-bar switcher. The till
    is a store login by construction (contract, step 3): the payload names one
    GSTIN, one shelf and one set of override PIN hashes, so a person who can see
    two stores has no honest dataset - and letting the switcher pick would hand
    any multi-store login a store's PIN hashes by choosing a unit in a dropdown.
    """
    ids = actionable_store_ids(user)
    if ids is None:
        raise TillScopeError(
            "This login can see every store, so it cannot be a till. A counter "
            "signs in as its own store."
        )
    if len(ids) != 1:
        where = "no store" if not ids else f"{len(ids)} stores"
        raise TillScopeError(
            f"This login is scoped to {where}, and a till is one store. Ask an "
            "administrator for a counter login at this store."
        )
    store = Store.objects.filter(id=ids[0], is_active=True).select_related("gstin").first()
    if store is None:
        raise TillScopeError("This login's store is closed. A closed store has no counter.")
    return store


def build_dataset(store: Store, since_raw: str) -> dict[str, Any]:
    """The till's whole world, or what changed in it since `since_raw`.

    An unreadable `since` is answered with the full snapshot rather than a 400.
    The cursor is opaque and ours; a till holding a damaged one has no way to
    repair it, and a GET it can never escape is worse than a re-send.
    """
    started = timezone.now()
    since = parse_datetime(since_raw.strip()) if since_raw.strip() else None
    if since is not None and timezone.is_naive(since):
        since = timezone.make_aware(since, UTC)
    today = timezone.localdate(started)

    notes_open, notes_closed = _credit_notes(store, since, today)
    return {
        "cursor": _stamp(started - CURSOR_LAP),
        "full": since is None,
        "store": {
            "code": store.code,
            "gstin": store.gstin.gstin,
            "state_code": store.gstin.state_code,
        },
        "items": _items(store, since),
        "stock": _stock(store, since),
        "gst_slabs": _gst_slabs(),
        # The rulebook is #183. Empty rather than absent, and for the same reason
        # the Dashboard's offers card is: "nothing is running" is a fact a till
        # has to be able to read, and a section that appears later is a section
        # every till has to be taught about twice. Each row will carry its own
        # `starts_on`/`ends_on` so the counter starts and stops an offer on its
        # own clock while offline (grill Q3) - the dates ride inside the data.
        "offers": [],
        "credit_notes": notes_open,
        "salesmen": _salesmen(store, since),
        "managers": _managers(store),
        "deleted": {
            "items": _withdrawn_items(store, since),
            "offers": [],
            "credit_notes": notes_closed,
        },
    }


def _stamp(moment: datetime) -> str:
    """A cursor, in the one format this endpoint reads back."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _at_store(store: Store) -> QuerySet[StockOnHand]:
    """The shelf: every barcode this store has ever held, whatever it holds now.

    A row at nought is not a row to drop. The piece can walk back in as an
    exchange, and the till still has to name and price it when it does.
    """
    return StockOnHand.objects.filter(store=store)


def _items(store: Store, since: datetime | None) -> list[dict[str, Any]]:
    """One row per sellable (barcode, season) this store has held.

    A season is a buying cohort, so one barcode bought twice is two rows with two
    prices, and the till resolves the scan to the older one (A2). Inactive SKUs
    are absent: head office withdrawing a piece must mean the counter stops
    offering it, and a delta says so out loud through `deleted.items`.
    """
    rows = Cohort.objects.filter(
        barcode__in=_at_store(store).values("sku_code"), sku__is_active=True
    )
    if since is not None:
        # Three ways an item row can be new *to this till*, and the third is the
        # one a naive delta misses: a cohort bought a season ago at another store,
        # arriving here today, moves no master row at all - only the stock
        # projection. Without it the till would receive a quantity for a barcode
        # it cannot describe or price.
        rows = rows.filter(
            Q(updated_at__gt=since)
            | Q(sku__updated_at__gt=since)
            | Q(barcode__in=_at_store(store).filter(updated_at__gt=since).values("sku_code"))
        )
    # `values_list`, not the model: `Cohort.unit_cost_paise` is the piece's cost
    # (the PT's P RATE) and must never be fetched onto an object this function
    # then serialises. Naming the columns is what makes H2 structural.
    fields = (
        "barcode",
        "season",
        "sku__design",
        "sku__brand",
        "sku__item",
        "sku__size",
        "sku__color",
        "sku__hsn",
        "mrp_paise",
        "sku__mrp_paise",
        "sku__no_discount",
    )
    return [
        {
            "barcode": barcode,
            "season": season,
            "design": design,
            "brand": brand,
            "item": item,
            "size": size,
            "color": color,
            "hsn": hsn,
            # The cohort's ticket price is the one printed on this buying lot's
            # tag; the SKU's is the fallback for a lot that never carried its own.
            "mrp_paise": int(cohort_mrp if cohort_mrp is not None else (sku_mrp or 0)),
            "no_discount": no_discount,
        }
        for (
            barcode,
            season,
            design,
            brand,
            item,
            size,
            color,
            hsn,
            cohort_mrp,
            sku_mrp,
            no_discount,
        ) in rows.order_by("barcode", "season").values_list(*fields)
    ]


def _withdrawn_items(store: Store, since: datetime | None) -> list[str]:
    """Barcodes this till must stop offering, by barcode.

    Only a delta answers anything here: a fresh bootstrap has nothing cached to
    remove, and an inactive piece is simply absent from `items` instead.

    Deactivating a SKU is the only withdrawal that exists. A cohort is a record of
    a purchase and is never unmade, and a stock row falls to nought rather than
    vanishing - so the barcode, not the (barcode, season) pair, is the identity a
    removal travels under, and it takes every season of that piece with it.
    """
    if since is None:
        return []
    return list(
        Sku.objects.filter(
            barcode__in=_at_store(store).values("sku_code"),
            is_active=False,
            updated_at__gt=since,
        )
        .order_by("barcode")
        .values_list("barcode", flat=True)
    )


def _stock(store: Store, since: datetime | None) -> list[dict[str, int | str]]:
    """Quantity per barcode. Quantity, and nothing else (H2).

    `net_value_paise` sits on this very row, which is why the two columns that may
    leave are named rather than a serialiser being pointed at the model.
    """
    rows = _at_store(store)
    if since is not None:
        rows = rows.filter(updated_at__gt=since)
    return [
        {"barcode": sku_code, "qty": net_qty}
        for sku_code, net_qty in rows.order_by("sku_code").values_list("sku_code", "net_qty")
    ]


def _gst_slabs() -> list[dict[str, Any]]:
    """Every dated slab, always whole - the till taxes on its own clock.

    Sent in full even on a delta, and deliberately including slabs whose date has
    not arrived: a rate change announced today and effective in October has to be
    on the device before the counter reaches October offline (Rule 11, dates ride
    inside the data).
    """
    fields = ("hsn_prefix", "threshold_paise", "rate_below", "rate_above", "effective_from")
    return [
        {
            "hsn_prefix": hsn_prefix,
            "threshold_paise": int(threshold_paise),
            "rate_below": _rate(rate_below),
            "rate_above": _rate(rate_above),
            "effective_from": effective_from.isoformat(),
        }
        for hsn_prefix, threshold_paise, rate_below, rate_above, effective_from in (
            GstSlab.objects.order_by("effective_from", "hsn_prefix").values_list(*fields)
        )
    ]


def _rate(rate: Decimal) -> str:
    """A tax rate as the two-decimal string the contract quotes.

    A string rather than a float on purpose: the till back-calculates tax out of
    an MRP-inclusive price, and a rate that arrived as 4.999999999 would put the
    counter and the server a paise apart on every line.
    """
    return f"{Decimal(rate):.2f}"


def _credit_notes(
    store: Store, since: datetime | None, today: date
) -> tuple[list[dict[str, Any]], list[str]]:
    """The notes this store issued, split into "still worth money" and "stop
    honouring this".

    Three things make this the fiddliest section here, and all three are
    consequences of the credit note being a *document*:

      · Its balance is not a column. A submitted document may not be UPDATEd (the
        FSM trigger refuses it), so spending a note appends a redemption row and
        moves nothing on the note itself. The balance is therefore annotated in
        SQL - and the annotation is why the "what changed" filter reaches the
        redemptions through `pk__in` rather than a join, which would quietly
        restrict the `Sum` to the rows that matched the filter.
      · It can expire with nothing written. A note goes dead because a date
        passed, so the delta has to ask which notes crossed their own deadline
        between the cursor and today, or a till that was offline over a weekend
        would go on honouring one.
      · It can only be closed, never removed. So a note leaving the till's cache
        is a `deleted` entry, and the till stops offering it.
    """
    notes = CreditNote.objects.filter(store=store).exclude(docstatus=DocStatus.DRAFT)
    if since is not None:
        redeemed = CreditNoteRedemption.objects.filter(
            credit_note__store=store, created_at__gt=since
        ).values("credit_note_id")
        notes = notes.filter(
            Q(updated_at__gt=since)
            | Q(pk__in=redeemed)
            | Q(expires_on__gte=timezone.localdate(since), expires_on__lt=today)
        )
    annotated = notes.annotate(spent=Coalesce(Sum("redemptions__amount_paise"), Value(0))).order_by(
        "doc_number"
    )

    still_worth_money: list[dict[str, Any]] = []
    closed: list[str] = []
    for note in annotated:
        remaining = int(note.value_paise or 0) - int(note.spent)
        if note.status_at(remaining, today) == CreditNote.Status.OPEN:
            still_worth_money.append(
                {
                    "number": note.doc_number,
                    "remaining_paise": remaining,
                    "expires_on": note.expires_on.isoformat(),
                }
            )
        elif since is not None:
            # Only a delta reports one: a bootstrap has nothing cached to close,
            # and every note it does not send is one the till never knew about.
            closed.append(note.doc_number)
    return still_worth_money, closed


def _salesmen(store: Store, since: datetime | None) -> list[dict[str, Any]]:
    """This store's named sellers - the per-line credit popup.

    Sent whole on every response, active and retired alike on a delta: the
    contract's `deleted` block has no salesmen key, so a seller who has left says
    so on their own row (`is_active: false`) and the till drops them from the
    popup. A bootstrap sends only the working list, because a fresh till has
    nobody to forget.
    """
    rows = Salesman.objects.filter(store=store)
    if since is None:
        rows = rows.filter(is_active=True)
    return [
        {"id": pk, "code": code, "name": name, "is_active": is_active}
        for pk, code, name, is_active in rows.order_by("code").values_list(
            "id", "code", "name", "is_active"
        )
    ]


def _managers(store: Store) -> list[dict[str, Any]]:
    """Who may authorise an over-cap discount at this counter with the line cut.

    The narrowest list this can honestly be, because it is a set of credentials
    that leaves the building: somebody explicitly assigned to *this* store, whose
    boundary is stores at all, who holds `sell >= approve` on the **stored** matrix
    (whatever an administrator has made it - #173), who is not the break-glass
    superuser, and who has actually set a PIN. A blank hash is not a credential,
    and a row carrying one would let the till compare against nothing.

    Sent whole every time and never deltaed: it is a handful of rows, and the one
    thing that must never happen is a till holding a stale copy - a rung
    withdrawn at head office is withdrawn on the next request (Anand's ruling, 30
    Jul), and the counter's copy has to follow.

    Note what the seeded matrix means for this list today: the ratified sheet
    predates the POS and gives both store seats `sell: operate`, so out of the box
    no store person reaches the rung and this list is empty until an administrator
    grants it in the editor. That is a decision about the sheet, not about this
    code.
    """
    candidates = (
        User.objects.filter(
            is_active=True,
            is_superuser=False,
            stores=store,
            scope_type__in=STORE_BOUND_SCOPES,
        )
        .exclude(till_pin_hash="")
        .select_related("role")
        .order_by("id")
    )
    return [
        {
            "user_id": user.id,
            "name": user.full_name or user.username,
            "till_pin_hash": user.till_pin_hash,
        }
        for user in candidates
        if user_can(user, "sell", CAP_APPROVE)
    ]
