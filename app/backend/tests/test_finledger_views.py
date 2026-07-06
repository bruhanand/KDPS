"""Unit tests for finledger.views — covering vendor bill/payment/reverse, cash
movement/reverse, balances, summary, ageing, and permission checks."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, ScopeType, User
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from finledger.posting import post_cash_movement, post_vendor_bill
from vendors.models import Vendor


@pytest.fixture
def vendor(db):
    return Vendor.objects.create(code="VEN01", name="Alpha Vendor", city="Patna")


@pytest.fixture
def finance_role(db):
    return Role.objects.create(
        code="accounts",
        name="Accounts",
        nav_groups=["home", "ledgers"],
    )


@pytest.fixture
def finance_user(db, finance_role):
    user = User.objects.create_user(username="accountant", password="Account@123")
    user.role = finance_role
    user.scope_type = ScopeType.ALL
    user.save()
    return user


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="regular", password="Regular@123")


@pytest.fixture
def finance_client(finance_user):
    client = APIClient()
    client.force_authenticate(user=finance_user)
    return client


@pytest.fixture
def regular_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


# --- Permission tests ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestFinledgerPermissions:
    def test_non_finance_user_blocked_from_vendor_entries(self, regular_client):
        resp = regular_client.get("/api/finledger/vendor/entries")
        assert resp.status_code == 403

    def test_non_finance_user_blocked_from_cash_entries(self, regular_client):
        resp = regular_client.get("/api/finledger/cash/entries")
        assert resp.status_code == 403

    def test_non_finance_user_blocked_from_vendor_balances(self, regular_client):
        resp = regular_client.get("/api/finledger/vendor/balances")
        assert resp.status_code == 403

    def test_unauthenticated_blocked(self):
        client = APIClient()
        resp = client.get("/api/finledger/vendor/entries")
        assert resp.status_code == 401


# --- Vendor Bill ---------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestVendorBillView:
    def test_post_vendor_bill(self, finance_client, vendor):
        resp = finance_client.post(
            "/api/finledger/vendor/bill",
            {
                "vendor_id": vendor.pk,
                "amount": "5000",
                "description": "Invoice #123",
                "reference": "INV-123",
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["kind"] == "bill"
        assert VendorLedgerEntry.objects.filter(vendor=vendor).exists()

    def test_post_vendor_bill_missing_vendor(self, finance_client):
        resp = finance_client.post(
            "/api/finledger/vendor/bill",
            {"vendor_id": 99999, "amount": "1000"},
            format="json",
        )
        assert resp.status_code == 400
        assert "vendor_id" in resp.data["detail"]

    def test_post_vendor_bill_zero_amount(self, finance_client, vendor):
        resp = finance_client.post(
            "/api/finledger/vendor/bill",
            {"vendor_id": vendor.pk, "amount": "0"},
            format="json",
        )
        assert resp.status_code == 400
        assert "amount" in resp.data["detail"].lower()

    def test_non_finance_user_blocked(self, regular_client, vendor):
        resp = regular_client.post(
            "/api/finledger/vendor/bill",
            {"vendor_id": vendor.pk, "amount": "1000"},
            format="json",
        )
        assert resp.status_code == 403


# --- Vendor Payment ------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestVendorPaymentView:
    def test_post_vendor_payment(self, finance_client, vendor):
        resp = finance_client.post(
            "/api/finledger/vendor/payment",
            {
                "vendor_id": vendor.pk,
                "amount": "2000",
                "description": "Payment via UPI",
                "mode": "upi",
                "account": "BANK",
                "also_cash": True,
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["kind"] == "payment"
        # Should also create a cash entry
        assert CashLedgerEntry.objects.filter(vendor=vendor).exists()

    def test_post_vendor_payment_no_cash(self, finance_client, vendor):
        resp = finance_client.post(
            "/api/finledger/vendor/payment",
            {
                "vendor_id": vendor.pk,
                "amount": "1000",
                "also_cash": False,
            },
            format="json",
        )
        assert resp.status_code == 201
        assert CashLedgerEntry.objects.filter(vendor=vendor).count() == 0

    def test_invalid_vendor(self, finance_client):
        resp = finance_client.post(
            "/api/finledger/vendor/payment",
            {"vendor_id": 99999, "amount": "1000"},
            format="json",
        )
        assert resp.status_code == 400

    def test_zero_amount_rejected(self, finance_client, vendor):
        resp = finance_client.post(
            "/api/finledger/vendor/payment",
            {"vendor_id": vendor.pk, "amount": "0"},
            format="json",
        )
        assert resp.status_code == 400


# --- Vendor Reverse ------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestVendorReverseView:
    def test_reverse_bill(self, finance_client, finance_user, vendor):
        entry = post_vendor_bill(vendor, 500000, "Test bill", finance_user)
        resp = finance_client.post(f"/api/finledger/vendor/entries/{entry.pk}/reverse")
        assert resp.status_code == 201
        assert resp.data["kind"] == "reversal"

    def test_double_reverse_returns_409(self, finance_client, finance_user, vendor):
        entry = post_vendor_bill(vendor, 500000, "Test bill", finance_user)
        finance_client.post(f"/api/finledger/vendor/entries/{entry.pk}/reverse")
        resp = finance_client.post(f"/api/finledger/vendor/entries/{entry.pk}/reverse")
        assert resp.status_code == 409

    def test_reverse_nonexistent_returns_404(self, finance_client):
        resp = finance_client.post("/api/finledger/vendor/entries/99999/reverse")
        assert resp.status_code == 404


# --- Vendor Balances & Ageing ---------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestVendorBalancesView:
    def test_empty_balances(self, finance_client):
        resp = finance_client.get("/api/finledger/vendor/balances")
        assert resp.status_code == 200
        assert resp.data["vendors_with_dues"] == 0

    def test_with_outstanding(self, finance_client, finance_user, vendor):
        post_vendor_bill(vendor, 1000000, "Bill 1", finance_user)
        resp = finance_client.get("/api/finledger/vendor/balances")
        assert resp.status_code == 200
        assert resp.data["vendors_with_dues"] == 1
        assert resp.data["total_payable_paise"] == 1000000


@pytest.mark.django_db(transaction=True)
class TestVendorAgeingView:
    def test_empty_ageing(self, finance_client):
        resp = finance_client.get("/api/finledger/vendor/ageing")
        assert resp.status_code == 200
        assert resp.data["total_due_paise"] == 0
        assert resp.data["rows"] == []

    def test_with_open_bill(self, finance_client, finance_user, vendor):
        post_vendor_bill(vendor, 500000, "Recent bill", finance_user)
        resp = finance_client.get("/api/finledger/vendor/ageing")
        assert resp.status_code == 200
        assert resp.data["total_due_paise"] == 500000
        assert len(resp.data["rows"]) == 1
        row = resp.data["rows"][0]
        assert row["vendor_code"] == "VEN01"
        # Recent bill should be in the 0-30 bucket
        assert row["bucket_0_30_paise"] == 500000


# --- Vendor Entries (list) -----------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestVendorEntriesView:
    def test_list_entries(self, finance_client, finance_user, vendor):
        post_vendor_bill(vendor, 300000, "Bill A", finance_user)
        resp = finance_client.get("/api/finledger/vendor/entries")
        assert resp.status_code == 200
        assert resp.data["count"] >= 1

    def test_filter_by_vendor(self, finance_client, finance_user, vendor):
        vendor2 = Vendor.objects.create(code="VEN02", name="Beta Vendor")
        post_vendor_bill(vendor, 300000, "Bill A", finance_user)
        post_vendor_bill(vendor2, 200000, "Bill B", finance_user)
        resp = finance_client.get(f"/api/finledger/vendor/entries?vendor={vendor.pk}")
        assert resp.status_code == 200
        for entry in resp.data["results"]:
            assert entry["vendor"] == vendor.pk


# --- Cash Movement -------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCashMovementView:
    def test_cash_in(self, finance_client):
        resp = finance_client.post(
            "/api/finledger/cash/movement",
            {"direction": "in", "amount": "10000", "description": "Store collection"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["kind"] == "receipt"

    def test_cash_out(self, finance_client):
        resp = finance_client.post(
            "/api/finledger/cash/movement",
            {"direction": "out", "amount": "5000", "description": "Petty cash"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["kind"] == "payment"

    def test_invalid_direction(self, finance_client):
        resp = finance_client.post(
            "/api/finledger/cash/movement",
            {"direction": "sideways", "amount": "1000"},
            format="json",
        )
        assert resp.status_code == 400

    def test_zero_amount_rejected(self, finance_client):
        resp = finance_client.post(
            "/api/finledger/cash/movement",
            {"direction": "in", "amount": "0"},
            format="json",
        )
        assert resp.status_code == 400


# --- Cash Reverse --------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCashReverseView:
    def test_reverse_cash_entry(self, finance_client, finance_user):
        entry = post_cash_movement("in", 100000, "Test receipt", finance_user)
        resp = finance_client.post(f"/api/finledger/cash/entries/{entry.pk}/reverse")
        assert resp.status_code == 201
        assert resp.data["kind"] == "reversal"

    def test_double_reverse_returns_409(self, finance_client, finance_user):
        entry = post_cash_movement("in", 100000, "Test receipt", finance_user)
        finance_client.post(f"/api/finledger/cash/entries/{entry.pk}/reverse")
        resp = finance_client.post(f"/api/finledger/cash/entries/{entry.pk}/reverse")
        assert resp.status_code == 409

    def test_reverse_nonexistent_returns_404(self, finance_client):
        resp = finance_client.post("/api/finledger/cash/entries/99999/reverse")
        assert resp.status_code == 404


# --- Cash Summary & Entries ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCashSummaryView:
    def test_empty_summary(self, finance_client):
        resp = finance_client.get("/api/finledger/cash/summary")
        assert resp.status_code == 200
        assert resp.data["total_paise"] == 0
        assert resp.data["accounts"] == []

    def test_with_movements(self, finance_client, finance_user):
        post_cash_movement("in", 500000, "Cash in", finance_user, account="CASH")
        post_cash_movement("out", 200000, "Cash out", finance_user, account="CASH")
        resp = finance_client.get("/api/finledger/cash/summary")
        assert resp.status_code == 200
        assert resp.data["total_paise"] == 300000


@pytest.mark.django_db(transaction=True)
class TestCashEntriesView:
    def test_list_entries(self, finance_client, finance_user):
        post_cash_movement("in", 100000, "Entry 1", finance_user, account="CASH")
        resp = finance_client.get("/api/finledger/cash/entries")
        assert resp.status_code == 200
        assert resp.data["count"] >= 1

    def test_filter_by_account(self, finance_client, finance_user):
        post_cash_movement("in", 100000, "Cash", finance_user, account="CASH")
        post_cash_movement("in", 200000, "Bank", finance_user, account="BANK")
        resp = finance_client.get("/api/finledger/cash/entries?account=BANK")
        assert resp.status_code == 200
        for entry in resp.data["results"]:
            assert entry["account"] == "BANK"
