"""Unit tests for vendors.views — covering utility functions, VendorListCreate,
BookingListCreate, BookingDetail, and BookingDraft (AI-read mock)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import User
from masters.models import Brand, Gstin, LegalEntity, Season, Store
from vendors.models import Booking, BookingLine, Vendor
from vendors.views import _financial_year, _rupees_to_paise, _safe_int


# --- Pure utility function tests ------------------------------------------------


class TestRupeesToPaise:
    def test_none_returns_none(self):
        assert _rupees_to_paise(None) is None

    def test_empty_string_returns_none(self):
        assert _rupees_to_paise("") is None

    def test_zero_returns_none(self):
        assert _rupees_to_paise(0) is None

    def test_integer(self):
        assert _rupees_to_paise(100) == 10000

    def test_float(self):
        assert _rupees_to_paise(99.99) == 9999

    def test_string_number(self):
        assert _rupees_to_paise("250.50") == 25050

    def test_invalid_string_returns_none(self):
        assert _rupees_to_paise("abc") is None


class TestSafeInt:
    def test_none_returns_zero(self):
        assert _safe_int(None) == 0

    def test_empty_string_returns_zero(self):
        assert _safe_int("") == 0

    def test_zero(self):
        assert _safe_int(0) == 0

    def test_integer(self):
        assert _safe_int(42) == 42

    def test_string_number(self):
        assert _safe_int("7") == 7

    def test_invalid_string_returns_zero(self):
        assert _safe_int("abc") == 0


class TestFinancialYear:
    def test_april_start(self):
        assert _financial_year(date(2026, 4, 1)) == "26-27"

    def test_march_end(self):
        assert _financial_year(date(2026, 3, 31)) == "25-26"

    def test_january(self):
        assert _financial_year(date(2027, 1, 15)) == "26-27"

    def test_december(self):
        assert _financial_year(date(2025, 12, 1)) == "25-26"


# --- API endpoint tests (DB-backed) ------------------------------------------


@pytest.fixture
def _master_data(db):
    """Create the minimal master data tree for vendor/booking tests."""
    entity = LegalEntity.objects.create(code="kdps", name="KDPS Lifestyle")
    gstin = Gstin.objects.create(
        legal_entity=entity, gstin="10AABCK1234A1Z5", state_code="10", state_name="Bihar"
    )
    store = Store.objects.create(code="DEO", name="Deoghar", gstin=gstin)
    brand = Brand.objects.create(
        code="mufti", name="Mufti", ownership="owned", return_terms="none"
    )
    season = Season.objects.create(code="SS26", name="Spring Summer 2026")
    vendor = Vendor.objects.create(code="VEN01", name="Test Vendor", city="Patna")
    vendor.brands.add(brand)
    return {
        "entity": entity,
        "gstin": gstin,
        "store": store,
        "brand": brand,
        "season": season,
        "vendor": vendor,
    }


@pytest.fixture
def auth_client(db):
    """Return an APIClient authenticated as a regular user."""
    user = User.objects.create_user(username="testuser", password="TestPass123!")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def auth_user(db):
    """Return an authenticated user."""
    return User.objects.create_user(username="testuser2", password="TestPass123!")


@pytest.mark.django_db(transaction=True)
class TestVendorListCreateView:
    def test_list_vendors_returns_active(self, auth_client, _master_data):
        resp = auth_client.get("/api/vendors")
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert resp.data[0]["code"] == "VEN01"

    def test_list_vendors_excludes_inactive(self, auth_client, _master_data):
        Vendor.objects.filter(code="VEN01").update(is_active=False)
        resp = auth_client.get("/api/vendors")
        assert resp.status_code == 200
        assert len(resp.data) == 0

    def test_create_vendor(self, auth_client, _master_data):
        resp = auth_client.post(
            "/api/vendors",
            {"code": "VEN02", "name": "New Vendor", "city": "Delhi", "brands": []},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["code"] == "VEN02"
        assert Vendor.objects.filter(code="VEN02").exists()

    def test_unauthenticated_rejected(self, _master_data):
        client = APIClient()
        resp = client.get("/api/vendors")
        assert resp.status_code == 401


@pytest.mark.django_db(transaction=True)
class TestBookingListCreateView:
    def test_create_booking(self, auth_client, _master_data):
        md = _master_data
        resp = auth_client.post(
            "/api/bookings",
            {
                "vendor": md["vendor"].pk,
                "brand": md["brand"].pk,
                "season": md["season"].pk,
                "vendor_ref": "INV-001",
                "notes": "Test booking",
                "lines": [
                    {"style_code": "STY-A", "size": "M", "booked_qty": 10, "mrp_paise": 150000},
                    {"style_code": "STY-B", "size": "L", "booked_qty": 5, "mrp": "2000"},
                ],
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["status"] == "booked"
        assert resp.data["vendor_ref"] == "INV-001"
        # Check lines were created
        booking = Booking.objects.get(number=resp.data["number"])
        assert booking.lines.count() == 2

    def test_create_booking_with_store_per_line(self, auth_client, _master_data):
        md = _master_data
        resp = auth_client.post(
            "/api/bookings",
            {
                "vendor": md["vendor"].pk,
                "brand": md["brand"].pk,
                "season": md["season"].pk,
                "lines": [
                    {
                        "style_code": "STY-X",
                        "size": "S",
                        "booked_qty": 3,
                        "mrp_paise": 100000,
                        "store": md["store"].pk,
                    },
                ],
            },
            format="json",
        )
        assert resp.status_code == 201
        line = BookingLine.objects.get(booking__number=resp.data["number"])
        assert line.store_id == md["store"].pk

    def test_create_booking_invalid_store_in_line(self, auth_client, _master_data):
        md = _master_data
        resp = auth_client.post(
            "/api/bookings",
            {
                "vendor": md["vendor"].pk,
                "brand": md["brand"].pk,
                "season": md["season"].pk,
                "lines": [
                    {"style_code": "STY-Z", "size": "M", "booked_qty": 2, "store": 99999},
                ],
            },
            format="json",
        )
        assert resp.status_code == 201
        line = BookingLine.objects.get(booking__number=resp.data["number"])
        # Invalid store id falls back to None
        assert line.store_id is None

    def test_list_bookings(self, auth_client, _master_data):
        md = _master_data
        # Create a booking first
        auth_client.post(
            "/api/bookings",
            {
                "vendor": md["vendor"].pk,
                "brand": md["brand"].pk,
                "season": md["season"].pk,
                "lines": [{"style_code": "A", "booked_qty": 1}],
            },
            format="json",
        )
        resp = auth_client.get("/api/bookings")
        assert resp.status_code == 200
        assert len(resp.data) >= 1

    def test_list_bookings_filter_by_status(self, auth_client, _master_data):
        md = _master_data
        auth_client.post(
            "/api/bookings",
            {
                "vendor": md["vendor"].pk,
                "brand": md["brand"].pk,
                "season": md["season"].pk,
                "lines": [{"style_code": "A", "booked_qty": 1}],
            },
            format="json",
        )
        resp = auth_client.get("/api/bookings?status=booked")
        assert resp.status_code == 200
        assert len(resp.data) >= 1

        resp2 = auth_client.get("/api/bookings?status=cancelled")
        assert resp2.status_code == 200
        assert len(resp2.data) == 0

    def test_estimated_value_computed(self, auth_client, _master_data):
        md = _master_data
        resp = auth_client.post(
            "/api/bookings",
            {
                "vendor": md["vendor"].pk,
                "brand": md["brand"].pk,
                "season": md["season"].pk,
                "lines": [
                    {"style_code": "A", "booked_qty": 10, "mrp_paise": 100000},
                ],
            },
            format="json",
        )
        assert resp.status_code == 201
        booking = Booking.objects.get(number=resp.data["number"])
        # 10 × 100000 paise = 1_000_000 paise
        assert booking.estimated_value_paise == 1_000_000


@pytest.mark.django_db(transaction=True)
class TestBookingDetailView:
    def test_retrieve_booking(self, auth_client, _master_data):
        md = _master_data
        resp = auth_client.post(
            "/api/bookings",
            {
                "vendor": md["vendor"].pk,
                "brand": md["brand"].pk,
                "season": md["season"].pk,
                "lines": [{"style_code": "A", "booked_qty": 5}],
            },
            format="json",
        )
        pk = resp.data["id"]
        detail = auth_client.get(f"/api/bookings/{pk}")
        assert detail.status_code == 200
        assert detail.data["id"] == pk

    def test_not_found(self, auth_client, _master_data):
        resp = auth_client.get("/api/bookings/99999")
        assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
class TestBookingDraftView:
    def test_no_file_returns_400(self, auth_client):
        resp = auth_client.post("/api/bookings/draft")
        assert resp.status_code == 400
        assert "file" in resp.data["detail"].lower()

    @patch("vendors.views.read_booking_receipt")
    def test_successful_draft(self, mock_read, auth_client):
        mock_read.return_value = {
            "vendor": "Test Vendor",
            "lines": [{"style_code": "ABC", "size": "M", "quantity": 5, "mrp": "1500"}],
        }
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("test.pdf", b"fake-pdf-data", content_type="application/pdf")
        resp = auth_client.post("/api/bookings/draft", {"file": upload}, format="multipart")
        assert resp.status_code == 200
        assert "source_file_id" in resp.data
        assert resp.data["lines"][0]["mrp_paise"] == 150000

    @patch("vendors.views.read_booking_receipt")
    def test_ai_failure_returns_422(self, mock_read, auth_client):
        mock_read.side_effect = RuntimeError("AI model unavailable")
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("test.pdf", b"fake-pdf", content_type="application/pdf")
        resp = auth_client.post("/api/bookings/draft", {"file": upload}, format="multipart")
        assert resp.status_code == 422
        assert "source_file_id" in resp.data
