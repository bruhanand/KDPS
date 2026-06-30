"""KDPS Foundation backend tests — auth, scope isolation, masters."""
import os
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend .env (CI env may not propagate)
    try:
        with open(Path(__file__).resolve().parents[3] / "app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def s():
    return requests.Session()


# ---------- Health ----------
def test_health(s):
    r = s.get(f"{API}/health", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"


# ---------- Login ----------
def _login(s, username, password):
    return s.post(f"{API}/auth/login", json={"username": username, "password": password}, timeout=15)


def test_login_owner_returns_tokens_and_profile(s):
    r = _login(s, "owner", "Owner@123")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access" in data and "refresh" in data
    assert "user" in data
    user = data["user"]
    assert "role" in user
    role = user["role"]
    assert "code" in role
    assert "nav_groups" in role
    assert "landing_page" in role
    assert "scope_type" in user
    assert "stores" in user and isinstance(user["stores"], list)


def test_login_invalid_credentials(s):
    r = _login(s, "owner", "WrongPass!")
    assert r.status_code in (400, 401)


# ---------- /me & refresh ----------
def test_me_with_token(s):
    r = _login(s, "owner", "Owner@123")
    access = r.json()["access"]
    me = s.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {access}"}, timeout=15)
    assert me.status_code == 200
    body = me.json()
    assert body.get("role", {}).get("code")
    assert "stores" in body


def test_me_without_token_returns_401(s):
    # A request with neither a Bearer header nor a valid auth cookie must be 401.
    # Use a fresh session so a cookie left in the shared jar by a prior login test
    # cannot authenticate this call (cookie-or-header JWT auth).
    fresh = requests.Session()
    me = fresh.get(f"{API}/auth/me", timeout=15)
    assert me.status_code == 401


def test_refresh_returns_new_access(s):
    r = _login(s, "owner", "Owner@123")
    refresh = r.json()["refresh"]
    rr = s.post(f"{API}/auth/refresh", json={"refresh": refresh}, timeout=15)
    assert rr.status_code == 200
    assert "access" in rr.json()


# ---------- Brute force lockout ----------
def test_brute_force_lockout_429():
    # Use a fresh username to avoid collateral (ops1) — but lockout key is per-username.
    # Use a temporary unique-ish unused identity: 'lockout_test_user' — invalid creds still count.
    target = "lockout_test_user"
    sess = requests.Session()
    statuses = []
    for _ in range(6):
        r = sess.post(f"{API}/auth/login", json={"username": target, "password": "WrongPass!"}, timeout=15)
        statuses.append(r.status_code)
    # After 5 failures, the 6th should be 429
    assert 429 in statuses, f"Expected 429 in {statuses}"


# ---------- Scope isolation ----------
def test_scope_isolation_stores_and_summary(s):
    # owner sees all 6 stores
    r = _login(s, "owner", "Owner@123")
    owner_token = r.json()["access"]
    o_stores = s.get(f"{API}/masters/stores", headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)
    assert o_stores.status_code == 200
    o_data = o_stores.json()
    # Could be list or paginated dict
    o_list = o_data if isinstance(o_data, list) else o_data.get("results", o_data.get("items", []))
    assert len(o_list) == 6, f"owner should see 6 stores, saw {len(o_list)}"

    o_summary = s.get(f"{API}/masters/summary", headers={"Authorization": f"Bearer {owner_token}"}, timeout=15)
    assert o_summary.status_code == 200
    osd = o_summary.json()
    assert osd.get("stores") == 6
    assert osd.get("warehouses") == 1

    # deo.cashier - store scoped
    r2 = _login(s, "deo.cashier", "Store@123")
    assert r2.status_code == 200, r2.text
    deo_token = r2.json()["access"]
    d_stores = s.get(f"{API}/masters/stores", headers={"Authorization": f"Bearer {deo_token}"}, timeout=15)
    assert d_stores.status_code == 200
    d_data = d_stores.json()
    d_list = d_data if isinstance(d_data, list) else d_data.get("results", d_data.get("items", []))
    assert len(d_list) == 1, f"deo.cashier should see 1 store, saw {len(d_list)}"
    assert "DEO" in (d_list[0].get("code", "") + d_list[0].get("name", ""))

    d_summary = s.get(f"{API}/masters/summary", headers={"Authorization": f"Bearer {deo_token}"}, timeout=15)
    assert d_summary.status_code == 200
    dsd = d_summary.json()
    assert dsd.get("stores") == 1
    assert dsd.get("warehouses") == 0


# ---------- Master seeded data ----------
def test_masters_seeded(s):
    r = _login(s, "owner", "Owner@123")
    token = r.json()["access"]
    h = {"Authorization": f"Bearer {token}"}

    def get_list(path):
        rr = s.get(f"{API}{path}", headers=h, timeout=15)
        assert rr.status_code == 200, f"{path} -> {rr.status_code}: {rr.text[:200]}"
        body = rr.json()
        return body if isinstance(body, list) else body.get("results", body.get("items", []))

    brands = get_list("/masters/brands")
    assert len(brands) == 10, f"expected 10 brands, got {len(brands)}"
    assert any("commercial_label" in b for b in brands)

    seasons = get_list("/masters/seasons")
    assert len(seasons) == 3

    gstins = get_list("/masters/gstins")
    assert len(gstins) == 2

    entities = get_list("/masters/entities")
    assert len(entities) == 1
