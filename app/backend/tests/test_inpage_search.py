"""In-page search on the screen you are standing on (issue #102), at the API seam.

The top bar already searches everything (#86). This is the other half: the list
you are already looking at narrows in place. One query parameter — ``?q=`` — is
honoured identically by every list endpoint, so a store person learns the
behaviour once.

Four properties are asserted here and none of them is about implementation:

* **the term narrows the list, on the server** — the answer is smaller, and the
  count the screen prints comes down with it;
* **scope survives the search** — searching is never a way around
  ``visible_store_ids``: a term that matches a row at another store answers with
  nothing, not with that row;
* **a scan resolves** — a barcode typed by a wedge scanner into the stock box
  lands on that barcode's stock through the scan-alias model;
* **an empty term changes nothing** — the list, its totals and the deep-link
  filters from a global-search result read exactly as they do without ``q``.
"""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, ScopeType, User
from accounts.rbac_matrix import section_access_for
from core.documents import VoucherSeries
from masters.models import Brand, Gstin, LegalEntity, Season, Sku, Store
from outbound.models import StoreTransfer
from stockledger.models import StockOnHand
from tests._creds import TEST_PASSWORD
from vendors.models import Booking

ON_HAND = "/api/stockledger/on-hand"
BOOKINGS = "/api/bookings"
TRANSFERS = "/api/outbound/transfers"


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _stock(store: Store, gstin: Gstin, **kw: Any) -> StockOnHand:
    qty = kw.pop("net_qty", 5)
    return StockOnHand.objects.create(
        store=store,
        gstin=gstin,
        season="SS26",
        item="shirt",
        hsn="6205",
        net_qty=qty,
        net_value_paise=qty * 90000,
        **kw,
    )


@pytest.fixture()
def scaffold(db):
    """Two stores — DEO, which the caller manages, and BNK, which they must never
    see — each carrying stock, a booking and a transfer whose names collide on a
    shared term, so a leak would show up as an extra row rather than as silence."""
    entity = LegalEntity.objects.create(code="ips-ent", name="Search Entity", pan="AAACS4322B")
    gstin_jh = Gstin.objects.create(
        gstin="20AAACS4322B1ZQ", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    gstin_bh = Gstin.objects.create(
        gstin="10AAACS4322B1ZQ", state_code="10", state_name="Bihar", legal_entity=entity
    )
    deo = Store.objects.create(code="IPS-DEO", name="Search Deoghar", gstin=gstin_jh)
    bnk = Store.objects.create(code="IPS-BNK", name="Search Banka", gstin=gstin_bh)

    for code in ("IPS-DEO", "IPS-BNK"):
        VoucherSeries.objects.create(
            fy="26-27", store_code=code, doc_type="STO", prefix=f"{code}/STO/26-27/", next_seq=1
        )

    # A barcode is a scan alias: the master row is what a scan resolves through,
    # and stock is a count under it.
    sku = Sku.objects.create(
        barcode="IPS-BAR-001",
        design="KURTA77",
        color="Blue",
        size="40",
        brand="SearchBrand",
        item="shirt",
        hsn="6205",
        mrp_paise=199900,
    )
    _stock(
        deo,
        gstin_jh,
        sku_code=sku.barcode,
        design="KURTA77",
        color="Blue",
        size="40",
        brand="SearchBrand",
        net_qty=7,
    )
    # Same design at the other store — the row a search must never surface.
    _stock(
        bnk,
        gstin_bh,
        sku_code="IPS-BAR-999",
        design="KURTA77",
        color="Red",
        size="40",
        brand="SearchBrand",
        net_qty=500,
    )
    # A second style at the caller's own store, so a term genuinely narrows.
    _stock(
        deo,
        gstin_jh,
        sku_code="IPS-BAR-002",
        design="DENIM10",
        color="Black",
        size="32",
        brand="OtherBrand",
        net_qty=3,
    )
    # A barcode the scanned one is a strict prefix of. A scan means *this tag*,
    # so it must not drag this row along with it.
    Sku.objects.create(
        barcode="IPS-BAR-0010",
        design="KURTA77",
        color="Green",
        size="42",
        brand="SearchBrand",
        item="shirt",
        hsn="6205",
        mrp_paise=199900,
    )
    _stock(
        deo,
        gstin_jh,
        sku_code="IPS-BAR-0010",
        design="KURTA77",
        color="Green",
        size="42",
        brand="SearchBrand",
        net_qty=11,
    )

    brand = Brand.objects.create(
        code="ips-brand",
        name="SearchBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    other_brand = Brand.objects.create(
        code="ips-other",
        name="OtherBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    season = Season.objects.create(code="ips-ss26", name="Search SS26")
    other_season = Season.objects.create(code="ips-aw26", name="Search AW26")
    from vendors.models import Vendor

    vendor = Vendor.objects.create(name="Kurta Traders", code="ipsvnd")
    other_vendor = Vendor.objects.create(name="Denim House", code="ipsvnd2")
    booking_kurta = Booking.objects.create(
        number="IPS-BK-KURTA",
        vendor=vendor,
        brand=brand,
        season=season,
        destination_store=deo,
        status=Booking.Status.BOOKED,
    )
    booking_denim = Booking.objects.create(
        number="IPS-BK-DENIM",
        vendor=other_vendor,
        brand=other_brand,
        season=other_season,
        destination_store=bnk,
        status=Booking.Status.BOOKED,
    )

    # One transfer the caller is an end of, one entirely between other stores.
    own_transfer = StoreTransfer(source_store=deo, destination_store=bnk)
    own_transfer.save()
    own_transfer.post()
    foreign = Store.objects.create(code="IPS-FAR", name="Search Faraway", gstin=gstin_bh)
    VoucherSeries.objects.create(
        fy="26-27", store_code="IPS-FAR", doc_type="STO", prefix="IPS-FAR/STO/26-27/", next_seq=1
    )
    foreign_transfer = StoreTransfer(source_store=foreign, destination_store=bnk)
    foreign_transfer.save()
    foreign_transfer.post()

    store_role = Role.objects.create(
        code="store_manager",
        name="Store Manager (in-page search test)",
        section_access=section_access_for("store_manager"),
    )
    store_user = User.objects.create_user(
        username="ips_store",
        password=TEST_PASSWORD,
        role=store_role,
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    store_user.stores.add(deo)

    owner_role = Role.objects.create(
        code="owner",
        name="Owner (in-page search test)",
        section_access=section_access_for("owner"),
    )
    owner = User.objects.create_user(
        username="ips_owner",
        password=TEST_PASSWORD,
        role=owner_role,
        entity=entity,
        scope_type=ScopeType.ALL,
    )
    return {
        "deo": deo,
        "bnk": bnk,
        "sku": sku,
        "booking_kurta": booking_kurta,
        "booking_denim": booking_denim,
        "own_transfer": own_transfer,
        "foreign_transfer": foreign_transfer,
        "store_user": store_user,
        "owner": owner,
    }


# -- Stock on Hand ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_on_hand_narrows_to_the_term_and_the_count_follows(scaffold):
    """The screen's own box narrows the list, and the line count it prints is the
    searched set — not the number it would have shown unsearched."""
    client = _client(scaffold["store_user"])
    all_rows = client.get(f"{ON_HAND}?group_by=sku").json()
    assert all_rows["summary"]["lines"] == 3

    body = client.get(f"{ON_HAND}?group_by=sku&q=DENIM").json()
    assert [r["sku_code"] for r in body["rows"]] == ["IPS-BAR-002"]
    assert body["summary"]["lines"] == 1
    assert body["summary"]["units_on_hand"] == 3


@pytest.mark.django_db(transaction=True)
def test_on_hand_search_cannot_reach_another_store(scaffold):
    """`KURTA77` names a style at both stores. The store person gets their own
    row and is never told the other one exists."""
    body = _client(scaffold["store_user"]).get(f"{ON_HAND}?group_by=sku&q=KURTA77").json()
    assert {r["sku_code"] for r in body["rows"]} == {"IPS-BAR-001", "IPS-BAR-0010"}
    assert body["summary"]["units_on_hand"] == 18  # 7 + 11, never the 500 at Banka

    # A term that matches ONLY the other store's row answers with nothing.
    empty = _client(scaffold["store_user"]).get(f"{ON_HAND}?group_by=sku&q=IPS-BAR-999").json()
    assert empty["rows"] == []
    assert empty["summary"]["lines"] == 0

    # …and the same term, for someone whose scope reaches both, finds it.
    seen = _client(scaffold["owner"]).get(f"{ON_HAND}?group_by=sku&q=IPS-BAR-999").json()
    assert [r["sku_code"] for r in seen["rows"]] == ["IPS-BAR-999"]


@pytest.mark.django_db(transaction=True)
def test_on_hand_search_resolves_a_scanned_barcode(scaffold):
    """A wedge scan is a whole barcode. It resolves through the scan alias to that
    barcode's stock alone — `IPS-BAR-0010` sits right beside it and is not what
    was scanned, so a substring match here would be the wrong answer."""
    body = _client(scaffold["store_user"]).get(f"{ON_HAND}?group_by=sku&q=IPS-BAR-001").json()
    assert [r["sku_code"] for r in body["rows"]] == ["IPS-BAR-001"]
    assert body["summary"]["units_on_hand"] == 7

    # Typing part of a barcode is not a scan, and still narrows the ordinary way.
    typed = _client(scaffold["store_user"]).get(f"{ON_HAND}?group_by=sku&q=IPS-BAR-00").json()
    assert {r["sku_code"] for r in typed["rows"]} == {
        "IPS-BAR-001",
        "IPS-BAR-0010",
        "IPS-BAR-002",
    }


@pytest.mark.django_db(transaction=True)
def test_on_hand_empty_term_reads_exactly_as_today(scaffold):
    """An empty box is not a search. The answer — rows and totals — is the one the
    screen renders with no `q` at all, including a global-search deep link."""
    client = _client(scaffold["store_user"])
    plain = client.get(f"{ON_HAND}?group_by=sku").json()
    blank = client.get(f"{ON_HAND}?group_by=sku&q=").json()
    spaces = client.get(f"{ON_HAND}?group_by=sku&q=%20%20").json()
    assert blank == plain
    assert spaces == plain

    deep = client.get(f"{ON_HAND}?group_by=sku&sku=IPS-BAR-001").json()
    deep_blank = client.get(f"{ON_HAND}?group_by=sku&sku=IPS-BAR-001&q=").json()
    assert deep_blank == deep
    assert [r["sku_code"] for r in deep["rows"]] == ["IPS-BAR-001"]


@pytest.mark.django_db(transaction=True)
def test_on_hand_search_composes_with_the_deep_link(scaffold):
    """Arriving from a global-search link and then typing narrows within it — the
    two filters compose rather than one replacing the other."""
    client = _client(scaffold["store_user"])
    body = client.get(f"{ON_HAND}?group_by=sku&sku=IPS-BAR-001&q=DENIM").json()
    assert body["rows"] == []


# -- Bookings ---------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_bookings_search_matches_number_vendor_and_brand(scaffold):
    """One box, several fields: the booking number a person half-remembers, the
    vendor they rang, or the brand they are chasing."""
    client = _client(scaffold["owner"])
    for term in ("IPS-BK-KURTA", "Kurta Traders", "SearchBrand", "ips-ss26"):
        numbers = [b["number"] for b in client.get(f"{BOOKINGS}?q={term}").json()]
        assert numbers == ["IPS-BK-KURTA"], term

    assert [b["number"] for b in client.get(f"{BOOKINGS}?q=DENIM").json()] == ["IPS-BK-DENIM"]
    assert client.get(f"{BOOKINGS}?q=nothing-matches-this").json() == []


@pytest.mark.django_db(transaction=True)
def test_bookings_empty_term_reads_exactly_as_today(scaffold):
    client = _client(scaffold["owner"])
    assert client.get(f"{BOOKINGS}?q=").json() == client.get(BOOKINGS).json()


@pytest.mark.django_db(transaction=True)
def test_bookings_search_stays_inside_the_caller_scope(scaffold):
    """The booking list is not store-scoped yet — #101 owns that — so this asserts
    the property that *is* true today and will keep being true after it lands:
    a search answers with a subset of what the same caller sees unsearched."""
    client = _client(scaffold["store_user"])
    unsearched = {b["number"] for b in client.get(BOOKINGS).json()}
    searched = {b["number"] for b in client.get(f"{BOOKINGS}?q=IPS-BK").json()}
    assert searched <= unsearched
    assert searched, "the term should match something the caller can already see"


# -- Transfers --------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_transfers_search_matches_number_and_both_stores(scaffold):
    """A transfer is found by its voucher number or by either end of the move."""
    client = _client(scaffold["owner"])
    own = scaffold["own_transfer"]
    assert [t["id"] for t in client.get(f"{TRANSFERS}?q={own.doc_number}").json()] == [own.id]
    assert [t["id"] for t in client.get(f"{TRANSFERS}?q=IPS-DEO").json()] == [own.id]
    assert [t["id"] for t in client.get(f"{TRANSFERS}?q=Deoghar").json()] == [own.id]
    assert client.get(f"{TRANSFERS}?q=no-such-transfer").json() == []


@pytest.mark.django_db(transaction=True)
def test_transfers_search_cannot_reach_a_transfer_between_other_stores(scaffold):
    """Both ends of a move may see it, and nobody else may. Searching for the
    voucher number of a transfer between two other stores answers with nothing —
    the sharp case, because a two-sided scope is the easiest one to widen."""
    client = _client(scaffold["store_user"])
    foreign = scaffold["foreign_transfer"]
    assert client.get(f"{TRANSFERS}?q={foreign.doc_number}").json() == []
    assert [t["id"] for t in client.get(f"{TRANSFERS}?q=IPS-").json()] == [
        scaffold["own_transfer"].id
    ]
    # The same number, for someone whose scope reaches it, is found.
    assert [
        t["id"]
        for t in _client(scaffold["owner"]).get(f"{TRANSFERS}?q={foreign.doc_number}").json()
    ] == [foreign.id]


@pytest.mark.django_db(transaction=True)
def test_transfer_list_is_store_scoped_even_without_a_search(scaffold):
    """Search only narrows what scope already allows, so scope has to be there
    first: an unsearched list must not carry other stores' transfers either."""
    ids = [t["id"] for t in _client(scaffold["store_user"]).get(TRANSFERS).json()]
    assert ids == [scaffold["own_transfer"].id]


@pytest.mark.django_db(transaction=True)
def test_transfers_empty_term_reads_exactly_as_today(scaffold):
    client = _client(scaffold["store_user"])
    assert client.get(f"{TRANSFERS}?q=").json() == client.get(TRANSFERS).json()


# -- The contract itself ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_every_screen_uses_the_same_parameter_name(scaffold):
    """One contract, not three. If a screen invented its own parameter name this
    is where it shows up: `q` is ignored by nobody."""
    client = _client(scaffold["owner"])
    nonsense = "zzz-no-such-thing-zzz"
    assert client.get(f"{ON_HAND}?group_by=sku&q={nonsense}").json()["rows"] == []
    assert client.get(f"{BOOKINGS}?q={nonsense}").json() == []
    assert client.get(f"{TRANSFERS}?q={nonsense}").json() == []


@pytest.mark.django_db(transaction=True)
def test_search_is_case_insensitive(scaffold):
    """Plain substring matching, ignoring case — a store person does not type in
    the case the PT file happened to use."""
    client = _client(scaffold["owner"])
    assert [r["sku_code"] for r in client.get(f"{ON_HAND}?group_by=sku&q=kurta77").json()["rows"]]
    assert [b["number"] for b in client.get(f"{BOOKINGS}?q=kurta").json()] == ["IPS-BK-KURTA"]
