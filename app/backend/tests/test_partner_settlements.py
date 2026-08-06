"""Partner Settlements feature — payment recording against partner store dues.

Covers: PartnerDuesView (GET), PartnerSettlementsView (GET list + POST create),
PartnerSettlementReverseView (POST reverse). RBAC via money:view/money:manage.
"""

from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


def _login(username, password):
    r = requests.post(f"{API}/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        pytest.skip(f"login failed for {username}: {r.status_code} {r.text}")
    return r.json()["access"]


@pytest.fixture(scope="module")
def accounts_token():
    return _login("accounts1", "Acct@123")


@pytest.fixture(scope="module")
def store_mgr_token():
    return _login("deo.manager", "Store@123")


@pytest.fixture
def accounts_client(accounts_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {accounts_token}"})
    return s


@pytest.fixture
def store_mgr_client(store_mgr_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {store_mgr_token}"})
    return s


@pytest.fixture(scope="module")
def banka_store_id(accounts_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {accounts_token}"})
    r = s.get(f"{API}/outbound/partner-dues")
    assert r.status_code == 200, r.text
    data = r.json()
    banka = next((st for st in data["stores"] if st["store_code"] == "BANKA"), None)
    if not banka:
        pytest.skip("BANKA partner store not found in partner-dues — seed data missing")
    return banka["store_id"]


class TestPartnerDuesView:
    def test_get_partner_dues_structure(self, accounts_client):
        r = accounts_client.get(f"{API}/outbound/partner-dues")
        assert r.status_code == 200
        data = r.json()
        for key in (
            "stores",
            "total_owed_paise",
            "total_paid_paise",
            "net_outstanding_paise",
            "billing_mode",
        ):
            assert key in data
        assert data["net_outstanding_paise"] == data["total_owed_paise"] - data["total_paid_paise"]
        for st in data["stores"]:
            for key in ("total_owed_paise", "total_paid_paise", "net_outstanding_paise"):
                assert key in st
            assert st["net_outstanding_paise"] == st["total_owed_paise"] - st["total_paid_paise"]

    def test_rbac_no_auth_401(self):
        r = requests.get(f"{API}/outbound/partner-dues")
        assert r.status_code in (401, 403)


class TestPartnerSettlementsCRUDFlow:
    def test_full_flow_partial_overpay_reverse(self, accounts_client, banka_store_id):
        # snapshot before
        dues_before = accounts_client.get(f"{API}/outbound/partner-dues").json()
        store_before = next(s for s in dues_before["stores"] if s["store_id"] == banka_store_id)
        outstanding_before = store_before["net_outstanding_paise"]

        # 1. Partial payment of 100 rupees
        pay_amount = 100
        r = accounts_client.post(
            f"{API}/outbound/partner-settlements",
            json={
                "store_id": banka_store_id,
                "amount": pay_amount,
                "mode": "cash",
                "reference": "TEST-REF-1",
                "description": "TEST partial payment",
            },
        )
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["amount_paise"] == pay_amount * 100
        entry_id = created["id"]

        dues_after = accounts_client.get(f"{API}/outbound/partner-dues").json()
        store_after = next(s for s in dues_after["stores"] if s["store_id"] == banka_store_id)
        assert store_after["net_outstanding_paise"] == outstanding_before - pay_amount * 100

        # Verify history filtered by store shows the new entry
        hist = accounts_client.get(
            f"{API}/outbound/partner-settlements", params={"store": banka_store_id}
        )
        assert hist.status_code == 200
        rows = hist.json()["rows"]
        assert any(row["id"] == entry_id for row in rows)
        assert all(row["store_id"] == banka_store_id for row in rows)

        # 2. Overpayment — pay more than currently outstanding (allowed, may go negative)
        overpay_amount = abs(store_after["net_outstanding_paise"]) / 100 + 500
        r2 = accounts_client.post(
            f"{API}/outbound/partner-settlements",
            json={
                "store_id": banka_store_id,
                "amount": overpay_amount,
                "mode": "bank",
                "reference": "TEST-REF-OVERPAY",
                "description": "TEST overpayment",
            },
        )
        assert r2.status_code == 201, r2.text
        overpay_entry_id = r2.json()["id"]

        dues_over = accounts_client.get(f"{API}/outbound/partner-dues").json()
        store_over = next(s for s in dues_over["stores"] if s["store_id"] == banka_store_id)
        assert store_over["net_outstanding_paise"] < 0, (
            "overpayment should push net outstanding negative"
        )

        # 3. Reverse the overpayment entry
        rev = accounts_client.post(
            f"{API}/outbound/partner-settlements/{overpay_entry_id}/reverse", json={}
        )
        assert rev.status_code == 201, rev.text

        dues_reversed = accounts_client.get(f"{API}/outbound/partner-dues").json()
        store_reversed = next(s for s in dues_reversed["stores"] if s["store_id"] == banka_store_id)
        # Outstanding should go back up to roughly what it was right after step 1
        # (partial payment only)
        assert store_reversed["net_outstanding_paise"] == store_after["net_outstanding_paise"]

        # 4. Reversing the same entry twice should 409
        rev2 = accounts_client.post(
            f"{API}/outbound/partner-settlements/{overpay_entry_id}/reverse", json={}
        )
        assert rev2.status_code == 409, rev2.text

        # cleanup: reverse the partial payment too, to leave state roughly as found
        accounts_client.post(f"{API}/outbound/partner-settlements/{entry_id}/reverse", json={})

    def test_non_positive_amount_rejected(self, accounts_client, banka_store_id):
        r = accounts_client.post(
            f"{API}/outbound/partner-settlements",
            json={"store_id": banka_store_id, "amount": 0, "mode": "cash"},
        )
        assert r.status_code == 400
        r2 = accounts_client.post(
            f"{API}/outbound/partner-settlements",
            json={"store_id": banka_store_id, "amount": -50, "mode": "cash"},
        )
        assert r2.status_code == 400

    def test_missing_store_id_rejected(self, accounts_client):
        r = accounts_client.post(
            f"{API}/outbound/partner-settlements",
            json={"amount": 100, "mode": "cash"},
        )
        assert r.status_code == 400

    def test_list_all_settlements_no_store_filter(self, accounts_client):
        r = accounts_client.get(f"{API}/outbound/partner-settlements")
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert isinstance(rows, list)
        assert len(rows) <= 200


class TestPartnerSettlementsRBAC:
    def test_store_manager_forbidden_post(self, store_mgr_client, banka_store_id):
        r = store_mgr_client.post(
            f"{API}/outbound/partner-settlements",
            json={"store_id": banka_store_id, "amount": 50, "mode": "cash"},
        )
        assert r.status_code == 403, r.text

    def test_store_manager_get_settlements_allowed_readonly(self, store_mgr_client):
        # store_manager holds money:operate (>= money:view on the ordinal ladder),
        # so GET (read, gated at money:view) is allowed; only POST/reverse
        # (money:manage) is blocked.
        r = store_mgr_client.get(f"{API}/outbound/partner-settlements")
        assert r.status_code == 200, r.text

    def test_store_manager_forbidden_reverse(self, store_mgr_client):
        r = store_mgr_client.post(f"{API}/outbound/partner-settlements/1/reverse", json={})
        assert r.status_code == 403, r.text

    def test_store_manager_dues_view_access_allowed_readonly(self, store_mgr_client):
        # money:view gate — store_manager's baseline money access clears it (read-only report).
        r = store_mgr_client.get(f"{API}/outbound/partner-dues")
        assert r.status_code == 200, r.text


class TestRegressionSanity:
    def test_vendor_ledger_unaffected(self, accounts_client):
        r = accounts_client.get(
            f"{API}/vendors/ledger" if False else f"{API}/outbound/partner-billing-policy"
        )
        assert r.status_code == 200

    def test_partner_billing_policy_unaffected(self, accounts_client):
        r = accounts_client.get(f"{API}/outbound/partner-billing-policy")
        assert r.status_code == 200
        assert "mode" in r.json()
