"""What the counter knows: the till's bootstrap and its delta feed (#179, D10).

The till bills **offline**. Everything it needs to price a scan, name a piece,
tax it and credit a salesman has to be sitting on the device before the network goes away - so this
module is the whole of the till's knowledge, and a row missing from it is a
counter that cannot sell a shirt it can see on the shelf.

Three shapes are worth reading before the code.

**The payload has no cost in it, by construction.** H2: a store person may know
the ticket price of everything and the cost of nothing. The hazard is not
carelessness, it is convenience - `StockOnHand` carries `net_value_paise` on the
very row the `stock` section is built from, and `Cohort` carries
`unit_cost_paise` on the row the `items` section is built from. So neither
section is built by serialising a model: both go through `values`/`values_list`
naming exactly the columns that may leave, which means a cost cannot ride along by
having been on the object. A test walks the finished payload and fails on any
cost-shaped key or number, and that test is the belt to this braces.

**Big sections are deltaed; small ones are sent whole.** Items and stock are
20,000 rows and get a watermark. The store's own registration, its tax slabs, its
salesmen, its manager PINs, the season master's ordering and the shop floor's
money dials are a handful of rows each: a delta over five rows saves nothing and
would need a deletion channel the contract does not give it, so they are replaced
wholesale on every response. `deleted` therefore names the two sections
that can lose a row invisibly - items and offers.

**The cursor deliberately laps backwards, and even so it is not the whole
guarantee.** `updated_at` is stamped when a row is written, not when its
transaction commits, so a cursor set to the request's own instant can step over a
row that was stamped before the request and landed after it - the classic
watermark hole, and the missed row is missed for ever. The till upserts every
section by key, so re-sending rows costs nothing and losing one costs a barcode
the counter cannot scan; the cursor is therefore held a long lap behind the clock,
sized against the longest write transaction this system has (see `CURSOR_LAP`).

That lap makes the hole very unlikely rather than impossible, so it is not what
the correctness rests on: **a bootstrap cannot miss anything by construction**, and
the till takes one at store open each day. Any row a delta could still lose is
recovered within the day, without anybody having to notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import User
from accounts.till_pin import STORE_BOUND_SCOPES, may_hold_till_pin
from masters.models import Cohort, Customer, GstSlab, Season, Sku, Store
from masters.scoping import actionable_store_ids
from offers.models import Offer
from sell.models import Salesman, SellPolicy
from stockledger.models import StockOnHand

#: How far behind the clock the returned cursor sits. See the module docstring for
#: why it laps at all; this is why it laps *this far*.
#:
#: The lap has to outlast the longest write transaction in the system, because a
#: row stamped at the start of one and committed at the end of it is invisible to
#: any cursor issued in between. The longest is `post_pt_inward`, which is a single
#: `@transaction.atomic` walking a PT row by row and calling `update_or_create` on
#: `Sku` and `Cohort` for each - a 20,000-line PT is tens of thousands of round
#: trips in one transaction, minutes rather than seconds. A quarter of an hour has
#: real headroom over that.
#:
#: The cost of the lap is a delta re-sending a quarter-hour of edits, which is a
#: handful of rows the till upserts. That is the cheap side of an unfair trade.
CURSOR_LAP = timedelta(minutes=15)


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


@dataclass(frozen=True)
class Sync:
    """One request for the till's world: whose counter, and how far back.

    These three travelled as loose arguments to every section builder, and the
    middle one carried its meaning in a null check - `if since is not None` reads
    as a missing value where what it means is "this is a delta, not a bootstrap".
    `is_bootstrap` says that, and `today` rides along because every section that
    judges a deadline has to judge it against the *same* day.
    """

    store: Store
    #: The caller's cursor; `None` is a bootstrap (see `_read_cursor`).
    since: datetime | None
    #: The store-local day this whole answer is judged against.
    today: date

    @property
    def is_bootstrap(self) -> bool:
        return self.since is None

    @property
    def from_moment(self) -> datetime:
        """The cursor, for the delta arms that only run when there is one.

        A property rather than a cast at each site: mypy has to be told that a
        delta has a cursor, and telling it eight times is eight chances to tell it
        wrongly.
        """
        assert self.since is not None, "a bootstrap has no cursor to read from"
        return self.since


def build_dataset(store: Store, since_raw: str) -> dict[str, Any]:
    """The till's whole world, or what changed in it since `since_raw`.

    One `timezone.now()` for the whole answer, taken before any query: it is both
    the day the deadline sections are judged against and the base of the cursor
    handed back.

    An unreadable `since` is a bootstrap, not a refusal - see `_read_cursor`.
    """
    started = timezone.now()
    sync = Sync(store=store, since=_read_cursor(since_raw), today=timezone.localdate(started))

    offers_live, offers_withdrawn = _offers(sync)
    return {
        "cursor": _stamp(started - CURSOR_LAP),
        "full": sync.is_bootstrap,
        "store": {
            "code": store.code,
            "gstin": store.gstin.gstin,
            "state_code": store.gstin.state_code,
        },
        "items": _items(sync),
        "stock": _stock(sync),
        "gst_slabs": _gst_slabs(),
        # Each row carries its own `starts_on`/`ends_on`, so the counter starts
        # and stops an offer on its own clock while offline (grill Q3) - the
        # dates ride inside the data rather than being applied by this query.
        "offers": offers_live,
        "salesmen": _salesmen(sync),
        "managers": _managers(store),
        "seasons": _seasons(),
        "policy": _policy(),
        "customers": _customers(sync),
        "deleted": {
            "items": _withdrawn_items(sync),
            "offers": offers_withdrawn,
        },
    }


def _stamp(moment: datetime) -> str:
    """A cursor, in the one format this endpoint reads back."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _read_cursor(raw: str) -> datetime | None:
    """The caller's cursor, or `None` meaning "start from nothing".

    **Anything unreadable is a bootstrap, never a refusal.** The cursor is opaque
    and ours; a till holding a damaged one cannot repair it, and a GET whose 400
    the queue retries for ever is worse than re-sending 20,000 rows once.

    Both failure shapes have to be caught, and only one of them looks like a
    failure: `parse_datetime` answers `None` for something that is not a timestamp
    at all ("yesterday-ish") but *raises* `ValueError` for something correctly
    shaped and impossible ("2026-02-30T00:00:00Z"). Catching only the first is how
    the self-heal this docstring promises would be true of one damaged cursor and a
    500 for another.
    """
    text = raw.strip()
    if not text:
        return None
    try:
        moment = parse_datetime(text)
    except ValueError:
        return None
    if moment is None:
        return None
    # A cursor is always one we minted, so it always carries `Z`. A naive one can
    # only be a hand-typed or mangled cursor; UTC is the reading that cannot make
    # the delta *skip* rows, whatever the server's local zone is.
    return moment if timezone.is_aware(moment) else timezone.make_aware(moment, UTC)


def _at_store(store: Store) -> QuerySet[StockOnHand]:
    """The shelf: every barcode this store has ever held, whatever it holds now.

    A row at nought is not a row to drop. The piece can walk back in as an
    exchange, and the till still has to name and price it when it does.
    """
    return StockOnHand.objects.filter(store=store)


def _items(sync: Sync) -> list[dict[str, Any]]:
    """One row per sellable (barcode, season) this store has held.

    A season is a buying cohort, so one barcode bought twice is two rows with two
    prices, and the till resolves the scan to the older one (A2). Inactive SKUs
    are absent: head office withdrawing a piece must mean the counter stops
    offering it, and a delta says so out loud through `deleted.items`.
    """
    rows = Cohort.objects.filter(
        barcode__in=_at_store(sync.store).values("sku_code"), sku__is_active=True
    )
    if not sync.is_bootstrap:
        # Three ways an item row can be new *to this till*, and the third is the
        # one a naive delta misses: a cohort bought a season ago at another store,
        # arriving here today, moves no master row at all - only the stock
        # projection. Without it the till would receive a quantity for a barcode
        # it cannot describe or price.
        arrived_here = _at_store(sync.store).filter(updated_at__gt=sync.from_moment)
        rows = rows.filter(
            Q(updated_at__gt=sync.from_moment)
            | Q(sku__updated_at__gt=sync.from_moment)
            | Q(barcode__in=arrived_here.values("sku_code"))
        )
    # `values`, not the model: `Cohort.unit_cost_paise` is the piece's cost (the
    # PT's P RATE) and must never be fetched onto an object this function then
    # serialises. Naming the columns is what makes H2 structural.
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
            "barcode": row["barcode"],
            "season": row["season"],
            "design": row["sku__design"],
            "brand": row["sku__brand"],
            "item": row["sku__item"],
            "size": row["sku__size"],
            "color": row["sku__color"],
            "hsn": row["sku__hsn"],
            "mrp_paise": _ticket_price(row["mrp_paise"], row["sku__mrp_paise"]),
            "no_discount": row["sku__no_discount"],
        }
        for row in rows.order_by("barcode", "season").values(*fields)
    ]


def _ticket_price(cohort_mrp: int | None, sku_mrp: int | None) -> int | None:
    """The MRP printed on this buying lot's tag, or `null` if nobody knows one.

    **Null, never nought.** A PT that quotes no MRP registers the SKU with none
    (`_register_identity` stores `None` deliberately), so an unpriced piece is a
    real thing that reaches a shelf - and a zero here would be a till pricing that
    scan at ₹0, billing it at ₹0, and posting ₹0 of revenue and tax against a
    garment that walked out of the shop. `null` says "this needs a price from a
    human" in a way no number can.

    The fallback is `or` rather than a null test on purpose: a stored nought on the
    cohort is not knowledge either, and must not shadow a good price on the SKU.
    """
    return cohort_mrp or sku_mrp or None


def _withdrawn_items(sync: Sync) -> list[str]:
    """Barcodes this till must stop offering, by barcode.

    Only a delta answers anything here: a fresh bootstrap has nothing cached to
    remove, and an inactive piece is simply absent from `items` instead.

    Deactivating a SKU is the only withdrawal that exists. A cohort is a record of
    a purchase and is never unmade, and a stock row falls to nought rather than
    vanishing - so the barcode, not the (barcode, season) pair, is the identity a
    removal travels under, and it takes every season of that piece with it.
    """
    if sync.is_bootstrap:
        return []
    return list(
        Sku.objects.filter(
            barcode__in=_at_store(sync.store).values("sku_code"),
            is_active=False,
            updated_at__gt=sync.from_moment,
        )
        .order_by("barcode")
        .values_list("barcode", flat=True)
    )


def _stock(sync: Sync) -> list[dict[str, int | str]]:
    """Quantity per barcode. Quantity, and nothing else (H2).

    `net_value_paise` sits on this very row, which is why the two columns that may
    leave are named rather than a serialiser being pointed at the model.
    """
    rows = _at_store(sync.store)
    if not sync.is_bootstrap:
        rows = rows.filter(updated_at__gt=sync.from_moment)
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


def _seasons() -> list[dict[str, Any]]:
    """The season master's own ordering, so the counter can pick the oldest.

    A barcode is a scan-alias, not an identity (A2): the same tag under two buying
    cohorts is two lots at two ticket prices, and a scan that does not name a
    season resolves to the **oldest live** one with stock here. `resolve_piece`
    makes that choice server-side by ranking `(is_closed, sort_order)` from this
    master - and the till has to make the identical choice offline, because the
    season it picks is the season it writes on the line and the accept pipeline
    honours an exact `(barcode, season)` outright. Without the ordering on the
    device the till would fall back to sorting names, and "FW25 before SS26" is
    true only by the accident of the alphabet.

    Whole on every response, like the slabs and the manager list: it is a handful
    of rows, a season closing is a fact the counter must not miss, and `deleted`
    has no channel for it.
    """
    fields = ("code", "name", "status", "sort_order")
    return [
        {"code": code, "name": name, "status": status, "sort_order": sort_order}
        for code, name, status, sort_order in Season.objects.order_by(
            "sort_order", "code"
        ).values_list(*fields)
    ]


def _policy() -> dict[str, str | bool]:
    """The dials the counter has to hold offline.

    The cap is B2: below it a manual discount is the cashier's to give, above it
    the bill will not close without a manager. Both ends of that rule have to
    agree, and only one of them is online. A till that did not know the number
    would let a cashier key in a discount the accept pipeline refuses - days later,
    when the bill is printed, paid for and in a customer's hand.

    So it rides down whole on every response, and as a two-decimal **string** for
    the reason the tax rates are: the till multiplies by it, and a rate that
    arrived as 7.499999 would put the counter and the server on opposite sides of
    a cap.
    """
    return SellPolicy.current().as_till_policy()


def _offer_is_for(offer: Offer, store_code: str, today: date) -> bool:
    """Should this counter be holding this rule at all?

    Three ways a rule stops being this till's business, and the till can only see
    the last of them for itself: head office stopped it, head office took this
    store off it, or its end date passed. The dates are still sent down and still
    judged at the counter (grill Q3) - this is about what is worth sending, not
    about who decides when an offer stops.
    """
    if offer.status != Offer.Status.LIVE:
        return False
    # Upper-cased on both sides: `validate_store_scope` normalises what it
    # stores, `Store.code` is a slug with no normalisation of its own, and a
    # lower-case store code would otherwise send this counter an empty rulebook
    # while the dashboard and the server still found its offers.
    if store_code.upper() not in ((offer.store_scope or {}).get("stores") or []):
        return False
    return offer.ends_on is None or offer.ends_on >= today


def _offers(sync: Sync) -> tuple[list[dict[str, Any]], list[int]]:
    """The rulebook this counter prices with, and the rules it must forget.

    Two things make this awkward for the same underlying reason - a rule can stop
    mattering without anybody writing to its row:

      · **A rule dies of a date.** `ends_on` passes and nothing is stamped, so a
        delta also asks which rules crossed their own end date between the cursor
        and today. A till that was offline over a weekend would otherwise go on
        discounting under a promotion that finished on the Saturday.
      · **A rule can be taken off *this store* rather than stopped.** That edit
        does stamp `updated_at`, but it also drops the row out of any query
        narrowed by store - so the delta would never mention it again and the
        till would keep it for ever. The delta therefore scans the changed rules
        across the network and decides store membership per row, which is the
        only ordering that can report a withdrawal at all.

    A bootstrap has nothing cached, so it reports nothing withdrawn and simply
    omits what it will not send.
    """
    code = sync.store.code.upper()
    rows = Offer.objects.select_related("brand")
    if sync.is_bootstrap:
        live = [
            offer
            for offer in rows.filter(status=Offer.Status.LIVE, store_scope__stores__contains=[code])
            .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=sync.today))
            .order_by("priority", "id")
        ]
        return [offer.as_rule_payload() for offer in live], []

    changed = rows.filter(
        Q(updated_at__gt=sync.from_moment)
        | Q(ends_on__gte=timezone.localdate(sync.from_moment), ends_on__lt=sync.today)
    ).order_by("priority", "id")

    sending: list[dict[str, Any]] = []
    withdrawn: list[int] = []
    for offer in changed:
        if _offer_is_for(offer, code, sync.today):
            sending.append(offer.as_rule_payload())
        else:
            # Sent even for a rule this store never held: an id the till does not
            # know is a delete that does nothing, and the alternative - guessing
            # which store scope a rule used to have - cannot be done from here.
            withdrawn.append(offer.id)
    return sending, withdrawn


def _salesmen(sync: Sync) -> list[dict[str, Any]]:
    """This store's named sellers - the per-line credit popup.

    Sent whole on every response, active and retired alike on a delta: the
    contract's `deleted` block has no salesmen key, so a seller who has left says
    so on their own row (`is_active: false`) and the till drops them from the
    popup. A bootstrap sends only the working list, because a fresh till has
    nobody to forget.
    """
    rows = Salesman.objects.filter(store=sync.store)
    if sync.is_bootstrap:
        rows = rows.filter(is_active=True)
    return [
        {"id": pk, "code": code, "name": name, "is_active": is_active}
        for pk, code, name, is_active in rows.order_by("code").values_list(
            "id", "code", "name", "is_active"
        )
    ]


def _customers(sync: Sync) -> list[dict[str, Any]]:
    """Everybody KDPS has ever billed, by mobile - the counter's phone book (#245).

    **Deliberately not narrowed to this store**, and it is the only section here
    that is not. Every other store-owned list is scoped because shipping another
    shop's shelf or its override PINs would be wrong; a customer is the opposite
    case - a Deoghar regular walking into Ranchi has to be recognised there, so
    the list is all-KDPS (grill Q6). Scoping it would look consistent with the
    sections above it and quietly make the typeahead useless at the second store
    somebody visits.

    Three fields and no fourth: a mobile to find them by, a name to print, and a
    GSTIN so a business bill does not have to be keyed in twice. No purchase
    history rides down - the till is a device on a shop floor, and what a
    customer has ever spent is not a question it should be able to answer.

    Deltaed like items rather than sent whole like the salesmen, because this list
    is the one that only ever grows: it is the whole business's customers, not a
    handful of rows, and re-sending it every five minutes would cost every till
    the entire book to learn about one new shopper. There is no `deleted` channel
    to pair with the watermark and none is needed - a customer row is never
    removed in v1 (db-design), so the only thing a delta can fail to say is a
    thing that cannot happen.
    """
    rows = Customer.objects.all()
    if not sync.is_bootstrap:
        rows = rows.filter(updated_at__gt=sync.from_moment)
    return [
        {"mobile": mobile, "name": name, "gstin": gstin}
        for mobile, name, gstin in rows.order_by("mobile").values_list("mobile", "name", "gstin")
    ]


def _managers(store: Store) -> list[dict[str, Any]]:
    """Who may authorise an over-cap discount at this counter with the line cut.

    The narrowest list this can honestly be, because it is a set of credentials
    that leaves the building: somebody explicitly assigned to *this* store who
    `may_hold_till_pin` (their boundary is stores at all, they hold `sell >=
    approve` on the **stored** matrix - whatever an administrator has made it,
    #173 - and they are not the break-glass superuser), and who has actually set
    one. A blank hash is not a credential, and a row carrying one would let the
    till compare against nothing.

    That sentence lives in `accounts.till_pin` rather than here, because the
    endpoint a manager sets their PIN through has to refuse exactly the people
    this list would refuse to ship.

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
        if may_hold_till_pin(user)
    ]
