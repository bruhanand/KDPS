"""EOSS Planning API tests: recommendations list/generate/decide + ladder/targets config."""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or pytest.skip(
    "REACT_APP_BACKEND_URL not set", allow_module_level=True
)


@pytest.fixture(scope="module")
def owner_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "owner", "password": "Owner@123"})
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    tok = r.json().get("token") or r.json().get("access") or r.json().get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


class TestEossRecommendations:
    def test_list_recommendations_aw25(self, owner_session):
        r = owner_session.get(f"{BASE_URL}/api/offers/eoss/recommendations", params={"season": "AW25"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        required = {
            "brand_name", "design", "color", "weeks_in_stock", "on_hand_qty",
            "sold_qty", "sell_through_pct", "target_pct", "gap_pct",
            "broken_size_run", "margin_floor_pct", "recommended_discount_pct",
            "reason", "status", "decided_discount_pct", "offer",
        }
        missing = required - set(data[0].keys())
        assert not missing, f"missing fields: {missing}. got={list(data[0].keys())}"

    def test_generate_returns_generated_count_and_rows(self, owner_session):
        r = owner_session.post(f"{BASE_URL}/api/offers/eoss/recommendations", json={"season": "AW25"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "generated" in d and "recommendations" in d
        assert isinstance(d["recommendations"], list)

    def test_generate_missing_season(self, owner_session):
        r = owner_session.post(f"{BASE_URL}/api/offers/eoss/recommendations", json={})
        assert r.status_code == 400

    def test_generate_unknown_season(self, owner_session):
        r = owner_session.post(f"{BASE_URL}/api/offers/eoss/recommendations", json={"season": "ZZ99"})
        assert r.status_code == 404

    def test_regenerate_preserves_decided_rows(self, owner_session):
        # capture current approved+rejected rows
        r = owner_session.get(f"{BASE_URL}/api/offers/eoss/recommendations", params={"season": "AW25"})
        assert r.status_code == 200
        before = {row["id"]: row["status"] for row in r.json() if row["status"] in ("approved", "rejected")}
        # regenerate
        r = owner_session.post(f"{BASE_URL}/api/offers/eoss/recommendations", json={"season": "AW25"})
        assert r.status_code == 200
        r = owner_session.get(f"{BASE_URL}/api/offers/eoss/recommendations", params={"season": "AW25"})
        after = {row["id"]: row["status"] for row in r.json()}
        for rid, st in before.items():
            assert after.get(rid) == st, f"row {rid} changed {st}->{after.get(rid)}"

    def test_decide_already_decided_returns_400(self, owner_session):
        r = owner_session.get(f"{BASE_URL}/api/offers/eoss/recommendations", params={"season": "AW25"})
        decided = [row for row in r.json() if row["status"] in ("approved", "rejected")]
        if not decided:
            pytest.skip("no decided rows to test double-decide")
        rid = decided[0]["id"]
        r = owner_session.post(
            f"{BASE_URL}/api/offers/eoss/recommendations/{rid}/decide", json={"action": "approve"}
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_decide_invalid_action(self, owner_session):
        r = owner_session.get(f"{BASE_URL}/api/offers/eoss/recommendations", params={"season": "AW25"})
        pending = [row for row in r.json() if row["status"] == "pending"]
        if not pending:
            pytest.skip("no pending rows")
        rid = pending[0]["id"]
        r = owner_session.post(
            f"{BASE_URL}/api/offers/eoss/recommendations/{rid}/decide", json={"action": "maybe"}
        )
        assert r.status_code == 400

    def test_decide_nonexistent(self, owner_session):
        r = owner_session.post(
            f"{BASE_URL}/api/offers/eoss/recommendations/9999999/decide", json={"action": "approve"}
        )
        assert r.status_code == 404


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "Admin@123"})
    assert r.status_code == 200, f"admin login failed: {r.text}"
    tok = r.json().get("token") or r.json().get("access") or r.json().get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


class TestEossConfig:
    def test_get_default_config(self, owner_session):
        r = owner_session.get(f"{BASE_URL}/api/offers/eoss/config")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "ladder" in d and "targets" in d
        # seeded defaults
        assert len(d["ladder"]) == 3, f"expected 3 ladder steps, got {len(d['ladder'])}"
        assert len(d["targets"]) == 8, f"expected 8 target rows, got {len(d['targets'])}"

    def test_get_config_by_brand(self, owner_session):
        r = owner_session.get(f"{BASE_URL}/api/offers/eoss/config", params={"brand": "allen-solly"})
        assert r.status_code == 200
        d = r.json()
        assert "ladder" in d and "targets" in d

    def test_put_default_config_roundtrip(self, admin_session):
        original = admin_session.get(f"{BASE_URL}/api/offers/eoss/config").json()
        payload = {
            "ladder": [
                {"step_no": 1, "trigger_type": "gap", "trigger_value": "10", "discount_pct": "15"},
                {"step_no": 2, "trigger_type": "gap", "trigger_value": "25", "discount_pct": "30"},
                {"step_no": 3, "trigger_type": "gap", "trigger_value": "40", "discount_pct": "50"},
            ],
            "targets": [
                {"week_number": w, "target_pct": p}
                for w, p in [(2, 10), (4, 20), (6, 35), (8, 50), (10, 65), (12, 80), (16, 90), (20, 95)]
            ],
        }
        r = admin_session.put(f"{BASE_URL}/api/offers/eoss/config", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["ladder"]) == 3
        assert len(d["targets"]) == 8
        _ = original

    def test_put_config_bad_payload(self, admin_session):
        r = admin_session.put(f"{BASE_URL}/api/offers/eoss/config", json={"ladder": "nope"})
        assert r.status_code == 400

    def test_owner_cannot_manage_config(self, owner_session):
        # documents permission gap: owner has approve, not manage
        r = owner_session.put(
            f"{BASE_URL}/api/offers/eoss/config",
            json={"ladder": [], "targets": []},
        )
        assert r.status_code == 403
