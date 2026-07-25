"""Does the database actually look the way the migrations say it should?

`makemigrations --check` answers a different question - *models vs migrations* -
and it answered "clean" for weeks while the shared dev Postgres carried a
`sections` column on `accounts_role` that existed in no migration on any branch.
Nothing compared the third corner of the triangle, so the drift only surfaced as
an `IntegrityError` the first time somebody tried to create a role (issue #93).

This module compares *migrations vs database* and names what it finds:

* a column in the database that no migration creates  → the `sections` case
* a column the migrations create that the database lacks
* a table on either side of that same mismatch
* a `django_migrations` row whose migration file exists nowhere
* migrations on disk that were never applied

The expected shape is rendered from the migration **graph**, not from the models,
on purpose: models are what a developer *intends*, migrations are what has been
promised to every other checkout, and the database is what is true. Drift lives
between the last two.

Read-only: nothing here writes to the database or to disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper

# `django_migrations` is written by the migration recorder itself, not by any
# model, so it is legitimately absent from the rendered migration state.
_TABLES_WITHOUT_A_MODEL = frozenset({"django_migrations"})

# Divergences that are a decision, not an accident. Expand/contract migrations
# deliberately leave a column in the database after removing it from model state,
# so the check would otherwise fail on the very technique that makes zero-downtime
# deploys safe. Every entry states why it exists and what retires it - an entry
# with no exit is drift wearing a permission slip.
_DELIBERATE_DIVERGENCES: dict[tuple[str, str], str] = {
    ("inbound_grn", "status"): (
        "expand/contract, inbound/0004_remove_grn_status: dropped from model state but "
        "left nullable in the database so the previous release could keep writing it "
        "across a Render cutover. Retire this entry when a cleanup migration drops the "
        "column outright."
    ),
}


class DriftKind(StrEnum):
    """The shapes drift comes in. Callers match on these, never on prose."""

    COLUMN_IN_DATABASE_ONLY = "column-in-database-only"
    COLUMN_IN_MIGRATIONS_ONLY = "column-in-migrations-only"
    TABLE_IN_DATABASE_ONLY = "table-in-database-only"
    TABLE_IN_MIGRATIONS_ONLY = "table-in-migrations-only"
    ORPHAN_MIGRATION_RECORD = "orphan-migration-record"
    UNAPPLIED_MIGRATION = "unapplied-migration"
    UNMIGRATED_DATABASE = "unmigrated-database"


@dataclass(frozen=True)
class DriftFinding:
    """One concrete disagreement between the migration graph and the database."""

    kind: DriftKind
    table: str
    column: str
    message: str

    def __str__(self) -> str:
        where = f"{self.table}.{self.column}" if self.column else self.table
        return f"[{self.kind}] {where}: {self.message}"


def _expected_tables(loader: MigrationLoader) -> dict[str, set[str]]:
    """Table → column names, as the migration graph on disk defines them."""
    state = loader.project_state()
    expected: dict[str, set[str]] = {}
    # include_auto_created picks up the join tables behind ManyToManyFields, which
    # are real tables in the database but never appear as declared models.
    for model in state.apps.get_models(include_auto_created=True):
        meta = model._meta
        # `column` is Optional only for the non-concrete fields that never appear
        # in `local_fields`; the guard is for the type checker, not for reality.
        expected[meta.db_table] = {f.column for f in meta.local_fields if f.column is not None}
    return expected


def _actual_tables(connection: BaseDatabaseWrapper) -> dict[str, set[str]]:
    """Table → column names, as the database actually has them right now."""
    actual: dict[str, set[str]] = {}
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names(cursor):
            actual[table] = {
                column.name
                for column in connection.introspection.get_table_description(cursor, table)
            }
    return actual


def _migration_record_findings(
    connection: BaseDatabaseWrapper, loader: MigrationLoader
) -> list[DriftFinding]:
    """`django_migrations` rows with no file, and files never applied."""
    on_disk = set(loader.disk_migrations)
    # A squash replaces its predecessors: their files are deleted but their rows
    # stay behind legitimately, so count anything a squash claims as "on disk".
    for migration in loader.disk_migrations.values():
        on_disk.update(migration.replaces)

    recorder = MigrationRecorder(connection)
    if not recorder.has_table():
        return [
            DriftFinding(
                kind=DriftKind.UNMIGRATED_DATABASE,
                table="django_migrations",
                column="",
                message=(
                    "the migration history table does not exist - this database has "
                    "never been migrated. Run: npm run dev:setup"
                ),
            )
        ]
    applied = set(recorder.applied_migrations())

    findings = [
        DriftFinding(
            kind=DriftKind.ORPHAN_MIGRATION_RECORD,
            table="django_migrations",
            column="",
            message=(
                f"'{app_label}.{name}' is recorded as applied, but that migration file "
                "exists in this checkout on no branch. The database was migrated by a "
                "checkout that has since dropped it. Rebuild: npm run dev:reset"
            ),
        )
        for app_label, name in sorted(applied - on_disk)
    ]
    findings += [
        DriftFinding(
            kind=DriftKind.UNAPPLIED_MIGRATION,
            table="django_migrations",
            column="",
            message=(
                f"'{app_label}.{name}' exists in this checkout but was never applied "
                "to this database. Run: npm run dev:setup"
            ),
        )
        for app_label, name in sorted(on_disk - applied)
    ]
    return findings


def find_drift(connection: BaseDatabaseWrapper) -> list[DriftFinding]:
    """Every way this database disagrees with the migration graph, most specific first.

    An empty list means the database is exactly what the migrations promise.
    """
    # One loader for the whole run: building it walks every installed app and
    # imports every migration module, which is the expensive part of this check.
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    findings = _migration_record_findings(connection, loader)
    expected = _expected_tables(loader)
    actual = _actual_tables(connection)

    for table in sorted(set(expected) & set(actual)):
        for column in sorted(actual[table] - expected[table]):
            if (table, column) in _DELIBERATE_DIVERGENCES:
                continue
            findings.append(
                DriftFinding(
                    kind=DriftKind.COLUMN_IN_DATABASE_ONLY,
                    table=table,
                    column=column,
                    message=(
                        f"column '{column}' exists on table '{table}' but no migration "
                        "creates it. It was almost certainly added by a migration that "
                        "has since been deleted or rewritten. Rebuild the local "
                        "database: npm run dev:reset"
                    ),
                )
            )
        for column in sorted(expected[table] - actual[table]):
            findings.append(
                DriftFinding(
                    kind=DriftKind.COLUMN_IN_MIGRATIONS_ONLY,
                    table=table,
                    column=column,
                    message=(
                        f"the migrations create column '{column}' on table '{table}', but "
                        "the database has no such column. This database is behind the "
                        "migration graph. Run: npm run dev:setup"
                    ),
                )
            )

    for table in sorted(set(actual) - set(expected) - _TABLES_WITHOUT_A_MODEL):
        findings.append(
            DriftFinding(
                kind=DriftKind.TABLE_IN_DATABASE_ONLY,
                table=table,
                column="",
                message=(
                    f"table '{table}' exists but no migration creates it. Rebuild the "
                    "local database: npm run dev:reset"
                ),
            )
        )

    for table in sorted(set(expected) - set(actual)):
        findings.append(
            DriftFinding(
                kind=DriftKind.TABLE_IN_MIGRATIONS_ONLY,
                table=table,
                column="",
                message=(
                    f"the migrations create table '{table}', but the database has no such "
                    "table. Run: npm run dev:setup"
                ),
            )
        )

    return findings
