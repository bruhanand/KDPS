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

**A server that answers is not a server that is current (issue #93).** For weeks
a container on :8001 served pre-#85 code against a database this repo had since
migrated. It passed the login probe above with no trouble: it was running, it was
seeded, it just was not the code anybody was editing. Tests then failed on
assertions nobody could explain, and the failures were waved through each run as
"environmental". So the probe now also asks the server *which code it is* -
``/api/health`` reports the set of migration files its process carries - and
compares that against this checkout. Disagreement **skips, with the mismatched
migrations named**; it never silently passes, and it never fails locally, because
a stale server is an environment problem and not a defect in the tree. Cloud CI
boots the server from the very checkout under test, so there a disagreement is a
real fault and fails the run outright.

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
from importlib import import_module
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests
from _creds import SEED_OWNER_PASSWORD
from _live_gate import mismatch_reason
from django.apps import apps as django_apps

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


@pytest.fixture(autouse=True)
def _restore_migration_seeded_policy_rows(
    request: pytest.FixtureRequest,
    django_db_setup,
    django_db_blocker,
):
    """Transaction tests flush rows; restore policy data each migrated DB starts with."""
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    with django_db_blocker.unblock():
        import_module("accounts.migrations.0009_actor_policy").seed_actor_policies(
            django_apps, None
        )
        import_module("accounts.migrations.0012_return_to_brand_actor_policy").seed(
            django_apps, None
        )
        import_module("approvals.migrations.0004_seed_approval_policies").seed_policies(
            django_apps, None
        )
        import_module("approvals.migrations.0005_seed_stock_request_policy").seed_policy(
            django_apps, None
        )
        import_module("alerts.migrations.0002_seed_alert_policies").seed_policies(django_apps, None)
    yield


def _live_api_unready_reason() -> str | None:
    """Return None when a seeded API server answers at BASE_URL, else why not."""
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "owner", "password": SEED_OWNER_PASSWORD},
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


def _version_mismatch_reason() -> str | None:
    """Return None when the target runs this checkout's code, else what differs.

    Deliberately silent on network trouble: an unreachable or unparseable server
    is the readiness probe's business, not this one's. This speaks only when it
    has a real answer from the server and that answer disagrees.
    """
    # Imported here, not at module scope: conftest is loaded before pytest-django
    # calls django.setup(), and reading the migration graph needs a populated app
    # registry.
    from core.identity import migration_digest, migration_names

    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=5)
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    if response.status_code != 200 or not isinstance(payload, dict):
        return None

    return mismatch_reason(
        payload.get("migrations"),
        target=BASE_URL,
        our_names=migration_names(),
        our_digest=migration_digest(),
    )


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

    # Live-probe gate: skip when no seeded server answers, or when the one that
    # answers is not running this checkout's code. Cloud CI boots the server from
    # the checkout under test, so there a version mismatch is a genuine fault and
    # must stop the run rather than quietly shrink it.
    if os.environ.get("CI"):
        mismatch = _version_mismatch_reason()
        if mismatch:
            raise pytest.UsageError(f"live-API target is not the code under test: {mismatch}")
        return
    reason = _live_api_unready_reason()
    if reason is not None:
        reason = (
            f"{reason} - boot one (migrate + seed_foundation + seed_ptmapper + "
            "seed_outbound_demo + uvicorn server:app, or just `npm run dev`) and set "
            "REACT_APP_BACKEND_URL, or rely on cloud CI"
        )
    else:
        reason = _version_mismatch_reason()
    if reason is None:
        return
    marker = pytest.mark.skip(reason=reason)
    for item in live_items:
        item.add_marker(marker)
