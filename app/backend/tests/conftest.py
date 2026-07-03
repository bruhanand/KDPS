"""Readiness gate for the live-API regression modules in this package.

Nine modules here are black-box suites: they talk to a running, seeded API
server over HTTP at ``REACT_APP_BACKEND_URL`` (each defines a module-level
``BASE_URL``). Cloud CI migrates, seeds, and boots ``uvicorn server:app`` on
port 8001 before running them; a plain local ``npm run ci`` boots nothing, so
without a gate these ~57 tests fail on every developer machine — or worse,
run against whatever unrelated process happens to be squatting on the port.

So: before the session starts we probe the target once with a real demo
login. If a seeded server answers, the suites run exactly as in cloud CI.
Otherwise they are *skipped* with the reason below, keeping the local gate
green and honest. In cloud CI (``CI`` env var set) the gate is disabled — a
broken server there must fail loudly, never skip.

The DB-backed suites in this package (pytest-django, no ``BASE_URL``) are
unaffected.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests

_BACKEND_URL_ENV = "REACT_APP_BACKEND_URL"
_DEFAULT_BASE_URL = "https://ledger-kernel-v2.preview.emergentagent.com"
_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILES = (
    _ROOT / "backend/.env",
    _ROOT / "frontend/.env",
)


def _read_env_file(path: Path) -> str | None:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key == _BACKEND_URL_ENV:
            return value.strip().rstrip("/") or None
    return None


def _resolve_base_url() -> str:
    env_url = os.environ.get(_BACKEND_URL_ENV, "").strip().rstrip("/")
    if env_url:
        return env_url
    for env_file in _ENV_FILES:
        file_url = _read_env_file(env_file)
        if file_url:
            return file_url
    return _DEFAULT_BASE_URL


BASE_URL = _resolve_base_url()
if not os.environ.get(_BACKEND_URL_ENV, "").strip():
    os.environ[_BACKEND_URL_ENV] = BASE_URL


def _live_api_unready_reason() -> str | None:
    """Return None when a seeded API server answers at BASE_URL, else why not."""
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "owner", "password": "Owner@123"},
            timeout=5,
        )
    except requests.RequestException as exc:
        return f"no live API server at {BASE_URL} ({type(exc).__name__})"
    if response.status_code != 200:
        return (
            f"live API server at {BASE_URL} is not seeded/healthy "
            f"(demo login -> {response.status_code})"
        )
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("CI"):
        return
    live_items = [
        item for item in items if getattr(getattr(item, "module", None), "BASE_URL", None)
    ]
    if not live_items:
        return
    reason = _live_api_unready_reason()
    if reason is None:
        return
    marker = pytest.mark.skip(
        reason=f"{reason} — boot one (migrate + seed_foundation + seed_ptmapper + "
        "uvicorn server:app, see .github/workflows/ci.yml) and set "
        "REACT_APP_BACKEND_URL, or rely on cloud CI"
    )
    for item in live_items:
        item.add_marker(marker)
