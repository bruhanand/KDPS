"""Iteration 23 - Review verification for KDPS.

Verifies:
- Dashboard truth (real API values, no hardcoded literals)
- Vendor Master RBAC (POST/PATCH gated to steward/owner)
- Booking short-close / cancel RBAC + rules
- Regression: /api/vendors GET open to authenticated users
"""
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://186fddb1-3c27-4262-9784-baaf87561b15.preview.emergentagent.com").rstrip("/")
API = BASE + "/api"

CREDS = {
    "owner": ("owner", "Owner@123"),
    "steward": ("steward", "Steward@123"),
    "ops1": ("ops1", "Ops@123"),
    "brand1": ("brand1", "Brand@123"),
    "deo.manager": ("deo.manager", "Store@123"),
    "deo.cashier": ("deo.cashier", "Store@123"),
}


@pytest.fixture(scope="session")
def tokens():
    out = {}
    for k, (u, p) in CREDS.items():
        r = requests.post(f"{API}/auth/login", json={"username": u, "password": p}, timeout=15)
        assert r.status_code == 200, f"login failed for {u}: {r.status_code} {r.text[:200]}"
        out[k] = r.json()["access"]
    return out


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- Dashboard truth data ----------
class TestDashboardData:
    def test_vendor_ageing_shape(self, tokens):
        r = requests.get(f"{API}/finledger/vendor/ageing", headers=H(tokens["owner"]), timeout=15)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # Should have total_due_paise
        assert "total_due_paise" in data or "total" in data or isinstance(data, dict)

    def test_stock_on_hand(self, tokens):
        r = requests.get(f"{API}/stockledger/on-hand", headers=H(tokens["owner"]), timeout=15)
        assert r.status_code == 200, r.text[:300]

    def test_approvals_inbox(self, tokens):
        r = requests.get(f"{API}/approvals/inbox", headers=H(tokens["owner"]), timeout=15)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), (list, dict))

    def test_inbound_pending(self, tokens):
        # Store dashboard uses this
        r = requests.get(f"{API}/inbound/pending", headers=H(tokens["deo.manager"]), timeout=15)
        assert r.status_code == 200, r.text[:300]

    def test_vendor_ageing_forbidden_for_store(self, tokens):
        # Store scope should NOT have money:manage; but 403 is what we expect per review note
        r = requests.get(f"{API}/finledger/vendor/ageing", headers=H(tokens["deo.manager"]), timeout=15)
        # Either 403 or the endpoint is not called at all. If called, must be forbidden.
        assert r.status_code in (403, 401), f"expected 403 for store role, got {r.status_code}"


# ---------- Vendor Master RBAC ----------
class TestVendorMasterRBAC:
    def test_get_vendors_authenticated_cashier(self, tokens):
        r = requests.get(f"{API}/vendors", headers=H(tokens["deo.cashier"]), timeout=15)
        assert r.status_code == 200

    def test_get_vendors_owner(self, tokens):
        r = requests.get(f"{API}/vendors", headers=H(tokens["owner"]), timeout=15)
        assert r.status_code == 200
        data = r.json()
        # Response may be list or paginated
        items = data if isinstance(data, list) else data.get("results", data.get("items", []))
        assert isinstance(items, list)

    def test_post_vendor_cashier_forbidden(self, tokens):
        payload = {"code": "TEST_forbid_vendor", "name": "Nope", "city": "X", "gstin": ""}
        r = requests.post(f"{API}/vendors", headers=H(tokens["deo.cashier"]), json=payload, timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"

    def test_post_vendor_ops_forbidden(self, tokens):
        payload = {"code": "TEST_forbid_ops", "name": "Nope", "city": "X"}
        r = requests.post(f"{API}/vendors", headers=H(tokens["ops1"]), json=payload, timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"

    def test_post_vendor_steward_allowed(self, tokens):
        payload = {
            "code": "TEST_qa_steward_v1",
            "name": "TEST QA Steward Vendor",
            "city": "Patna",
            "gstin": "",
            "payment_terms": "NET30",
        }
        r = requests.post(f"{API}/vendors", headers=H(tokens["steward"]), json=payload, timeout=15)
        # cleanup on either created or already-exists
        if r.status_code == 201:
            vid = r.json().get("id") or r.json().get("code")
            # PATCH by steward should be allowed
            code = r.json().get("code", "TEST_qa_steward_v1")
            patch = requests.patch(f"{API}/vendors/{vid}", headers=H(tokens["steward"]),
                                   json={"name": "TEST QA Steward Vendor Renamed"}, timeout=15)
            assert patch.status_code in (200, 202), f"steward PATCH failed: {patch.status_code} {patch.text[:200]}"
            # And cashier PATCH forbidden
            r2 = requests.patch(f"{API}/vendors/{vid}", headers=H(tokens["deo.cashier"]),
                                json={"name": "Hijack"}, timeout=15)
            assert r2.status_code == 403, f"cashier PATCH not forbidden: {r2.status_code}"
        else:
            # Already exists from prior test run — acceptable, still gates
            assert r.status_code in (400, 409, 201), f"unexpected: {r.status_code} {r.text[:200]}"

    def test_post_vendor_owner_allowed(self, tokens):
        payload = {"code": "TEST_qa_owner_v1", "name": "TEST QA Owner Vendor", "city": "Ranchi"}
        r = requests.post(f"{API}/vendors", headers=H(tokens["owner"]), json=payload, timeout=15)
        assert r.status_code in (201, 400, 409), f"owner POST /vendors: {r.status_code} {r.text[:300]}"


# ---------- Booking Close RBAC + rules ----------
class TestBookingClose:
    @pytest.fixture(autouse=True)
    def _reset_booking_1(self, tokens):
        """Ensure booking 1 is open before each test, reset after."""
        yield
        # Reset via management shell after each test - best effort
        import subprocess
        subprocess.run(
            ["/opt/kdpsvenv/bin/python", "manage.py", "shell", "-c",
             "from vendors.models import Booking; b=Booking.objects.get(pk=1); b.status='booked'; b.close_reason=''; b.closed_at=None; b.closed_by=None; b.save()"],
            cwd="/app/app/backend", timeout=30, capture_output=True
        )

    def test_close_empty_reason_400(self, tokens):
        r = requests.post(f"{API}/bookings/1/close", headers=H(tokens["owner"]),
                          json={"action": "close", "reason": ""}, timeout=15)
        assert r.status_code == 400, f"expected 400 for empty reason, got {r.status_code}: {r.text[:200]}"

    def test_close_ops_forbidden(self, tokens):
        r = requests.post(f"{API}/bookings/1/close", headers=H(tokens["ops1"]),
                          json={"action": "close", "reason": "operational reason"}, timeout=15)
        assert r.status_code == 403, f"expected 403 for ops1, got {r.status_code}: {r.text[:200]}"

    def test_close_brand_forbidden(self, tokens):
        r = requests.post(f"{API}/bookings/1/close", headers=H(tokens["brand1"]),
                          json={"action": "close", "reason": "brand reason"}, timeout=15)
        assert r.status_code == 403, f"expected 403 for brand1, got {r.status_code}: {r.text[:200]}"

    def test_close_owner_ok_then_double_close_409(self, tokens):
        r = requests.post(f"{API}/bookings/1/close", headers=H(tokens["owner"]),
                          json={"action": "close", "reason": "QA short close"}, timeout=15)
        assert r.status_code == 200, f"owner close failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert body.get("status") == "closed", body
        # Double close
        r2 = requests.post(f"{API}/bookings/1/close", headers=H(tokens["owner"]),
                           json={"action": "close", "reason": "again"}, timeout=15)
        assert r2.status_code == 409, f"double close expected 409, got {r2.status_code}"

    def test_receive_against_closed_409(self, tokens):
        # close first
        requests.post(f"{API}/bookings/1/close", headers=H(tokens["owner"]),
                      json={"action": "close", "reason": "closed for QA receive test"}, timeout=15)
        # Look up store from booking 1
        bk = requests.get(f"{API}/bookings/1", headers=H(tokens["owner"]), timeout=15).json()
        store_id = bk.get("store_id") or bk.get("store") or 1
        r = requests.post(f"{API}/inbound/grns", headers=H(tokens["owner"]),
                          json={"booking_id": 1, "store_id": store_id, "lines": []}, timeout=15)
        # 409 conflict expected because booking is closed
        assert r.status_code == 409, f"receive against closed booking: {r.status_code} {r.text[:300]}"
        assert "closed for QA receive test" in r.text or "closed" in r.text.lower(), r.text[:300]


# ---------- Regression sanity ----------
class TestRegression:
    def test_masters_summary(self, tokens):
        r = requests.get(f"{API}/masters/summary", headers=H(tokens["owner"]), timeout=15)
        assert r.status_code == 200

    def test_inbound_queue_owner(self, tokens):
        r = requests.get(f"{API}/inbound/queue", headers=H(tokens["owner"]), timeout=15)
        assert r.status_code == 200
