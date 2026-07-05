"""Multi-store bookings: `store` lives on each BookingLine (default → override).

A branded booking can span several stores for the same brand (Anand's flow).
A line names its own destination store; a line with none inherits the booking's
default `destination_store`. Store-scoped users (ADR-0003, fail-closed) see /
may receive against a booking only if ANY line lands at one of their stores.
Direct receipts (no booking) keep their own store-scoping — untouched here.

Hermetic (`db` fixture), so it runs in CI's `pytest tests` step.
"""

from __future__ import annotations

from django.db.models import Q

from accounts.models import User
from inbound.views import _booking_touches_stores
from masters.models import Brand, Gstin, LegalEntity, Season, Store
from vendors.models import Booking, BookingLine, Vendor
from vendors.serializers import BookingSerializer


def _fixtures():
    entity = LegalEntity.objects.create(code="e1", name="E1")
    gstin = Gstin.objects.create(
        gstin="10AAACK1234M1Z5", legal_entity=entity, state_code="10", state_name="Bihar"
    )
    deo = Store.objects.create(code="DEO", name="Deoghar", store_type="store", gstin=gstin)
    bkr = Store.objects.create(code="BKR", name="Bokaro", store_type="store", gstin=gstin)
    hzb = Store.objects.create(code="HZB", name="Hazaribagh", store_type="store", gstin=gstin)
    vendor = Vendor.objects.create(code="v", name="V")
    brand = Brand.objects.create(code="b", name="B", ownership="owned", return_terms="none")
    season = Season.objects.create(code="SS26", name="SS26")
    return entity, deo, bkr, hzb, vendor, brand, season


def _booking(vendor, brand, season, *, default_store):
    return Booking.objects.create(
        number=f"BK-{Booking.objects.count() + 1}",
        vendor=vendor,
        brand=brand,
        season=season,
        destination_store=default_store,
        status=Booking.Status.BOOKED,
    )


def test_line_store_persists_and_inherits_default_for_display(db):
    _, deo, bkr, _, vendor, brand, season = _fixtures()
    bk = _booking(vendor, brand, season, default_store=deo)
    inherit = BookingLine.objects.create(booking=bk, style_code="S1", booked_qty=5)  # no store
    override = BookingLine.objects.create(booking=bk, store=bkr, style_code="S2", booked_qty=3)

    data = BookingSerializer(bk).data
    by_id = {ln["id"]: ln for ln in data["lines"]}
    # An inheriting line stores nothing of its own; the UI falls back to the booking default.
    assert by_id[inherit.id]["store"] is None
    assert by_id[inherit.id]["store_name"] is None
    # An overriding line carries its own store + name.
    assert by_id[override.id]["store"] == bkr.id
    assert by_id[override.id]["store_name"] == "Bokaro"
    assert data["destination_store_name"] == "Deoghar"


def test_scope_sees_booking_when_any_line_lands_at_their_store(db):
    _, deo, bkr, hzb, vendor, brand, season = _fixtures()
    bk = _booking(vendor, brand, season, default_store=deo)
    BookingLine.objects.create(booking=bk, style_code="S1", booked_qty=5)  # inherits DEO
    BookingLine.objects.create(booking=bk, store=bkr, style_code="S2", booked_qty=3)  # BKR

    # DEO-scoped: the inheriting line lands at DEO → visible.
    assert _booking_touches_stores(bk, [deo.id])
    # BKR-scoped: the override line lands at BKR → visible.
    assert _booking_touches_stores(bk, [bkr.id])
    # HZB-scoped: no line lands there → fail-closed, not visible.
    assert not _booking_touches_stores(bk, [hzb.id])


def test_pending_query_filter_matches_touching_bookings_only(db):
    """Mirror the PendingBookingsView store filter: any-line-in-scope, distinct."""
    _, deo, bkr, hzb, vendor, brand, season = _fixtures()
    mine = _booking(vendor, brand, season, default_store=deo)
    BookingLine.objects.create(booking=mine, style_code="S1", booked_qty=5)  # inherits DEO
    BookingLine.objects.create(booking=mine, store=bkr, style_code="S2", booked_qty=3)

    theirs = _booking(vendor, brand, season, default_store=hzb)
    BookingLine.objects.create(booking=theirs, store=bkr, style_code="S3", booked_qty=2)  # BKR only

    ids = [deo.id]
    qs = Booking.objects.filter(
        Q(lines__store_id__in=ids) | Q(lines__store__isnull=True, destination_store_id__in=ids)
    ).distinct()
    assert mine in qs  # has a line inheriting the DEO default
    assert theirs not in qs  # HZB default + BKR line, nothing at DEO


def test_warehouse_bound_lines_are_invisible_to_store_scope(db):
    """A line with no store and a booking with no default = warehouse/HO — a
    store-scoped user must never see it (None is never in their id set)."""
    _, deo, _, _, vendor, brand, season = _fixtures()
    bk = _booking(vendor, brand, season, default_store=None)
    # store None + default None → warehouse/HO; invisible to any store scope
    BookingLine.objects.create(booking=bk, style_code="S1", booked_qty=5)
    assert not _booking_touches_stores(bk, [deo.id])


def test_direct_receipt_without_booking_is_not_blocked_here(db):
    """_resolve_booking short-circuits when there is no booking — direct receipts
    (non-branded, no booking) keep their own store-scoping on the GRN, unaffected
    by the booking-line rule."""
    from inbound.views import _resolve_booking

    user = User.objects.create(username="deo.cashier", scope_type="store")
    booking, err = _resolve_booking({}, user)
    assert booking is None and err is None
