"""Unit tests for vendors.models — covering Booking.recompute_status and model str."""

from __future__ import annotations

import pytest

from masters.models import Brand, Gstin, LegalEntity, Season, Store
from vendors.models import Booking, BookingLine, Vendor


@pytest.fixture
def _base(db):
    entity = LegalEntity.objects.create(code="kdps", name="KDPS")
    gstin = Gstin.objects.create(
        legal_entity=entity, gstin="10AABCK1234A1Z5", state_code="10", state_name="Bihar"
    )
    Store.objects.create(code="DEO", name="Deoghar", gstin=gstin)
    brand = Brand.objects.create(code="mufti", name="Mufti", ownership="owned")
    season = Season.objects.create(code="SS26", name="Spring Summer 2026")
    vendor = Vendor.objects.create(code="VEN01", name="Test Vendor")
    vendor.brands.add(brand)
    return {"brand": brand, "season": season, "vendor": vendor}


@pytest.fixture
def booking(_base):
    return Booking.objects.create(
        number="BK-TEST-001",
        vendor=_base["vendor"],
        brand=_base["brand"],
        season=_base["season"],
        status=Booking.Status.BOOKED,
        ownership="owned",
    )


@pytest.mark.django_db(transaction=True)
class TestBookingRecomputeStatus:
    def test_no_lines_no_change(self, booking):
        booking.recompute_status()
        booking.refresh_from_db()
        assert booking.status == Booking.Status.BOOKED

    def test_no_received_stays_booked(self, booking):
        BookingLine.objects.create(
            booking=booking, style_code="A", booked_qty=10, received_qty=0
        )
        booking.recompute_status()
        booking.refresh_from_db()
        assert booking.status == Booking.Status.BOOKED

    def test_partial_received(self, booking):
        BookingLine.objects.create(
            booking=booking, style_code="A", booked_qty=10, received_qty=5
        )
        booking.recompute_status()
        booking.refresh_from_db()
        assert booking.status == Booking.Status.PARTIALLY_RECEIVED

    def test_fully_received(self, booking):
        BookingLine.objects.create(
            booking=booking, style_code="A", booked_qty=10, received_qty=10
        )
        booking.recompute_status()
        booking.refresh_from_db()
        assert booking.status == Booking.Status.RECEIVED

    def test_over_received(self, booking):
        BookingLine.objects.create(
            booking=booking, style_code="A", booked_qty=10, received_qty=15
        )
        booking.recompute_status()
        booking.refresh_from_db()
        assert booking.status == Booking.Status.RECEIVED

    def test_closed_booking_not_changed(self, booking):
        BookingLine.objects.create(
            booking=booking, style_code="A", booked_qty=10, received_qty=10
        )
        booking.status = Booking.Status.CLOSED
        booking.save()
        booking.recompute_status()
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CLOSED

    def test_cancelled_booking_not_changed(self, booking):
        BookingLine.objects.create(
            booking=booking, style_code="A", booked_qty=10, received_qty=10
        )
        booking.status = Booking.Status.CANCELLED
        booking.save()
        booking.recompute_status()
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED

    def test_multiple_lines(self, booking):
        BookingLine.objects.create(
            booking=booking, style_code="A", booked_qty=10, received_qty=10
        )
        BookingLine.objects.create(
            booking=booking, style_code="B", booked_qty=20, received_qty=5
        )
        # Total: booked=30, received=15 → partially received
        booking.recompute_status()
        booking.refresh_from_db()
        assert booking.status == Booking.Status.PARTIALLY_RECEIVED


@pytest.mark.django_db
class TestVendorModel:
    def test_str(self, _base):
        assert str(_base["vendor"]) == "Test Vendor"

    def test_ordering(self, db):
        Vendor.objects.create(code="Z", name="Zebra")
        Vendor.objects.create(code="A", name="Alpha")
        vendors = list(Vendor.objects.values_list("name", flat=True))
        assert vendors == sorted(vendors)


@pytest.mark.django_db
class TestBookingLineModel:
    def test_str(self, booking):
        line = BookingLine.objects.create(
            booking=booking, style_code="STY-X", size="L", booked_qty=7
        )
        assert "STY-X" in str(line)
        assert "7" in str(line)
