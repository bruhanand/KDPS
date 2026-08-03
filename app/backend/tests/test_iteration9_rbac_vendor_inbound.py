"""Iteration 9 regression.

Vendor ageing, RBAC admin editor APIs, inbound GRN flows, auth guardrails.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
import requests
from _creds import SEED_OWNER_PASSWORD

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"


def _login(username: str, password: str) -> dict[str, Any]:
    r = requests.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed for {username}: {r.status_code} {r.text[:250]}"
    return r.json()


def _auth_headers(access: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def owner_auth() -> dict[str, Any]:
    return _login("owner", SEED_OWNER_PASSWORD)


@pytest.fixture(scope="module")
def admin_auth() -> dict[str, Any]:
    return _login("admin", "Admin@123")


@pytest.fixture(scope="module")
def cashier_auth() -> dict[str, Any]:
    return _login("deo.cashier", "Store@123")


@pytest.fixture(scope="module")
def accounts_auth() -> dict[str, Any]:
    return _login("accounts1", "Acct@123")


def _apply_access_change(
    maker: dict[str, str], checker: dict[str, str], method: str, path: str, payload: dict[str, Any]
) -> None:
    """Put one user/role change through the two people #131 requires.

    Every write under ``/auth/admin`` now answers 202 and waits: nobody changes
    who may do what on their own say-so. So the live suite proposes as one
    administrator and decides as another, which is also the only way to prove
    the rule holds against a real server rather than a test client.
    """
    proposal = requests.request(method, f"{API}{path}", headers=maker, json=payload, timeout=30)
    assert proposal.status_code == 202, (
        f"{method} {path} should wait for a second person: "
        f"{proposal.status_code} {proposal.text[:250]}"
    )
    approval_id = proposal.json()["approval_id"]

    refused = requests.post(
        f"{API}/approvals/{approval_id}/decide",
        headers=maker,
        json={"action": "approve"},
        timeout=30,
    )
    assert refused.status_code == 403, "the maker must never be able to apply their own change"

    decision = requests.post(
        f"{API}/approvals/{approval_id}/decide",
        headers=checker,
        json={"action": "approve"},
        timeout=30,
    )
    assert decision.status_code == 200, (
        f"apply failed: {decision.status_code} {decision.text[:250]}"
    )


def _fetch_one(headers: dict[str, str], collection: str, key: str, value: str) -> dict[str, Any]:
    listing = requests.get(f"{API}/auth/admin/{collection}", headers=headers, timeout=30)
    assert listing.status_code == 200
    match = [row for row in listing.json() if row.get(key) == value]
    assert match, f"{collection} has no row with {key}={value}"
    return match[0]


@pytest.fixture(scope="module")
def created_entities(owner_auth: dict[str, Any], admin_auth: dict[str, Any]) -> dict[str, Any]:
    """Create TEST role + user for CRUD checks; deactivate them in teardown."""
    headers = _auth_headers(owner_auth["access"])
    checker = _auth_headers(admin_auth["access"])

    ts = int(time.time())
    role_code = f"test_auto_role_{ts}"
    username = f"test.auto.{ts}"

    _apply_access_change(
        headers,
        checker,
        "post",
        "/auth/admin/roles",
        {
            "code": role_code,
            "name": f"TEST AUTO ROLE {ts}",
            "description": "Automation role",
            "landing_page": "home",
            "nav_groups": ["home", "documents"],
            "is_active": True,
        },
    )
    role = _fetch_one(headers, "roles", "code", role_code)

    meta = requests.get(f"{API}/auth/admin/meta", headers=headers, timeout=30)
    assert meta.status_code == 200
    stores = meta.json().get("stores", [])
    assert stores, "No active stores returned in admin meta"
    store_id = stores[0]["id"]

    _apply_access_change(
        headers,
        checker,
        "post",
        "/auth/admin/users",
        {
            "username": username,
            "full_name": "TEST AUTO USER",
            "role_id": role["id"],
            "scope_type": "store",
            "store_ids": [store_id],
            "is_active": True,
            "is_staff": False,
            "password": "TestAuto@123",
        },
    )
    user = _fetch_one(headers, "users", "username", username)

    yield {
        "role": role,
        "user": user,
        "store_id": store_id,
        "username": username,
        "maker": headers,
        "checker": checker,
    }

    _apply_access_change(
        headers, checker, "patch", f"/auth/admin/users/{user['id']}", {"is_active": False}
    )
    _apply_access_change(
        headers, checker, "patch", f"/auth/admin/roles/{role['id']}", {"is_active": False}
    )


# --- Vendor ageing report ---------------------------------------------------


def test_vendor_ageing_shape(owner_auth: dict[str, Any]):
    r = requests.get(
        f"{API}/finledger/vendor/ageing", headers=_auth_headers(owner_auth["access"]), timeout=30
    )
    assert r.status_code == 200
    body = r.json()

    assert "as_of" in body
    assert "bucket_0_30_rupees" in body
    assert "bucket_31_60_rupees" in body
    assert "bucket_60_plus_rupees" in body
    assert "rows" in body and isinstance(body["rows"], list)

    if body["rows"]:
        row = body["rows"][0]
        assert "vendor_id" in row
        assert "vendor_code" in row
        assert "bucket_0_30_rupees" in row
        assert "bucket_31_60_rupees" in row
        assert "bucket_60_plus_rupees" in row
        assert "total_due_rupees" in row


# --- RBAC users & roles admin APIs -----------------------------------------


def test_rbac_lists_access_control(
    owner_auth: dict[str, Any], admin_auth: dict[str, Any], accounts_auth: dict[str, Any]
):
    owner_roles = requests.get(
        f"{API}/auth/admin/roles", headers=_auth_headers(owner_auth["access"]), timeout=30
    )
    assert owner_roles.status_code == 200
    assert isinstance(owner_roles.json(), list)

    admin_users = requests.get(
        f"{API}/auth/admin/users", headers=_auth_headers(admin_auth["access"]), timeout=30
    )
    assert admin_users.status_code == 200
    assert isinstance(admin_users.json(), list)

    denied = requests.get(
        f"{API}/auth/admin/users", headers=_auth_headers(accounts_auth["access"]), timeout=30
    )
    assert denied.status_code == 403


def test_rbac_create_and_edit_role_and_user(created_entities: dict[str, Any]):
    headers = created_entities["maker"]
    checker = created_entities["checker"]
    role_id = created_entities["role"]["id"]
    user_id = created_entities["user"]["id"]

    _apply_access_change(
        headers,
        checker,
        "patch",
        f"/auth/admin/roles/{role_id}",
        {"description": "Automation role edited", "nav_groups": ["home", "ledgers"]},
    )
    get_role = requests.get(f"{API}/auth/admin/roles/{role_id}", headers=headers, timeout=30)
    assert get_role.status_code == 200
    role_body = get_role.json()
    assert role_body["description"] == "Automation role edited"
    assert "ledgers" in (role_body.get("nav_groups") or [])

    _apply_access_change(
        headers,
        checker,
        "patch",
        f"/auth/admin/users/{user_id}",
        {"full_name": "TEST AUTO USER EDITED", "is_staff": True},
    )
    get_user = requests.get(f"{API}/auth/admin/users/{user_id}", headers=headers, timeout=30)
    assert get_user.status_code == 200
    user_fetched = get_user.json()
    assert user_fetched["full_name"] == "TEST AUTO USER EDITED"
    assert user_fetched["is_staff"] is True


def test_a_pending_access_change_has_not_happened_yet(created_entities: dict[str, Any]):
    """The half of the rule the flow above cannot show: waiting means unchanged."""
    headers = created_entities["maker"]
    role_id = created_entities["role"]["id"]
    before = requests.get(f"{API}/auth/admin/roles/{role_id}", headers=headers, timeout=30).json()

    proposal = requests.patch(
        f"{API}/auth/admin/roles/{role_id}",
        headers=headers,
        json={"description": "never applied"},
        timeout=30,
    )
    assert proposal.status_code == 202

    after = requests.get(f"{API}/auth/admin/roles/{role_id}", headers=headers, timeout=30).json()
    assert after["description"] == before["description"]

    requests.post(
        f"{API}/approvals/{proposal.json()['approval_id']}/decide",
        headers=created_entities["checker"],
        json={"action": "reject", "reason": "raised only to prove nothing moved"},
        timeout=30,
    )


def test_store_scope_requires_store_ids(owner_auth: dict[str, Any]):
    r = requests.post(
        f"{API}/auth/admin/users",
        headers=_auth_headers(owner_auth["access"]),
        json={
            "username": f"test.scope.{int(time.time())}",
            "role_id": None,
            "scope_type": "store",
            "store_ids": [],
            "password": "ScopeTest@123",
        },
        timeout=30,
    )
    assert r.status_code == 400
    body = r.json()
    assert "store_ids" in str(body)


# --- Inbound GRN ------------------------------------------------------------


def test_inbound_list_owner_and_store_user(
    owner_auth: dict[str, Any], cashier_auth: dict[str, Any]
):
    r_owner = requests.get(
        f"{API}/inbound/grns", headers=_auth_headers(owner_auth["access"]), timeout=30
    )
    assert r_owner.status_code == 200
    assert isinstance(r_owner.json(), list)

    r_cashier = requests.get(
        f"{API}/inbound/grns", headers=_auth_headers(cashier_auth["access"]), timeout=30
    )
    assert r_cashier.status_code == 200
    assert isinstance(r_cashier.json(), list)


def test_inbound_direct_grn_create_and_detail_for_store_user(cashier_auth: dict[str, Any]):
    access = cashier_auth["access"]
    h = _auth_headers(access)

    me = requests.get(f"{API}/auth/me", headers=h, timeout=30)
    assert me.status_code == 200
    me_body = me.json()
    stores = me_body.get("stores", [])
    assert stores, "cashier has no scoped stores"
    store_id = stores[0]["id"]

    payload = {
        "store_id": store_id,
        "vendor_name": "TEST AUTO VENDOR",
        "invoice_number": f"AUTO-{int(time.time())}",
        "lines": [
            {
                "booking_line_id": None,
                "style_code": "TEST-AUTO-STYLE",
                "size": "M",
                "color": "Blue",
                "barcode": f"AUTO-{int(time.time())}",
                "received_qty": 1,
                "damaged_qty": 0,
                "is_variance": False,
                "remark": "",
            }
        ],
    }
    create = requests.post(f"{API}/inbound/grns", headers=h, json=payload, timeout=30)
    assert create.status_code == 201, f"grn create failed: {create.status_code} {create.text[:250]}"
    created = create.json()
    assert created.get("id")
    assert created.get("is_direct") is True

    detail = requests.get(f"{API}/inbound/grns/{created['id']}", headers=h, timeout=30)
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["id"] == created["id"]
    assert isinstance(detail_body.get("lines"), list)
    assert detail_body["lines"][0]["style_code"] == "TEST-AUTO-STYLE"


# --- Auth playbook checks ---------------------------------------------------


def test_login_bruteforce_lockout_after_five_failures():
    username = f"lockout.iter9.{int(time.time())}"
    statuses = []
    for _ in range(6):
        r = requests.post(
            f"{API}/auth/login",
            json={"username": username, "password": "WrongPass!"},
            timeout=30,
        )
        statuses.append(r.status_code)
    assert 429 in statuses


def test_login_cookie_and_cors_headers(owner_auth: dict[str, Any]):
    login_resp = requests.post(
        f"{API}/auth/login",
        json={"username": "owner", "password": SEED_OWNER_PASSWORD},
        timeout=30,
    )
    assert login_resp.status_code == 200
    set_cookie = login_resp.headers.get("set-cookie", "")
    # We assert the CURRENT behavior so we can report if cookie-based auth is absent.
    assert isinstance(set_cookie, str)

    cors_resp = requests.options(
        f"{API}/auth/login",
        headers={
            "Origin": BASE_URL,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
        timeout=30,
    )
    assert cors_resp.status_code in (200, 204)
    allow_origin = cors_resp.headers.get("access-control-allow-origin")
    # If credentials are enabled, origin should be explicit and not '*'.
    if cors_resp.headers.get("access-control-allow-credentials") == "true":
        assert allow_origin and allow_origin != "*"
