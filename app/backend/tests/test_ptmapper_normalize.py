"""Golden unit tests for the mechanical value normalisers (SKU = Style × Size × Color).

Brand PT files write size/colour in dozens of dialects; these pure functions fold
each into the KDPS canonical form so it lands directly on a Master-Sheet value.
No DB, no server — runs in CI's `pytest tests` step.
"""

from __future__ import annotations

import pytest

from ptmapper.engine import gender_from_text, normalize_color, normalize_size


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("44.0", "44"),  # float artifact from a numeric cell
        ("92.0", "92"),
        ("1.14M(2XL)", "XXL"),  # metric + alpha → the alpha, 2XL→XXL (master has XXL)
        ("96CM(M)", "M"),
        ("1.02M(L)", "L"),
        ("1.20M(3XL)", "3XL"),
        ("XL (105 CMS)", "XL"),  # alpha is the BASE, measurement in the parens
        ("L (1 MTR.)", "L"),
        ("100 CMS", "100"),  # plural CMS suffix dropped to a bare master size
        ("96 CM", "96 CM"),  # singular CM kept (Master keeps "96 CM" distinct from "96")
        ("36/XS", "XS"),  # num/alpha = same size, two notations → the alpha
        ("44/XXL", "XXL"),
        ("46/3XL", "3XL"),
        ("40/L", "L"),
        ("S/M", "S/M"),  # two DIFFERENT sizes → ambiguous, left for review (not "M")
        ("36/38", "36/38"),  # two numerics → ambiguous, left for review
        ("7-8Y", "7-8 Y"),  # age band, compact
        ("8-9 YEARS", "8-9 Y"),  # age band, spelled
        ("10-11 YEARS", "10-11 Y"),
        ("0-6 M", "0-6 M"),  # months
        ("FS", "FREE SIZE"),
        ("FREE", "FREE SIZE"),
        ("2XL", "XXL"),
        ("XL", "XL"),  # plain alpha passes through
        ("XXL", "XXL"),
        ("30B", "30B"),  # bra size passes through
        ("FREE SIZE", "FREE SIZE"),
        ("M", "M"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_size(raw, expected):
    assert normalize_size(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("88-BEIGE", "BEIGE"),  # leading numeric code
        ("16-BLUE", "BLUE"),
        ("134-BLUE BLACK", "BLUE BLACK"),
        ("BLACK73/1", "BLACK"),  # trailing lot code
        ("WHITE74", "WHITE"),
        ("BLUE DN89", "BLUE"),  # denim wash code
        ("L BLU DN88", "L BLU"),
        ("INDIGO MEL", "INDIGO"),  # melange code
        ("MID BLUE", "MID BLUE"),  # plain shade word kept (bucketed via lookup)
        ("  Light  Blue ", "LIGHT BLUE"),  # whitespace + case folded
        ("CP 1", "CP"),  # opaque code → stays for the review queue
        ("501", "501"),  # all-numeric code preserved (never blanked → stays reviewable)
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_color(raw, expected):
    assert normalize_color(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Senior Girls Top", "KIDS FEMALE"),
        ("Junior Boys Shirt", "KIDS MALE"),
        ("SOCKS-MENS", "MALE"),  # separator-glued tokens still match
        ("MENS TRACK PANT", "MALE"),
        ("WOMAN TOP DEAL", "FEMALE"),
        ("LADIES KURTI", "FEMALE"),
        ("Kids Wear", "UNISEX"),
        ("plain cotton shirt", ""),  # no gender word → blank (never guessed)
    ],
)
def test_gender_from_text(text, expected):
    assert gender_from_text(text) == expected


def test_women_does_not_trip_the_men_keyword():
    assert gender_from_text("WOMEN BLOUSE") == "FEMALE"
