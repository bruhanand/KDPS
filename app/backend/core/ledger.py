"""Append-only ledger base (ADR-0004).

A ledger row can only ever be INSERTed. A correction is a *new*, today-dated
reversing row — never an edit or a delete. The guarantee is defence-in-depth:

1. **The DB trigger is primary** — a `BEFORE UPDATE OR DELETE` row trigger that
   `RAISE EXCEPTION`s. It blocks *every* role, including the superuser/owner CI
   connects as (a `REVOKE` cannot stop a superuser; only a trigger can).
2. **`REVOKE UPDATE, DELETE`** is defence-in-depth for the eventual non-owner
   production app role.
3. **The `LedgerEntry` ORM base** is the early, clean error before SQL is reached.

`post_entries`, docstatus, dimensions and SCD-2 belong to later kernel slices —
this module is only the two engine primitives K1 owns.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from core.money import MoneyField

#: One shared trigger function for every ledger table.
TRIGGER_FUNCTION = "kdps_forbid_update_delete"


class AppendOnlyError(Exception):
    """Raised by the ORM base when something tries to mutate a persisted row."""


class LedgerEntry(models.Model):
    """Abstract base for every append-only ledger.

    Carries only the two things K1 owns: a signed paise `amount` and an immutable
    `created_at` insert stamp. Actor, dimensions, docstatus and the three keys
    arrive in K2/K3 — they are deliberately absent here.
    """

    amount = MoneyField()  # signed paise — a leg may be + or −
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{type(self).__name__}({self.amount} paise)"

    def save(self, *args: Any, **kwargs: Any) -> None:
        # `_state.adding` is True only for a never-persisted instance. Anything
        # else is an UPDATE in disguise — refuse it before the DB has to.
        if not self._state.adding:
            raise AppendOnlyError(
                "ledger rows are append-only; post a reversing entry instead of editing"
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise AppendOnlyError(
            "ledger rows are append-only; post a reversing entry instead of deleting"
        )


def append_only_sql(table_name: str) -> str:
    """SQL that makes `table_name` append-only: the shared trigger + a REVOKE.

    `CREATE OR REPLACE` on the function makes this idempotent across every ledger
    table that installs it. Run from a migration (the grants/triggers are
    themselves migrations, ADR-0004).
    """
    trigger_name = f"{table_name}_forbid_update_delete"
    return f"""
    CREATE OR REPLACE FUNCTION {TRIGGER_FUNCTION}() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION
            'append-only: % on % is forbidden; post a reversing entry',
            TG_OP, TG_TABLE_NAME;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER {trigger_name}
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FUNCTION}();

    REVOKE UPDATE, DELETE ON {table_name} FROM PUBLIC;
    """


def append_only_reverse_sql(table_name: str) -> str:
    """Reverse of `append_only_sql` for a single table (leaves the shared function)."""
    return f"DROP TRIGGER IF EXISTS {table_name}_forbid_update_delete ON {table_name};"


class LedgerProbe(LedgerEntry):
    """Kernel-internal concrete ledger that exercises the append-only invariants
    against real Postgres.

    NOT a business ledger — the stock, vendor and cash ledgers arrive with their
    business slices. This exists only so K1's trigger genuinely runs in the DB and
    the three golden tests have a concrete table to post against.
    """

    class Meta:
        db_table = "core_ledger_probe"
