"""Read scope on Booking (issue #234).

`BookingListCreateView.get_queryset` filtered only on status/brand/season/search
— no store filter at all — so a store login saw every store's bookings, not
just its own. The reported case: `bkr.manager` (scope = Bokaro alone) opened
`/booking` and saw `BK-SS26-0001`, a booking with lines split between Deoghar
and Bokaro. That particular booking touches Bokaro, so seeing it is correct —
the bug is that a login with *zero* lines on a booking would have seen it too,
because nothing ever checked.

The ratified scope rule (issue #234 triage, 7 Aug 2026): a store login sees a
booking only if at least one line lands at a store in its scope, honouring the
top-bar switcher (`X-KDPS-Unit`), fail-closed. Head-office and brand scopes
keep their existing, unrestricted read — Booking carries a `brand`, so the
general ADR-0003 default (fail a brand-scoped caller closed) is the wrong
answer here; a by-brand rule is a deliberately separate, later ticket.

Out of scope must be *indistinguishable from not existing*: the detail endpoint
answers 404, never 403 (the same convention `test_outbound_read_scope.py` set).
"""

from __future__ import annotations

from typing import Any

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from masters.models import Brand, Gstin, LegalEntity, Season, Store
from vendors.models import Booking, BookingLine, Vendor

BOOKINGS = "/api/bookings"
PENDING = "/api/inbound/pending"


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _ids(resp: Any) -> set[int]:
    return {row["id"] for row in resp.json()}


@pytest.fixture()
def scaffold(db):
    """Three stores — DEO, BKR, FAR — mirroring the reported case: a booking
    split across DEO and BKR, a booking touching only DEO, and one bound for the
    warehouse (no destination store at all, invisible to every store scope)."""
    entity = LegalEntity.objects.create(
        code="brs-ent", name="Booking Scope Entity", pan="AAACB1234B"
    )
    gstin = Gstin.objects.create(
        gstin="10AAACB1234B1ZQ", state_code="10", state_name="Bihar", legal_entity=entity
    )
    deo = Store.objects.create(code="BRS-DEO", name="Booking Deoghar", gstin=gstin)
    bkr = Store.objects.create(code="BRS-BKR", name="Booking Bokaro", gstin=gstin)
    far = Store.objects.create(code="BRS-FAR", name="Booking Faraway", gstin=gstin)

    brand = Brand.objects.create(
        code="brs-brand",
        name="ScopeBrand",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    other_brand = Brand.objects.create(
        code="brs-other",
        name="OtherScopeBrand",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    vendor = Vendor.objects.create(name="Booking Scope Vendor", code="brsvnd")
    season = Season.objects.create(code="BRS26", name="Booking Scope Season")

    owner_user = User.objects.create_user(
        username="brs_owner",
        password=TEST_PASSWORD,
        role=make_role("owner", "Owner (booking read scope test)"),
        entity=entity,
        scope_type=ScopeType.ALL,
    )
    deo_user = User.objects.create_user(
        username="brs_deo",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (booking read scope test)"),
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    deo_user.stores.add(deo)
    bkr_user = User.objects.create_user(
        username="brs_bkr",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (booking read scope test)"),
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    bkr_user.stores.add(bkr)
    far_user = User.objects.create_user(
        username="brs_far",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (booking read scope test)"),
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    far_user.stores.add(far)
    brand_user = User.objects.create_user(
        username="brs_brand",
        password=TEST_PASSWORD,
        role=make_role("brand_manager", "Brand Manager (booking read scope test)"),
        entity=entity,
        scope_type=ScopeType.BRAND,
    )
    brand_user.brands.add(brand)

    def _booking(*, brand: Brand, default_store: Store | None, number: str) -> Booking:
        return Booking.objects.create(
            number=number,
            vendor=vendor,
            brand=brand,
            season=season,
            destination_store=default_store,
            status=Booking.Status.BOOKED,
        )

    # The reported shape: default DEO, one line inherits it, one line overrides
    # to BKR — touches DEO and BKR, nothing else.
    split = _booking(brand=brand, default_store=deo, number="BRS-SS26-0001")
    BookingLine.objects.create(booking=split, style_code="SP1", booked_qty=5)  # inherits DEO
    BookingLine.objects.create(booking=split, store=bkr, style_code="SP2", booked_qty=3)

    deo_only = _booking(brand=brand, default_store=deo, number="BRS-SS26-0002")
    BookingLine.objects.create(booking=deo_only, style_code="DO1", booked_qty=2)  # inherits DEO

    warehouse = _booking(brand=brand, default_store=None, number="BRS-SS26-0003")
    BookingLine.objects.create(booking=warehouse, style_code="WH1", booked_qty=1)  # no store at all

    other_brand_booking = _booking(brand=other_brand, default_store=far, number="BRS-SS26-0004")
    BookingLine.objects.create(booking=other_brand_booking, style_code="OB1", booked_qty=1)

    return {
        "deo": deo,
        "bkr": bkr,
        "far": far,
        "owner": owner_user,
        "deo_user": deo_user,
        "bkr_user": bkr_user,
        "far_user": far_user,
        "brand_user": brand_user,
        "split": split,
        "deo_only": deo_only,
        "warehouse": warehouse,
        "other_brand_booking": other_brand_booking,
    }


# -- Store scope: any line in scope, and nothing else -----------------------


@pytest.mark.django_db(transaction=True)
def test_store_login_sees_only_bookings_with_a_line_in_scope(scaffold):
    """The reported booking (split DEO/BKR) is visible from both ends, and
    invisible to a store with zero lines on it."""
    assert _ids(_client(scaffold["deo_user"]).get(BOOKINGS)) == {
        scaffold["split"].id,
        scaffold["deo_only"].id,
    }
    assert _ids(_client(scaffold["bkr_user"]).get(BOOKINGS)) == {scaffold["split"].id}


@pytest.mark.django_db(transaction=True)
def test_a_login_with_zero_lines_on_a_booking_cannot_see_it(scaffold):
    """The reported gap: a store with no line on the booking must see neither
    the list row nor the detail — a 404, not a 403 (ADR-0003: indistinguishable
    from not existing)."""
    client = _client(scaffold["far_user"])

    assert scaffold["split"].id not in _ids(client.get(BOOKINGS))
    assert client.get(f"{BOOKINGS}/{scaffold['split'].id}").status_code == 404
    assert client.get(f"{BOOKINGS}/{scaffold['deo_only'].id}").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_store_login_can_open_its_own_booking_by_id(scaffold):
    client = _client(scaffold["bkr_user"])
    assert client.get(f"{BOOKINGS}/{scaffold['split'].id}").status_code == 200


@pytest.mark.django_db(transaction=True)
def test_a_warehouse_bound_booking_is_invisible_to_every_store_login(scaffold):
    """No destination store and no line store = warehouse/HO — `None` is never
    in a store scope's id set."""
    for user in (scaffold["deo_user"], scaffold["bkr_user"], scaffold["far_user"]):
        client = _client(user)
        assert scaffold["warehouse"].id not in _ids(client.get(BOOKINGS))
        assert client.get(f"{BOOKINGS}/{scaffold['warehouse'].id}").status_code == 404


# -- The X-KDPS-Unit switcher, same contract as every other store screen ----


@pytest.mark.django_db(transaction=True)
def test_the_unit_switcher_narrows_a_network_scoped_caller_too(scaffold):
    """An `all`-scope login sees everything by default, and only its chosen
    unit's bookings once it picks one in the top bar — the same rule the other
    store screens already honour."""
    owner = _client(scaffold["owner"])

    assert _ids(owner.get(BOOKINGS)) >= {
        scaffold["split"].id,
        scaffold["deo_only"].id,
        scaffold["warehouse"].id,
    }
    narrowed = _ids(owner.get(BOOKINGS, headers={"X-KDPS-Unit": scaffold["bkr"].code}))
    assert narrowed == {scaffold["split"].id}


# -- Brand scope: the deliberate carve-out -----------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_brand_scoped_caller_keeps_its_existing_unrestricted_read(scaffold):
    """Booking carries a brand, unlike the storeless documents the generic
    ADR-0003 default was built for — the ratified rule leaves a brand manager's
    read exactly as it was before this fix, including bookings for a brand they
    are not even entitled to (a deliberate interim; a by-brand rule is a
    separate, later ticket, same as #110 for transfers)."""
    client = _client(scaffold["brand_user"])

    seen = _ids(client.get(BOOKINGS))
    assert seen >= {
        scaffold["split"].id,
        scaffold["deo_only"].id,
        scaffold["warehouse"].id,
        scaffold["other_brand_booking"].id,
    }
    assert client.get(f"{BOOKINGS}/{scaffold['other_brand_booking'].id}").status_code == 200


# -- The sibling that answers the same document through another door --------


@pytest.mark.django_db(transaction=True)
def test_pending_bookings_queue_honours_the_same_store_scope(scaffold):
    """`inbound.PendingBookingsView` reads through the same `scope_bookings`
    helper (#234) — a store login gets the same answer here as on the Booking
    list, not a second, differently-shaped filter."""
    assert _ids(_client(scaffold["bkr_user"]).get(PENDING)) == {scaffold["split"].id}
    assert scaffold["split"].id not in _ids(_client(scaffold["far_user"]).get(PENDING))
