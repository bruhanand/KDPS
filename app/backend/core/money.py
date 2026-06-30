"""Money = integer paise (ADR-0004).

Every stored monetary amount is an integer number of paise in a `bigint`. This
makes *balance = sum of postings* an exact integer sum with zero float / rounding
drift — the double-entry sum-to-zero checksum is exact. There is no `float` on
any code path here: conversions use `Decimal`/`int` only.

Lakh/Crore *display* formatting and the ₹ input widget are K9 — these helpers do
only lossless conversion.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import BigIntegerField

PAISE_PER_RUPEE = 100

# `BigIntegerField` is generic to django-stubs but not subscriptable at runtime,
# so we pin the get/set types for the type checker only.
if TYPE_CHECKING:
    # Get/set typed Optional so nullable money columns (null=True) type-check;
    # non-null columns are still enforced by the DB and `_ensure_int_paise`.
    _MoneyBase = BigIntegerField[int | None, int | None]
else:
    _MoneyBase = BigIntegerField


class MoneyField(_MoneyBase):
    """A signed amount in integer paise. The stored Python value is always `int`.

    A semantic subclass of `BigIntegerField` that, unlike its parent, refuses to
    *coerce*: plain `BigIntegerField` runs `int(value)`, so a stray `1.9` or
    `Decimal("1.9")` silently truncates to `1` on write. A money column must never
    swallow that — a `float`/`Decimal` reaching here means precision was already
    lost upstream. Convert at the edge with `rupees_to_paise()`; the field accepts
    only `int` (and `None`), rejecting `bool`, `float`, `Decimal` and everything
    else. This guards every write path, not just the helper.
    """

    description = "Money amount in integer paise"

    def _ensure_int_paise(self, value: Any) -> int | None:
        if value is None:
            return None
        # bool is an int subclass, but True/False as an amount is always a bug.
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"{type(self).__name__} stores integer paise; refusing "
                f"{type(value).__name__} {value!r}. Convert at the edge with "
                "rupees_to_paise() — a float/Decimal must never reach a money column."
            )
        return value

    def get_prep_value(self, value: Any) -> int | None:
        # The DB-write boundary: this is where BigIntegerField would coerce.
        return self._ensure_int_paise(value)

    def to_python(self, value: Any) -> int | None:
        # The deserialization / full_clean() boundary.
        return self._ensure_int_paise(value)


def rupees_to_paise(rupees: Decimal | str | int) -> int:
    """Convert a rupee amount to integer paise, half-up at the paise.

    Accepts `Decimal`, `str` or `int` — never `float` (a float would already have
    lost precision before it got here). Rounds half-up to whole paise, the
    India-standard rule (ADR-0004).
    """
    if isinstance(rupees, bool) or isinstance(rupees, float):
        raise TypeError(f"pass Decimal/str/int, never {type(rupees).__name__}")
    amount = rupees if isinstance(rupees, Decimal) else Decimal(rupees)
    paise = (amount * PAISE_PER_RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(paise)


def paise_to_rupees_str(paise: int) -> str:
    """Render integer paise as a plain `"<rupees>.<paise>"` string (no grouping).

    Lakh/Crore grouping and the ₹ symbol are K9; this is the lossless inverse of
    `rupees_to_paise` for round-tripping and tests.
    """
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError(f"paise must be int, got {type(paise).__name__}")
    sign = "-" if paise < 0 else ""
    rupees, sub = divmod(abs(paise), PAISE_PER_RUPEE)
    return f"{sign}{rupees}.{sub:02d}"
