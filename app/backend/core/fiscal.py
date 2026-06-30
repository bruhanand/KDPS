"""Indian financial year helper (Apr–Mar), shared by every numbering series."""

from __future__ import annotations

from datetime import date


def financial_year(d: date | None = None) -> str:
    """`YY-YY` for the Apr–Mar FY of `d` (today if omitted). Jun-2026 → '26-27'."""
    d = d or date.today()
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"
