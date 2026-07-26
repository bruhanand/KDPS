"""`/api/health` must say *which code* is answering, not just that something is.

Issue #93: a stale server answers a liveness probe exactly as well as a current
one, so liveness alone let a container serving pre-#85 code stand in for the
working tree for weeks.
"""

from __future__ import annotations

from django.test import Client, override_settings

from core.identity import migration_digest, migration_identity, migration_names


def test_identity_is_the_migration_files_this_code_carries() -> None:
    names = migration_names()

    assert names, "no migrations found - the loader is looking in the wrong place"
    assert names == tuple(sorted(names)), "order must be stable, or digests differ per process"
    assert "core.0001_initial" in names


def test_the_digest_moves_when_the_migration_set_moves() -> None:
    """A digest that ignores a change is worse than no digest at all."""
    import hashlib

    baseline = migration_digest()
    with_one_more = hashlib.sha256(
        "\n".join([*migration_names(), "accounts.0099_hypothetical"]).encode()
    ).hexdigest()[:12]

    assert baseline != with_one_more


def test_names_are_withheld_unless_the_caller_is_a_developer_or_ci() -> None:
    """Count and digest are enough to detect a mismatch; the names are not public."""
    public = migration_identity(include_names=False)
    private = migration_identity(include_names=True)

    assert set(public) == {"count", "digest"}
    assert private["names"] == list(migration_names())
    assert private["count"] == public["count"] == len(migration_names())


@override_settings(ALLOWED_HOSTS=["*"])
def test_health_publishes_the_identity_without_touching_the_database() -> None:
    """No `django_db` marker here on purpose - health must answer with Postgres down."""
    response = Client().get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["migrations"]["digest"] == migration_digest()
    assert body["migrations"]["count"] == len(migration_names())
