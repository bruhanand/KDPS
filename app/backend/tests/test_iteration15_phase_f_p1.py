"""Iteration 15 — Phase F (P0 identity & scale) + two P1 backend features.

Covers:
  * GET /api/finledger/health (BooksHealthView) — IsFinance gated.
  * GET /api/stockledger/on-hand?group_by=sku — truncation surface.
  * Masters CRUD: stores/brands/seasons/gstins — IsMasterSteward gating.
"""

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
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
        # Magnitude is data-dependent (a fresh DB legitimately has no stock), so assert
        # only the shape here. The on-hand VALUE path is covered hermetically by
        # test_phase_e_commercial_model.test_stock_on_hand_projection_reflects_inward.
        assert isinstance(summary.get("units_on_hand"), int)
        assert isinstance(summary.get("value_rupees"), str)


# ───── Masters stewardship CRUD ────────────────────────────────────────
class TestMastersSteward:
    """Creates ZZ-prefixed masters (store/brand/season/gstin) over HTTP.

    There is deliberately no teardown: masters expose no DELETE endpoint
    (deactivate-by-design) and ``Season`` has no ``is_active`` field, so cleanup
    could never be complete — it would be theater. Instead these writes are
    confined to disposable DBs by the conftest remote-target gate (issue #41):
    against any non-local target they are skipped unless KDPS_TEST_ALLOW_REMOTE=1.
    """

    UNIQUE = uuid.uuid4().hex[:6].upper()

    def _first_id(self, token, collection):
        """The id of the first seeded row of a masters collection."""
        r = requests.get(f"{API}/masters/{collection}", headers=_hdr(token), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("results") or rows.get("rows") or []
        assert rows, f"no {collection} seeded"
        return rows[0]["id"]

    def _first_gstin_id(self, token):
        return self._first_id(token, "gstins")

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
        # This used to post `legal_name`/`active` - neither is a field on the
        # serializer - collect a 400 for the two *required* fields it therefore
        # omitted, and skip itself blaming a GSTIN checksum rule that does not
        # exist. It asserted nothing for months (issue #93). GSTIN is 15 chars:
        # state code, then a PAN-shaped body.
        gstin_value = f"10AAACT{self.UNIQUE[:4]}A1Z5"[:15].ljust(15, "Z")
        payload = {
            "gstin": gstin_value,
            "state_code": "10",
            "state_name": "Bihar",
            "legal_entity": self._first_id(steward_token, "entities"),
            "is_active": True,
        }
        r = requests.post(
            f"{API}/masters/gstins", headers=_hdr(steward_token), json=payload, timeout=15
        )
        assert r.status_code == 201, f"create gstin failed: {r.status_code} {r.text}"
        assert r.json()["gstin"] == gstin_value
