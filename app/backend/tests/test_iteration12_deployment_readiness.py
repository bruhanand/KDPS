"""Iteration 12 deployment-readiness regression: auth, health, and core API smoke checks."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"


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


# --- Core backend availability for app usage --------------------------------


def test_health_endpoint_ok_shape():
    r = requests.get(f"{API}/health", timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("status") == "ok"
    assert body.get("service") == "kdps-backend"


def test_login_owner_success_and_cookie_present(session: requests.Session):
    r = _login(session, "owner", "Owner@123")
    assert r.status_code == 200, r.text[:300]

    data = r.json()
    assert data.get("user", {}).get("username") == "owner"
    assert isinstance(data.get("access"), str) and data["access"]
    assert isinstance(data.get("refresh"), str) and data["refresh"]

    set_cookie = r.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    assert "HttpOnly" in set_cookie


def test_cookie_only_auth_me_works_after_login(session: requests.Session):
    login = _login(session, "owner", "Owner@123")
    assert login.status_code == 200, login.text[:300]

    me = session.get(f"{API}/auth/me", timeout=30)
    assert me.status_code == 200, me.text[:300]
    user = me.json()
    assert user.get("username") == "owner"
    assert isinstance(user.get("nav_groups"), list)


def test_core_authenticated_dashboard_feed_loads(session: requests.Session):
    login = _login(session, "owner", "Owner@123")
    assert login.status_code == 200, login.text[:300]
    access = login.json()["access"]
    headers = {"Authorization": f"Bearer {access}"}

    res = session.get(f"{API}/finledger/vendor/ageing", headers=headers, timeout=30)
    assert res.status_code == 200, res.text[:300]
    payload = res.json()
    assert "rows" in payload
    assert isinstance(payload["rows"], list)


# --- Optional auth playbook checks requested in handoff ---------------------


def test_bruteforce_lockout_after_five_failed_logins():
    username = f"iter12.lockout.{int(time.time())}"
    statuses: list[int] = []
    for _ in range(6):
        r = requests.post(
            f"{API}/auth/login",
            json={"username": username, "password": "WrongPass!"},
            timeout=30,
        )
        statuses.append(r.status_code)
    assert 429 in statuses


def test_password_hash_contains_bcrypt_2b_prefix_for_owner_record():
    backend_dir = Path(__file__).resolve().parents[1]
    cmd = (
        "from django.contrib.auth import get_user_model; "
        "u=get_user_model().objects.get(username='owner'); "
        "print(u.password)"
    )
    r = subprocess.run(
        [sys.executable, "manage.py", "shell", "-c", cmd],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert r.returncode == 0, r.stderr[-500:]
    stored = r.stdout.strip()
    assert stored
    assert "$2b$" in stored


def test_seed_admin_updates_existing_admin_password_if_changed():
    backend_dir = Path(__file__).resolve().parents[1]

    mutate = (
        "from django.contrib.auth import get_user_model; "
        "u=get_user_model().objects.get(username='owner'); "
        "u.set_password('TempOwner@123'); u.save(); print('ok')"
    )
    m = subprocess.run(
        [sys.executable, "manage.py", "shell", "-c", mutate],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert m.returncode == 0, m.stderr[-500:]

    seed = subprocess.run(
        [sys.executable, "manage.py", "seed_admin"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert seed.returncode == 0, seed.stderr[-500:]

    verify = (
        "from django.contrib.auth import get_user_model; "
        "from django.contrib.auth.hashers import check_password; "
        "u=get_user_model().objects.get(username='owner'); "
        "print(check_password('Owner@123', u.password))"
    )
    v = subprocess.run(
        [sys.executable, "manage.py", "shell", "-c", verify],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert v.returncode == 0, v.stderr[-500:]
    assert v.stdout.strip().lower() == "true"


def test_cors_preflight_allows_credentials_and_explicit_origin():
    origin = BASE_URL
    r = requests.options(
        "http://localhost:8001/api/auth/login",
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
