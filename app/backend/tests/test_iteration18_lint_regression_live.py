"""Iteration 18 — Regression confirmation after LINT-ONLY changes.

Focus: /api/finledger/health still works after the import reorder in
finledger/health.py, RBAC unchanged, vendor bill still ties, and multi-store
bookings read intact.
"""

from __future__ import annotations

import os

import pytest
import requests

BASE_URL = "https://kdps-delivery-check.preview.emergentagent.com"

pytestmark = pytest.mark.skipif(
    os.environ.get("KDPS_TEST_ALLOW_REMOTE") != "1",
    reason="Live-API test — set KDPS_TEST_ALLOW_REMOTE=1 to run",
)


def _login(username: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login {username}: {r.status_code} {r.text}"
    return r.json()["access"]


@pytest.fixture(scope="module")
def owner_token() -> str:
    return _login("owner", "Owner@123")


@pytest.fixture(scope="module")
def accounts_token() -> str:
    return _login("accounts1", "Acct@123")


@pytest.fixture(scope="module")
def warehouse_token() -> str:
    return _login("wh.patna", "Wh@123")


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------- (1) /api/finledger/health shape & values ------------------------


def test_health_owner_200_balanced_and_reconciled(owner_token: str) -> None:
    r = requests.get(f"{BASE_URL}/api/finledger/health", headers=_hdr(owner_token), timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()

    # Trial balance ties exactly
    assert body["balanced"] is True
    assert body["trial_balance_paise"] == 0

    # Top-level reconciliation object
    recon = body["reconciliation"]
    assert recon["reconciled"] is True

    # Vendor sub-block
    v = recon["vendor"]
    assert v["reconciled"] is True
    assert v["drift_paise"] == 0
    assert "subledger_paise" in v
    assert "gl_control_paise" in v

    # Cash sub-block
    c = recon["cash"]
    assert c["reconciled"] is True
    assert c["drift_paise"] == 0
    assert "subledger_paise" in c
    assert "gl_control_paise" in c


# ---------- (2) RBAC unchanged ---------------------------------------------


def test_health_accounts_role_200(accounts_token: str) -> None:
    r = requests.get(
        f"{BASE_URL}/api/finledger/health", headers=_hdr(accounts_token), timeout=15
    )
    assert r.status_code == 200, r.text
    assert r.json()["balanced"] is True


def test_health_warehouse_role_403(warehouse_token: str) -> None:
    r = requests.get(
        f"{BASE_URL}/api/finledger/health", headers=_hdr(warehouse_token), timeout=15
    )
    assert r.status_code == 403, r.text


# ---------- (3) Money flow: vendor bill still ties -------------------------


def test_vendor_bill_still_ties(owner_token: str) -> None:
    vendors = requests.get(
        f"{BASE_URL}/api/vendors", headers=_hdr(owner_token), timeout=15
    )
    assert vendors.status_code == 200, vendors.text
    payload = vendors.json()
    results = payload.get("results") if isinstance(payload, dict) else payload
    assert results, "no vendors seeded"
    vendor_id = results[0]["id"]

    # Snapshot before
    pre = requests.get(
        f"{BASE_URL}/api/finledger/health", headers=_hdr(owner_token), timeout=15
    ).json()
    assert pre["balanced"] is True and pre["reconciliation"]["reconciled"] is True

    # Post a bill
    post = requests.post(
        f"{BASE_URL}/api/finledger/vendor/bill",
        headers=_hdr(owner_token),
        json={
            "vendor_id": vendor_id,
            "amount": "100.00",
            "description": "lint-regression",
        },
        timeout=20,
    )
    assert post.status_code in (200, 201), post.text

    # Snapshot after — still balanced, still reconciled, drifts zero
    after = requests.get(
        f"{BASE_URL}/api/finledger/health", headers=_hdr(owner_token), timeout=15
    ).json()
    assert after["balanced"] is True
    assert after["trial_balance_paise"] == 0
    assert after["reconciliation"]["reconciled"] is True
    assert after["reconciliation"]["vendor"]["drift_paise"] == 0
    assert after["reconciliation"]["cash"]["drift_paise"] == 0


# ---------- (4) Multi-store bookings read unaffected -----------------------


def test_booking_1_multistore_shape(owner_token: str) -> None:
    r = requests.get(f"{BASE_URL}/api/bookings/1", headers=_hdr(owner_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "destination_store_name" in body
    lines = body.get("lines") or []
    assert lines, "expected lines on booking 1"

    # Every line has per-line store/store_name keys present
    for ln in lines:
        assert "store" in ln
        assert "store_name" in ln

    # Shirts inherit Deoghar (store_name None → falls back to booking default),
    # trousers show Bokaro (explicit override).
    shirts = [ln for ln in lines if "shirt" in (ln.get("style_code") or "").lower()
              or "shirt" in (ln.get("style_name") or "").lower()
              or "shirt" in (ln.get("description") or "").lower()]
    trousers = [ln for ln in lines if "trouser" in (ln.get("style_code") or "").lower()
                or "trouser" in (ln.get("style_name") or "").lower()
                or "trouser" in (ln.get("description") or "").lower()]

    booking_default = body["destination_store_name"]
    assert booking_default == "Deoghar" or "Deo" in (booking_default or ""), (
        f"expected Deoghar as default; got {booking_default!r}"
    )

    if shirts:
        s = shirts[0]
        # inherited → store_name is None (UI falls back to booking default)
        assert s["store_name"] in (None, "Deoghar"), (
            f"shirt line should inherit Deoghar, got store_name={s['store_name']!r}"
        )

    if trousers:
        t = trousers[0]
        assert t["store_name"] == "Bokaro", (
            f"trouser line should be Bokaro, got {t['store_name']!r}"
        )
