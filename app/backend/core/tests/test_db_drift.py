"""The drift check must name the drifted thing, not just say "something is wrong".

Issue #93: the shared dev Postgres carried an `accounts_role.sections` column that
existed in no migration, and every attempt to create a role 500'd with a bare
`IntegrityError`. `makemigrations --check` stayed green throughout, because it
compares models to migrations and never looks at the database.

Each test here drifts the schema *inside the test transaction* and asserts the
check reports it by table and column. Postgres rolls DDL back with everything
else, so no test leaves the database changed.
"""

from __future__ import annotations

import pytest
from django.db import connection

from core.dbdrift import DriftKind, find_drift

pytestmark = pytest.mark.django_db(transaction=False)


def _kinds(findings: list) -> set[str]:
    return {f.kind for f in findings}


def test_a_freshly_migrated_database_has_no_drift() -> None:
    """The baseline the gate depends on: migrate, and the check is silent."""
    assert find_drift(connection) == []


def test_a_column_no_migration_creates_is_reported_by_table_and_column() -> None:
    """The `accounts_role.sections` case, reproduced."""
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE accounts_role ADD COLUMN sections jsonb NOT NULL DEFAULT '[]'")

    findings = find_drift(connection)

    assert _kinds(findings) == {DriftKind.COLUMN_IN_DATABASE_ONLY}
    (finding,) = findings
    assert finding.table == "accounts_role"
    assert finding.column == "sections"
    assert "accounts_role" in str(finding) and "sections" in str(finding)


def test_a_column_the_migrations_expect_but_the_database_lacks_is_reported() -> None:
    """The opposite direction: a database behind the graph it claims to be at."""
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE accounts_role DROP COLUMN section_access")

    findings = find_drift(connection)

    assert _kinds(findings) == {DriftKind.COLUMN_IN_MIGRATIONS_ONLY}
    (finding,) = findings
    assert finding.table == "accounts_role"
    assert finding.column == "section_access"


def test_a_table_no_migration_creates_is_reported() -> None:
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE accounts_role_sections (id bigint PRIMARY KEY)")

    findings = find_drift(connection)

    assert _kinds(findings) == {DriftKind.TABLE_IN_DATABASE_ONLY}
    assert findings[0].table == "accounts_role_sections"


def test_a_migration_record_with_no_file_is_reported() -> None:
    """A migration the database remembers applying that exists on no branch."""
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO django_migrations (app, name, applied) "
            "VALUES ('accounts', '0099_draft_that_was_deleted', NOW())"
        )

    findings = find_drift(connection)

    assert _kinds(findings) == {DriftKind.ORPHAN_MIGRATION_RECORD}
    assert "accounts.0099_draft_that_was_deleted" in findings[0].message


def test_a_migration_on_disk_that_was_never_applied_is_reported() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM django_migrations WHERE app = 'accounts' AND name = '0001_initial'"
        )

    findings = find_drift(connection)

    assert _kinds(findings) == {DriftKind.UNAPPLIED_MIGRATION}
    assert "accounts.0001_initial" in findings[0].message


def test_a_deliberate_expand_contract_divergence_is_not_drift() -> None:
    """`inbound_grn.status` is left in the database on purpose (inbound/0004).

    If this ever starts failing, the cleanup migration that drops the column has
    landed - delete the allowlist entry rather than working around this test.
    """
    from core.dbdrift import _DELIBERATE_DIVERGENCES

    assert ("inbound_grn", "status") in _DELIBERATE_DIVERGENCES
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'inbound_grn' AND column_name = 'status'"
        )
        assert cursor.fetchone() is not None, (
            "inbound_grn.status is gone from the database - the cleanup migration has "
            "landed, so remove its _DELIBERATE_DIVERGENCES entry"
        )
    assert find_drift(connection) == []
