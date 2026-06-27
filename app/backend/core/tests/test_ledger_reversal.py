"""K1 golden test 3 — a correction is a new reversing row that nets to zero.

The original posting is never edited; the fix is a fresh, append-only `-X` row.
`SUM(amount)` over the pair is exactly the integer 0.
"""

from __future__ import annotations

import pytest
from django.db.models import Sum

from core.ledger import LedgerProbe

X = 285_000_000


@pytest.mark.django_db
def test_reversal_nets_to_zero() -> None:
    original = LedgerProbe.objects.create(amount=X)
    original_created_at = original.created_at

    LedgerProbe.objects.create(amount=-X)  # the reversing entry

    total = LedgerProbe.objects.aggregate(s=Sum("amount"))["s"]
    assert total == 0
    assert type(total) is int

    # the original row is byte-for-byte untouched — a new row was added, not an edit
    refetched = LedgerProbe.objects.get(pk=original.pk)
    assert refetched.amount == X
    assert refetched.created_at == original_created_at
    assert LedgerProbe.objects.count() == 2
