"""Iteration 13 regression: CORS/CSRF env-driven config change.

Goal: verify the deploy-readiness config change (env-driven CORS_ALLOWED_ORIGINS
and CSRF_TRUSTED_ORIGINS) did NOT break auth or core authenticated reads, and
that an allowed origin still passes CORS preflight via the regex allow-list. The
CORS tests are marked ``local_backend``: they hit the Django layer directly via
``{API}`` because a public ingress overwrites CORS headers (`*`) at the proxy,
so they are only meaningful against this checkout's locally-booted uvicorn.
"""

from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"

# localhost:3000 matches the DEBUG CORS regex `^http://localhost:\d+$`
# (config/settings.py); CI runs DJANGO_DEBUG=1, so the allowlist + credentials
# mechanism is exercised identically without the retired preview origin.
CORS_TEST_ORIGIN = os.environ.get("KDPS_TEST_CORS_ORIGIN", "http://localhost:3000")


# --- shared helpers ---------------------------------------------------------


@pytest.fixture
def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(session: requests.Session, username: str, password: str) -> requests.Response:
    return session.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )


# --- Auth: seeded users still authenticate after settings change -----------


@pytest.mark.parametrize(
    "username,password",
    [
        ("owner", "Owner@123"),
        ("deo.cashier", "Store@123"),
        ("wh.patna", "Wh@123"),
    ],
)
def test_seeded_users_login_returns_access_and_refresh(username, password):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = _login(s, username, password)
    assert r.status_code == 200, f"{username}: {r.status_code} {r.text[:300]}"
    body = r.json()
    assert isinstance(body.get("access"), str) and body["access"], "missing access"
    assert isinstance(body.get("refresh"), str) and body["refresh"], "missing refresh"
    user = body.get("user") or {}
    assert user.get("username") == username


# --- Core authenticated GETs still respond for owner -----------------------


@pytest.fixture
def owner_auth_headers(session: requests.Session) -> dict:
    r = _login(session, "owner", "Owner@123")
    assert r.status_code == 200, r.text[:300]
    return {"Authorization": f"Bearer {r.json()['access']}"}


def test_owner_vendor_ageing_returns_json(session: requests.Session, owner_auth_headers):
    r = session.get(f"{API}/finledger/vendor/ageing", headers=owner_auth_headers, timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert "rows" in body and isinstance(body["rows"], list)


def test_owner_inbound_grns_returns_json(session: requests.Session, owner_auth_headers):
    # NB: inbound/urls.py registers `grns` without a trailing slash; the trailing
    # slash variant 404s. Mirroring the actual route here.
    r = session.get(f"{API}/inbound/grns", headers=owner_auth_headers, timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    # Either DRF paginated dict or plain list — both are acceptable.
    assert isinstance(body, (dict, list))
    if isinstance(body, dict):
        assert "results" in body or "rows" in body or "count" in body


def test_owner_stockledger_entries_returns_json(session: requests.Session, owner_auth_headers):
    r = session.get(f"{API}/stockledger/entries", headers=owner_auth_headers, timeout=30)
    assert r.status_code == 200, r.text[:300]
    # Body must be parseable JSON.
    r.json()


# --- CORS preflight: preview origin must be echoed back --------------------


@pytest.mark.local_backend
def test_cors_preflight_echoes_allowed_origin_with_credentials():
    """Django CORS layer must echo an allowed origin and allow credentials.

    Hitting the Django layer directly (rather than a public proxy that rewrites
    CORS headers to `*`) is guaranteed by the `local_backend` marker. The
    settings.py change only controls the Django-emitted headers.
    """
    r = requests.options(
        f"{API}/auth/login",
        headers={
            "Origin": CORS_TEST_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
        timeout=30,
    )
    assert r.status_code in (200, 204), r.text[:300]
    assert r.headers.get("access-control-allow-origin") == CORS_TEST_ORIGIN, dict(r.headers)
    assert r.headers.get("access-control-allow-credentials") == "true", dict(r.headers)


@pytest.mark.local_backend
def test_cors_actual_post_includes_allow_origin_header():
    """Login POST from an allowed origin should also carry the echoed CORS header
    at the Django layer."""
    r = requests.post(
        f"{API}/auth/login",
        json={"username": "owner", "password": "Owner@123"},
        headers={"Origin": CORS_TEST_ORIGIN, "Content-Type": "application/json"},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:300]
    assert r.headers.get("access-control-allow-origin") == CORS_TEST_ORIGIN
    assert r.headers.get("access-control-allow-credentials") == "true"
