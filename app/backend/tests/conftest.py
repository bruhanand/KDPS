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

**Remote-target safety (issue #41).** Every live suite *writes* to the target
DB — masters rows, documents, and append-only ledger/GL posts that no API can
delete. During 2 Jul QA these suites were run against the shared Render demo
and left undeletable ``ZZ*`` junk behind (which then broke the exact-count
asserts on the next run). Masters has no DELETE endpoint and ``Season`` has no
``is_active`` field, so teardown can never be complete. The only safe rule is
to confine the writes to disposable deployments: when the target is **not**
localhost and we are **not** in cloud CI, all live items are skipped unless the
operator sets ``KDPS_TEST_ALLOW_REMOTE=1`` to opt in deliberately. Items marked
``local_backend`` are skipped against any non-local target even with that
opt-in — they drive ``manage.py`` subprocesses against *this checkout's* DB or
assert CORS headers a public proxy rewrites, so they are only valid against the
locally-booted uvicorn that shares this checkout's ``DATABASE_URL``.

The DB-backed suites in this package (pytest-django, no ``BASE_URL``) are
unaffected.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

_BACKEND_URL_ENV = "REACT_APP_BACKEND_URL"
_DEFAULT_BASE_URL = "http://localhost:8001"
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

IS_LOCAL_TARGET = (urlsplit(BASE_URL).hostname or "") in ("localhost", "127.0.0.1")


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
    live_items = [
        item for item in items if getattr(getattr(item, "module", None), "BASE_URL", None)
    ]
    if not live_items:
        return

    # Remote-target gate (issue #41): every live suite writes undeletable rows to
    # the target DB, so never touch a shared/remote server without an explicit
    # opt-in. Cloud CI (localhost throwaway) and local runs are naturally exempt.
    if (
        not IS_LOCAL_TARGET
        and not os.environ.get("CI")
        and os.environ.get("KDPS_TEST_ALLOW_REMOTE") != "1"
    ):
        remote_skip = pytest.mark.skip(
            reason=f"live-API suites write to the target DB (masters, documents, "
            f"append-only ledger/GL posts — none deletable via the API) and {BASE_URL} "
            "is not localhost; refusing to mutate a shared/remote deployment. Point "
            "REACT_APP_BACKEND_URL at a disposable instance, or set "
            "KDPS_TEST_ALLOW_REMOTE=1 to override deliberately."
        )
        for item in live_items:
            item.add_marker(remote_skip)
        return

    # local_backend gate: these hit this checkout's DB via manage.py subprocesses or
    # assert CORS headers a public proxy rewrites, so they are meaningless against any
    # non-local target — skipped even under a deliberate KDPS_TEST_ALLOW_REMOTE=1 run.
    if not IS_LOCAL_TARGET:
        local_only_skip = pytest.mark.skip(
            reason=f"local_backend test is only valid against this checkout's own "
            f"locally-booted uvicorn (shared DATABASE_URL, no CORS-rewriting proxy); "
            f"target {BASE_URL} is not localhost"
        )
        for item in live_items:
            if item.get_closest_marker("local_backend"):
                item.add_marker(local_only_skip)

    # Live-probe gate: skip when no seeded server answers. Disabled in cloud CI —
    # a broken server there must fail loudly, never skip.
    if os.environ.get("CI"):
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
