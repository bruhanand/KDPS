"""Pytest configuration for the backend test suite.

The append-only ledger / document tables carry a ``BEFORE TRUNCATE`` guard
(``core.ledger.truncate_guard_sql``) that binds even the superuser. Django's
``TransactionTestCase`` teardown flushes via ``TRUNCATE``, which that guard would
block — so for the *test* connection only we set the session GUC
``kdps.allow_truncate = 'on'``, the escape hatch the trigger honours.

Production never imports conftest and runs as a non-superuser role, so the guard
(plus ``REVOKE TRUNCATE``) is fully active there.
"""

from __future__ import annotations

from typing import Any

from django.db.backends.signals import connection_created


def _allow_test_truncate(sender: Any, connection: Any, **kwargs: Any) -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SET kdps.allow_truncate = 'on'")


connection_created.connect(_allow_test_truncate)
