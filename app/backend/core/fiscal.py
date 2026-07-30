"""Indian financial year helper (Apr–Mar), shared by every numbering series."""

from __future__ import annotations

import re
from datetime import date

#: The FY label's only spelling — two digits, a dash, two digits (`26-27`). The
#: same shape `financial_year` writes, so a label that round-trips is the only
#: one this module accepts.
_FY_LABEL = re.compile(r"^(\d{2})-(\d{2})$")

#: FY labels carry two digits, so reading one back needs a century. KDPS's books
#: begin in this one; a `26-27` meaning 1926 or 2126 is not a case that exists.
_CENTURY = 2000

#: April — the month an Indian financial year opens on.
FY_START_MONTH = 4


def financial_year(d: date | None = None) -> str:
    """`YY-YY` for the Apr–Mar FY of `d` (today if omitted). Jun-2026 → '26-27'."""
    d = d or date.today()
    start = d.year if d.month >= FY_START_MONTH else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def financial_year_months(fy: str) -> list[date]:
    """The twelve months of FY `fy`, each as its own first day, April first.

    `'26-27'` → 1 Apr 2026 … 1 Mar 2027. The inverse of `financial_year`, and
    deliberately the *months* rather than a start/end pair: every caller so far
    wants either the twelve columns of a grid or the ends of the range, and
    handing back the months gives both without a second helper that could
    disagree with this one about where March sits.

    Raises `ValueError` on anything `financial_year` would not have written —
    including a well-formed label whose two halves are not consecutive years, so
    `'26-28'` is refused rather than quietly read as 2026-27.
    """
    matched = _FY_LABEL.match(fy.strip())
    if not matched:
        raise ValueError(f"Not a financial year label: {fy!r}. Expected 'YY-YY', e.g. '26-27'.")
    first, second = (int(part) for part in matched.groups())
    if second != (first + 1) % 100:
        raise ValueError(f"Not a financial year: {fy!r}. The two halves must be consecutive years.")
    start = _CENTURY + first
    return [
        date(start + (0 if month >= FY_START_MONTH else 1), month, 1)
        for month in [*range(FY_START_MONTH, 13), *range(1, FY_START_MONTH)]
    ]
