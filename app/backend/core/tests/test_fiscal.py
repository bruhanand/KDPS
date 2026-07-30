"""The Indian financial year, both ways round.

`financial_year` has been read from since K0 (every numbering series names one).
`financial_year_months` is the inverse, added with the store-target grid (#171),
and the pair has one thing to prove: they agree about where a month lives, so a
label written by one is understood by the other and March never drifts a year.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.fiscal import financial_year, financial_year_months


def test_the_year_opens_in_april_and_closes_in_march():
    months = financial_year_months("26-27")
    assert months[0] == date(2026, 4, 1)
    assert months[-1] == date(2027, 3, 1)
    assert len(months) == 12


def test_every_month_is_its_own_first_day():
    assert all(month.day == 1 for month in financial_year_months("26-27"))


def test_the_two_directions_agree():
    """The property that matters: label → months → label is the identity. A
    calendar-year reading of `26-27` would break on exactly the three months the
    Indian FY moves — Jan, Feb and Mar."""
    for month in financial_year_months("26-27"):
        assert financial_year(month) == "26-27"


def test_january_belongs_to_the_year_that_started_the_april_before():
    assert date(2027, 1, 1) in financial_year_months("26-27")
    assert date(2027, 1, 1) not in financial_year_months("27-28")


@pytest.mark.parametrize("label", ["2026", "26/27", "26-27-28", "", "  ", "ab-cd", "26-27 "])
def test_a_label_that_is_not_a_label_is_refused(label):
    """`26-27 ` with a trailing space is fine — a URL is allowed to be untidy —
    but nothing that would change the *meaning* is guessed at."""
    if label.strip() == "26-27":
        assert financial_year_months(label) == financial_year_months("26-27")
        return
    with pytest.raises(ValueError):
        financial_year_months(label)


@pytest.mark.parametrize("label", ["26-28", "26-26", "27-26"])
def test_two_halves_that_are_not_consecutive_years_are_refused(label):
    """Shape alone is not enough: `26-28` looks like a label and means nothing,
    and reading it as 2026-27 would silently answer a question nobody asked."""
    with pytest.raises(ValueError):
        financial_year_months(label)


def test_the_century_rollover_still_reads_as_consecutive():
    """`99-00` is a real label `financial_year` would write, so the consecutive
    check has to be modular rather than a plain `+1`."""
    assert financial_year_months("99-00")[0] == date(2099, 4, 1)
