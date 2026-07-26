"""Review findings, backend half: the vendor master and how a booking ends.

Two holes the code review found, neither of them in a ticket:

1. ``/api/vendors`` sat on a bare ``IsAuthenticated`` for writes, while every
   other master (stores, brands, seasons, GSTINs) was steward-gated — so a store
   cashier could mint the supplier that future bookings, GRNs and payables hang
   off. And there was no detail route at all: a vendor, once created, could never
   be corrected or retired through the API.

2. A booking had no ending. ``Status.CLOSED`` and ``Status.CANCELLED`` existed on
   the model and nothing could ever reach them, so a season that delivered 40 of
   100 pieces left 60 open for ever — and the access table's Booking *Approve*
   cell (owner, HO ops) gated no endpoint at all.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from masters.models import Brand, Gstin, LegalEntity, Season, Store
from vendors.models import Booking, BookingLine, Vendor


def _user(username: str, role_code: str, *, scope: str = ScopeType.STORE) -> User:
    user = User.objects.create_user(
        username=username, password=TEST_PASSWORD, role=make_role(role_code)
    )
    if scope != user.scope_type:
        user.scope_type = scope
        user.save(update_fields=["scope_type"])
    return user


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def world(db):
    entity = LegalEntity.objects.create(code="kdps", name="KDPS")
    gstin = Gstin.objects.create(
        legal_entity=entity, gstin="10ABCDE1234F1Z5", state_code="10", state_name="Bihar"
    )
    store = Store.objects.create(
        code="DEO", name="Deoghar", store_type=Store.StoreType.STORE, gstin=gstin
    )
    brand = Brand.objects.create(code="lw", name="Localwear", ownership="owned")
    season = Season.objects.create(code="SS26", name="Spring Summer 26", status="open")
    return {"store": store, "brand": brand, "season": season}


# --- 1. The vendor master is master data ----------------------------------


def test_a_cashier_cannot_create_a_vendor(world):
    body = {"code": "acme", "name": "Acme Apparel"}

    r = _client(_user("till", "store_staff")).post("/api/vendors", body, format="json")

    assert r.status_code == 403, r.content
    assert not Vendor.objects.exists()


def test_a_steward_creates_and_corrects_a_vendor(world):
    client = _client(_user("steward", "data_steward"))

    created = client.post(
        "/api/vendors",
        {"code": "acme", "name": "Acme Aparel", "city": "Ludhiana", "brands": [world["brand"].id]},
        format="json",
    )
    assert created.status_code == 201, created.content
    vendor_id = created.json()["id"]
    assert created.json()["brand_names"] == ["Localwear"]

    fixed = client.patch(f"/api/vendors/{vendor_id}", {"name": "Acme Apparel"}, format="json")

    assert fixed.status_code == 200, fixed.content
    assert Vendor.objects.get(pk=vendor_id).name == "Acme Apparel"


def test_a_retired_vendor_leaves_the_pickers_but_not_the_master(world):
    steward = _client(_user("steward2", "it_admin"))
    vendor = Vendor.objects.create(code="old", name="Old Supplier")

    steward.patch(f"/api/vendors/{vendor.id}", {"is_active": False}, format="json")

    listed = steward.get("/api/vendors")
    assert [v["code"] for v in listed.json()] == []
    with_inactive = steward.get("/api/vendors?include_inactive=1")
    assert [v["code"] for v in with_inactive.json()] == ["old"]
    assert Vendor.objects.filter(code="old").exists()


def test_anyone_may_read_the_vendor_list(world):
    """The booking form needs the list; only the edit is a stewardship act."""
    Vendor.objects.create(code="acme", name="Acme Apparel")

    r = _client(_user("till2", "store_staff")).get("/api/vendors")

    assert r.status_code == 200
    assert [v["code"] for v in r.json()] == ["acme"]


# --- 2. How a booking ends ------------------------------------------------


@pytest.fixture
def booking(world):
    vendor = Vendor.objects.create(code="acme", name="Acme Apparel")
    bk = Booking.objects.create(
        number="BK/26-27/SS26/0001",
        vendor=vendor,
        brand=world["brand"],
        season=world["season"],
        destination_store=world["store"],
        status=Booking.Status.BOOKED,
    )
    BookingLine.objects.create(booking=bk, style_code="SH-100", size="M", booked_qty=100)
    return bk


def test_a_short_close_writes_off_the_balance_with_a_reason(booking):
    booking.lines.update(received_qty=40)
    booking.recompute_status()
    assert booking.status == Booking.Status.PARTIALLY_RECEIVED

    r = _client(_user("boss", "owner")).post(
        f"/api/bookings/{booking.id}/close",
        {"action": "close", "reason": "Season over, vendor short-shipped 60 pcs"},
        format="json",
    )

    assert r.status_code == 200, r.content
    body = r.json()
    assert body["status"] == "closed"
    assert body["open_qty"] == 60
    assert body["close_reason"].startswith("Season over")
    assert body["closed_at"] and body["closed_by_name"] is not None


def test_the_reason_is_not_optional(booking):
    r = _client(_user("boss2", "owner")).post(
        f"/api/bookings/{booking.id}/close", {"action": "close", "reason": " "}, format="json"
    )

    assert r.status_code == 400
    booking.refresh_from_db()
    assert booking.status == Booking.Status.BOOKED


def test_the_buyer_cannot_write_off_their_own_order(booking):
    """The matrix gives HO ops `booking: operate` ("Create") and the Approve cell
    to the owner — the same separation that stops the buyer confirming receipt of
    their own order (#130). Writing off the undelivered balance is that decision."""
    for username, role in (("ho", "ho_ops"), ("bm", "brand_manager")):
        r = _client(_user(username, role)).post(
            f"/api/bookings/{booking.id}/close",
            {"action": "close", "reason": "not mine to close"},
            format="json",
        )

        assert r.status_code == 403, f"{role}: {r.content!r}"
    booking.refresh_from_db()
    assert booking.status == Booking.Status.BOOKED


def test_a_booking_goods_arrived_against_cannot_be_cancelled(booking):
    booking.lines.update(received_qty=10)

    r = _client(_user("owner1", "owner")).post(
        f"/api/bookings/{booking.id}/close",
        {"action": "cancel", "reason": "vendor pulled out"},
        format="json",
    )

    assert r.status_code == 409, r.content
    assert "close it" in r.json()["detail"]
    booking.refresh_from_db()
    assert booking.status == Booking.Status.BOOKED


def test_an_untouched_booking_cancels_once(booking):
    client = _client(_user("owner2", "owner"))

    first = client.post(
        f"/api/bookings/{booking.id}/close",
        {"action": "cancel", "reason": "placed against the wrong season"},
        format="json",
    )
    second = client.post(
        f"/api/bookings/{booking.id}/close",
        {"action": "cancel", "reason": "again"},
        format="json",
    )

    assert first.status_code == 200 and first.json()["status"] == "cancelled"
    assert second.status_code == 409


def test_a_late_receipt_cannot_quietly_reopen_a_closed_booking(booking):
    """Belt and braces: `recompute_status` already refuses, and the GRN path
    refuses before it gets there."""
    booking.end(user=None, reason="short-closed", cancel=False)

    r = _client(_user("wh", "warehouse", scope=ScopeType.ALL)).post(
        "/api/inbound/grns",
        {
            "store": booking.destination_store_id,
            "booking_id": booking.id,
            "kind": "branded",
            "lines": [{"style_code": "SH-100", "size": "M", "received_qty": 10}],
        },
        format="json",
    )

    assert r.status_code == 409, r.content
    assert "closed" in r.json()["detail"].lower()
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CLOSED
