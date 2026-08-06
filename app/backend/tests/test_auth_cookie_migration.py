"""
Regression tests for cookie-only session migration (frontend-only change).
Backend must continue to support BOTH:
  - JSON body access/refresh tokens returned on login (for curl/API clients)
  - Authorization: Bearer <token> header auth (CookieOrHeaderJWTAuthentication)
Tested against the public HTTPS preview URL (not localhost plain-http, per
agent-to-agent context note - curl cookie-jar quirks over plain HTTP are a
known red herring, unrelated to server behavior).
"""

import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def api_base():
    assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
    return f"{BASE_URL}/api"


class TestLoginJsonBody:
    def test_login_returns_tokens_in_body(self, api_base):
        r = requests.post(
            f"{api_base}/auth/login",
            json={"username": "owner", "password": "Owner@123"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access" in data and isinstance(data["access"], str) and len(data["access"]) > 20
        assert "refresh" in data and isinstance(data["refresh"], str) and len(data["refresh"]) > 20
        assert "user" in data
        assert data["user"]["username"] == "owner"

    def test_login_invalid_credentials(self, api_base):
        r = requests.post(
            f"{api_base}/auth/login",
            json={"username": "owner", "password": "wrongpassword"},
            timeout=30,
        )
        assert r.status_code == 401


class TestHeaderBasedAuthStillWorks:
    """Non-browser clients (curl/Postman) must keep working via Authorization header."""

    def test_bearer_header_auth_on_protected_endpoint(self, api_base):
        login = requests.post(
            f"{api_base}/auth/login",
            json={"username": "accounts1", "password": "Acct@123"},
            timeout=30,
        )
        assert login.status_code == 200, login.text
        access = login.json()["access"]

        # Use header-only auth (no cookies at all in this session).
        r = requests.get(
            f"{api_base}/outbound/partner-dues",
            headers={"Authorization": f"Bearer {access}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text

    def test_bearer_header_auth_on_me_endpoint(self, api_base):
        login = requests.post(
            f"{api_base}/auth/login",
            json={"username": "deo.manager", "password": "Store@123"},
            timeout=30,
        )
        assert login.status_code == 200, login.text
        access = login.json()["access"]

        r = requests.get(
            f"{api_base}/auth/me",
            headers={"Authorization": f"Bearer {access}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["username"] == "deo.manager"

    def test_no_auth_returns_401(self, api_base):
        r = requests.get(f"{api_base}/auth/me", timeout=30)
        assert r.status_code in (401, 403)


class TestCookieAuthViaRequestsSession:
    """Simulate a browser using a requests.Session (cookie jar) over HTTPS."""

    def test_login_sets_cookies_and_cookie_auth_works(self, api_base):
        s = requests.Session()
        r = s.post(
            f"{api_base}/auth/login",
            json={"username": "owner", "password": "Owner@123"},
            timeout=30,
        )
        assert r.status_code == 200
        assert "access_token" in s.cookies
        assert "refresh_token" in s.cookies

        # Now hit a protected endpoint with NO Authorization header - cookie only.
        r2 = s.get(f"{api_base}/auth/me", timeout=30)
        assert r2.status_code == 200, r2.text
        assert r2.json()["username"] == "owner"

    def test_logout_clears_cookies_and_session_ends(self, api_base):
        s = requests.Session()
        s.post(
            f"{api_base}/auth/login",
            json={"username": "owner", "password": "Owner@123"},
            timeout=30,
        )
        logout = s.post(f"{api_base}/auth/logout", json={}, timeout=30)
        assert logout.status_code == 200

        # Post-logout, cookie-based access to /auth/me must fail.
        r = s.get(f"{api_base}/auth/me", timeout=30)
        assert r.status_code == 401
