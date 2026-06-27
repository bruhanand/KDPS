"""K1 golden test 1 — money is integer paise, no float drift.

`MoneyField` stores a `bigint` paise value; a save→reload round-trip returns the
*exact* same `int`. Every rupee↔paise conversion uses Decimal/int math only —
there is no `float` on any code path.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.ledger import LedgerProbe
from core.money import paise_to_rupees_str, rupees_to_paise

# A spread: 1 paise, sub-rupee, the ₹28,50,000 example, a large value, and a
# signed value (a ledger leg may be negative).
PAISE_VALUES = [1, 999, 28_50_00_000, 285_000_000, 9_999_999_999, -150]


@pytest.mark.django_db
@pytest.mark.parametrize("paise", PAISE_VALUES)
def test_paise_round_trips_with_no_float_drift(paise: int) -> None:
    row = LedgerProbe.objects.create(amount=paise)
    reloaded = LedgerProbe.objects.get(pk=row.pk)
    assert reloaded.amount == paise
    assert type(reloaded.amount) is int  # never float


def test_rupees_to_paise_is_exact() -> None:
    # ₹28,50,000 → 285000000 paise (the CONTEXT example).
    assert rupees_to_paise(Decimal("2850000")) == 285_000_000
    assert rupees_to_paise(Decimal("100.50")) == 10_050
    assert rupees_to_paise("0.01") == 1
    assert rupees_to_paise(2500) == 2_50_000
    result = rupees_to_paise(Decimal("1.005"))  # half-up at the paise
    assert isinstance(result, int)
    assert result == 101


def test_rupees_to_paise_rejects_float() -> None:
    with pytest.raises(TypeError):
        rupees_to_paise(100.5)  # type: ignore[arg-type]


def test_paise_to_rupees_str_round_trips() -> None:
    assert paise_to_rupees_str(285_000_000) == "2850000.00"
    assert paise_to_rupees_str(10_050) == "100.50"
    assert paise_to_rupees_str(1) == "0.01"
    assert paise_to_rupees_str(-150) == "-1.50"
    # round-trip through the pair
    assert rupees_to_paise(paise_to_rupees_str(123_456)) == 123_456
