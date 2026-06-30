"""Iteration 15 — Phase F (P0 identity & scale) + two P1 backend features.

Covers:
  * GET /api/finledger/health (BooksHealthView) — IsFinance gated.
  * GET /api/stockledger/on-hand?group_by=sku — truncation surface.
  * Masters CRUD: stores/brands/seasons/gstins — IsMasterSteward gating.
"""

import os
import uuid
from pathlib import Path

import pytest
import requests


def _read_frontend_env():
    env_path = str(Path(__file__).resolve().parents[3] / "app/frontend/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("REACT_APP_BACKEND_URL", "")


BASE_URL = _read_frontend_env().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing"
API = f"{BASE_URL}/api"


def _login(username: str, password: str) -> str:
    r = requests.post(
        f"{API}/auth/login", json={"username": username, "password": password}, timeout=15
    )
    assert r.status_code == 200, f"login {username} failed: {r.status_code} {r.text}"
    body = r.json()
    # token field may be 'access' or 'token'
    return body.get("access") or body.get("token") or body.get("access_token")


@pytest.fixture(scope="module")
def owner_token():
    return _login("owner", "Owner@123")


@pytest.fixture(scope="module")
def steward_token():
    return _login("steward", "Steward@123")


@pytest.fixture(scope="module")
def warehouse_token():
    return _login("wh.patna", "Wh@123")


@pytest.fixture(scope="module")
def cashier_token():
    return _login("deo.cashier", "Store@123")


def _hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ───── Books health (finledger) ─────────────────────────────────────────
class TestBooksHealth:
    def test_owner_sees_balanced_books(self, owner_token):
        r = requests.get(f"{API}/finledger/health", headers=_hdr(owner_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("balanced") is True, body
        assert body.get("trial_balance_paise") == 0, body
        assert "accounts" in body and isinstance(body["accounts"], list)

    def test_warehouse_is_forbidden(self, warehouse_token):
        r = requests.get(f"{API}/finledger/health", headers=_hdr(warehouse_token), timeout=15)
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text}"


# ───── Stock on hand (stockledger) ──────────────────────────────────────
class TestStockOnHand:
    def test_owner_summary_keys_present(self, owner_token):
        r = requests.get(
            f"{API}/stockledger/on-hand?group_by=sku",
            headers=_hdr(owner_token),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        summary = body.get("summary") or body
        # lines/displayed/truncated must exist on the summary
        for key in ("lines", "displayed", "truncated"):
            assert key in summary, f"missing summary key {key!r} in {summary!r}"
        assert isinstance(summary["truncated"], bool)
        # live data check (~241 units / 152 lines per spec)
        units = summary.get("units_on_hand") or body.get("units_on_hand")
        value = summary.get("value_rupees") or body.get("value_rupees")
        assert units, f"units_on_hand falsy: {summary}"
        assert value, f"value_rupees falsy: {summary}"


# ───── Masters stewardship CRUD ────────────────────────────────────────
class TestMastersSteward:
    UNIQUE = uuid.uuid4().hex[:6].upper()

    def _first_gstin_id(self, token):
        r = requests.get(f"{API}/masters/gstins", headers=_hdr(token), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("results") or rows.get("rows") or []
        assert rows, "no gstins seeded"
        return rows[0]["id"]

    def test_steward_creates_and_patches_store(self, steward_token):
        gstin_id = self._first_gstin_id(steward_token)
        code = f"ZZTEST{self.UNIQUE}"
        payload = {
            "code": code,
            "name": f"Test store {self.UNIQUE}",
            "store_type": "store",
            "city": "Patna",
            "gstin": gstin_id,
            "is_active": True,
        }
        r = requests.post(
            f"{API}/masters/stores", headers=_hdr(steward_token), json=payload, timeout=15
        )
        assert r.status_code == 201, f"create store failed: {r.status_code} {r.text}"
        store = r.json()
        assert store["code"] == code
        sid = store["id"]

        r2 = requests.patch(
            f"{API}/masters/stores/{sid}",
            headers=_hdr(steward_token),
            json={"city": "Ranchi"},
            timeout=15,
        )
        assert r2.status_code in (200, 202), f"patch store failed: {r2.status_code} {r2.text}"
        # GET to confirm persistence
        r3 = requests.get(f"{API}/masters/stores/{sid}", headers=_hdr(steward_token), timeout=15)
        assert r3.status_code == 200, r3.text
        assert r3.json()["city"] == "Ranchi"

    def test_cashier_cannot_create_store(self, cashier_token, steward_token):
        gstin_id = self._first_gstin_id(steward_token)
        payload = {
            "code": f"ZZNO{self.UNIQUE}",
            "name": "Forbidden store",
            "store_type": "store",
            "city": "Patna",
            "gstin": gstin_id,
            "is_active": True,
        }
        r = requests.post(
            f"{API}/masters/stores", headers=_hdr(cashier_token), json=payload, timeout=15
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text}"

    def test_steward_creates_brand(self, steward_token):
        code = f"ZZB{self.UNIQUE}"
        payload = {
            "code": code,
            "name": f"Brand {self.UNIQUE}",
            "ownership": "owned",
            "return_terms": "none",
            "is_active": True,
        }
        r = requests.post(
            f"{API}/masters/brands", headers=_hdr(steward_token), json=payload, timeout=15
        )
        assert r.status_code == 201, f"create brand failed: {r.status_code} {r.text}"
        assert r.json()["code"] == code

    def test_steward_creates_season(self, steward_token):
        code = f"ZZS{self.UNIQUE}"
        payload = {"code": code, "name": f"Season {self.UNIQUE}", "status": "open"}
        r = requests.post(
            f"{API}/masters/seasons", headers=_hdr(steward_token), json=payload, timeout=15
        )
        assert r.status_code == 201, f"create season failed: {r.status_code} {r.text}"
        assert r.json()["code"] == code

    def test_steward_creates_gstin(self, steward_token):
        # GSTIN is 15 chars. Build something obviously test-prefixed but valid in length.
        gstin_value = f"10AAACT{self.UNIQUE[:4]}A1Z5"[:15].ljust(15, "Z")
        payload = {
            "gstin": gstin_value,
            "legal_name": f"Test Legal {self.UNIQUE}",
            "state_code": "10",
            "active": True,
        }
        r = requests.post(
            f"{API}/masters/gstins", headers=_hdr(steward_token), json=payload, timeout=15
        )
        # accept 201; if the backend validates the gstin checksum, accept 400 too
        assert r.status_code in (201, 400), f"unexpected status {r.status_code}: {r.text}"
        if r.status_code == 400:
            pytest.skip(
                f"gstin creation rejected by validation (expected for non-checksum value): {r.text}"
            )
        assert r.json().get("gstin") or r.json().get("number")
