"""K0 foundation smoke tests.

These prove the skeleton is wired and — critically — that the test run is hitting
real PostgreSQL, not SQLite. Every later kernel invariant (append-only,
cross-store isolation, balanced posting) depends on this being true.
"""

from __future__ import annotations

import pytest
from django.db import connection


def test_arithmetic_smoke() -> None:
    assert 1 + 1 == 2


@pytest.mark.django_db
def test_database_is_postgresql() -> None:
    assert connection.vendor == "postgresql"
