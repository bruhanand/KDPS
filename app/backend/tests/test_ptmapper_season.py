"""Season precedence (review medium: 'season is a name, never a date').

A date-derived season label must never beat an explicit season code. Pure
function with a fake resolver — no DB/server — so it runs in CI's `pytest tests`.
"""

from __future__ import annotations

from ptmapper.engine import _map_season


class _Resolver:
    def season_from_code(self, code, ctx=None):
        return "SS26" if code.strip().upper() == "SS26" else None

    def season_from_date(self, d):
        return "AW25"


def _g(season_src: str, date_src: str):
    values = {"SEASON_SRC": season_src, "DATE_SRC": date_src}
    return lambda role: values.get(role)


def test_explicit_season_code_beats_the_invoice_date():
    # _map_season now returns (value, source); the explicit code resolves via 'alias'.
    assert _map_season(_Resolver(), _g("SS26", "2025-11-01"), {}) == ("SS26", "alias")


def test_falls_back_to_date_when_no_season_code():
    assert _map_season(_Resolver(), _g("", "2025-11-01"), {}) == ("AW25", "derived")
