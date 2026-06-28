"""K1 golden test 2 — a ledger row can only ever be INSERTed.

The DB trigger is the load-bearing guarantee: a raw `UPDATE`/`DELETE` raises even
for the role CI connects as (the `kdps` superuser). The ORM `LedgerEntry` base is
the early, clean error before SQL is ever reached.
"""

from __future__ import annotations

import pytest
from django.db import DatabaseError, connection, transaction

from core.ledger import AppendOnlyError, LedgerProbe

TABLE = LedgerProbe._meta.db_table


@pytest.mark.django_db
def test_raw_update_is_forbidden_even_for_superuser() -> None:
    row = LedgerProbe.objects.create(amount=500)
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"UPDATE {TABLE} SET amount = 999 WHERE id = %s", [row.pk])
    # untouched
    assert LedgerProbe.objects.get(pk=row.pk).amount == 500


@pytest.mark.django_db
def test_raw_delete_is_forbidden_even_for_superuser() -> None:
    row = LedgerProbe.objects.create(amount=500)
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE id = %s", [row.pk])
    assert LedgerProbe.objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
def test_raw_insert_still_succeeds() -> None:
    with connection.cursor() as cur:
        cur.execute(f"INSERT INTO {TABLE} (amount, created_at) VALUES (%s, now())", [42])
    assert LedgerProbe.objects.filter(amount=42).exists()


@pytest.mark.django_db
def test_orm_save_on_persisted_row_raises() -> None:
    row = LedgerProbe.objects.create(amount=500)
    reloaded = LedgerProbe.objects.get(pk=row.pk)
    with pytest.raises(AppendOnlyError):
        reloaded.save()


@pytest.mark.django_db
def test_orm_delete_raises() -> None:
    row = LedgerProbe.objects.create(amount=500)
    with pytest.raises(AppendOnlyError):
        row.delete()
