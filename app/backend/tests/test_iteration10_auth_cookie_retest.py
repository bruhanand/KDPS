"""Iteration 10 auth retest: cookie-compatible JWT, CORS credentials, seed_admin idempotency."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from _creds import SEED_OWNER_PASSWORD

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"

# localhost:3000 matches the DEBUG CORS regex `^http://localhost:\d+$`
# (config/settings.py); CI runs DJANGO_DEBUG=1, so the allowlist + credentials
# mechanism is exercised identically without the retired preview origin.
CORS_TEST_ORIGIN = os.environ.get("KDPS_TEST_CORS_ORIGIN", "http://localhost:3000")


def _json_login(session: requests.Session, username: str, password: str) -> requests.Response:
    return session.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )


def _bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- Auth browser/API compatibility checks ---------------------------------


def test_login_returns_json_tokens_and_sets_http_only_cookies(session: requests.Session):
    r = _json_login(session, "owner", SEED_OWNER_PASSWORD)
    assert r.status_code == 200, r.text[:300]

    body = r.json()
    assert isinstance(body.get("access"), str) and body["access"]
    assert isinstance(body.get("refresh"), str) and body["refresh"]
    assert body.get("user", {}).get("username") == "owner"

    set_cookie = r.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie


def test_auth_me_works_with_cookie_only_without_authorization_header(session: requests.Session):
    login = _json_login(session, "owner", SEED_OWNER_PASSWORD)
    assert login.status_code == 200

    # no Authorization header set; relies on cookie-based auth path
    r = session.get(f"{API}/auth/me", timeout=30)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    assert data["username"] == "owner"
    assert isinstance(data.get("stores"), list)


def test_refresh_from_cookie_sets_access_cookie_and_keeps_json_compatibility(
    session: requests.Session,
):
    login = _json_login(session, "owner", SEED_OWNER_PASSWORD)
    assert login.status_code == 200

    # Cookie-only refresh (no request body token)
    r = session.post(f"{API}/auth/refresh", json={}, timeout=30)
    assert r.status_code == 200, r.text[:300]

    body = r.json()
    assert isinstance(body.get("access"), str) and body["access"]

    set_cookie = r.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie


def test_logout_clears_auth_cookies(session: requests.Session):
    login = _json_login(session, "owner", SEED_OWNER_PASSWORD)
    assert login.status_code == 200

    r = session.post(f"{API}/auth/logout", json={}, timeout=30)
    assert r.status_code == 200, r.text[:300]

    set_cookie = r.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
    assert ("Max-Age=0" in set_cookie) or ("expires=" in set_cookie.lower())


def test_bruteforce_lockout_after_five_failures_still_active():
    username = f"lockout.iter10.{int(time.time())}"
    statuses: list[int] = []
    for _ in range(6):
        r = requests.post(
            f"{API}/auth/login",
            json={"username": username, "password": "WrongPass!"},
            timeout=30,
        )
        statuses.append(r.status_code)
    assert 429 in statuses


# --- CORS check (internal Django app endpoint) ------------------------------


@pytest.mark.local_backend
def test_internal_django_cors_allows_explicit_origin_and_credentials():
    origin = CORS_TEST_ORIGIN
    r = requests.options(
        f"{API}/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
        timeout=30,
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-credentials") == "true"
    assert r.headers.get("access-control-allow-origin") == origin


# --- Password hasher + seed_admin idempotency -------------------------------


@pytest.mark.local_backend
def test_seed_admin_is_idempotent_and_does_not_overwrite_password():
    backend_dir = Path(__file__).resolve().parents[1]

    def shell(code: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "manage.py", "shell", "-c", code],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    # seed_admin exists and runs (idempotent)
    run1 = subprocess.run(
        [sys.executable, "manage.py", "seed_admin"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert run1.returncode == 0, run1.stderr[-500:]

    temp = "OpsRotated#789"
    try:
        # Rotate owner's password (operator action); the bcrypt_sha256 hasher is used.
        mutate = shell(
            "from django.contrib.auth import get_user_model; "
            "u=get_user_model().objects.get(username='owner'); "
            f"u.set_password('{temp}'); u.save(); print(u.password.split('$')[0])"
        )
        assert mutate.returncode == 0, mutate.stderr[-500:]
        assert mutate.stdout.strip().splitlines()[-1].strip() == "bcrypt_sha256"

        # Re-seed must NOT clobber the rotated password (security fix).
        run2 = subprocess.run(
            [sys.executable, "manage.py", "seed_admin"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert run2.returncode == 0, run2.stderr[-500:]

        verify = shell(
            "from django.contrib.auth import get_user_model; "
            "from django.contrib.auth.hashers import check_password; "
            "u=get_user_model().objects.get(username='owner'); "
            f"print(u.password); print(check_password('{temp}', u.password))"
        )
        assert verify.returncode == 0, verify.stderr[-500:]
        out = verify.stdout.strip().splitlines()
        assert len(out) >= 2
        assert out[0].strip().startswith("bcrypt_sha256$")
        # The operator-set password SURVIVES the re-seed (no auto-revert).
        assert out[-1].strip().lower() == "true"
    finally:
        shell(
            "from django.contrib.auth import get_user_model; "
            "u=get_user_model().objects.get(username='owner'); "
            "u.set_password('Owner@123'); u.save(); print('restored')"
        )


# --- Regression sanity for requested feature routes -------------------------


def test_regression_vendor_users_inbound_routes_still_load_via_api(session: requests.Session):
    login = _json_login(session, "owner", SEED_OWNER_PASSWORD)
    assert login.status_code == 200
    access = login.json()["access"]
    headers = _bearer_headers(access)

    vendor_ageing = session.get(f"{API}/finledger/vendor/ageing", headers=headers, timeout=30)
    assert vendor_ageing.status_code == 200
    v = vendor_ageing.json()
    assert "rows" in v and isinstance(v["rows"], list)

    users = session.get(f"{API}/auth/admin/users", headers=headers, timeout=30)
    assert users.status_code == 200
    assert isinstance(users.json(), list)

    inbound = session.get(f"{API}/inbound/grns", headers=headers, timeout=30)
    assert inbound.status_code == 200
    assert isinstance(inbound.json(), list)
