"""The GSTIN checker on its own (#187) - no database, one string at a time.

Two properties are worth pinning here rather than through a bill:

  · **It agrees with reality.** The three registrations below are real ones, and
    they are the whole argument that the check digit is computed the way the GSTN
    computes it. A checksum that were subtly wrong would pass its own unit tests
    happily and flag every genuine B2B bill KDPS ever takes.
  · **It says *why*.** The reason goes into a `ContinuityFlag` a clerk at head
    office reads, and "not a GSTIN" is not something anybody can act on.

The mirror of this module is `till/gstin.ts`, tested against the same strings:
the counter prints the split offline and the server re-derives it, so the two
must not be able to disagree.
"""

from __future__ import annotations

import pytest

from sell.gstin import WELL_FORMED, check_digit, describe, is_well_formed, normalise, state_code

#: Registrations that exist. Two different check digits and a letter one, so a
#: checksum that were off by a constant could not pass all three.
REAL = [
    "27AAPFU0939F1ZV",
    "27AAACR5055K1Z7",
    "09AAACH7409R1ZZ",
]


@pytest.mark.parametrize("gstin", REAL)
def test_a_real_registration_is_well_formed(gstin):
    assert describe(gstin) == WELL_FORMED


@pytest.mark.parametrize("gstin", REAL)
def test_the_check_digit_is_the_one_the_gstn_issued(gstin):
    assert check_digit(gstin[:14]) == gstin[14]


def test_nothing_typed_is_not_a_complaint():
    """A B2C bill has no GSTIN, and that is not a defect to flag."""
    assert describe("") == WELL_FORMED
    assert describe("   ") == WELL_FORMED


def test_a_short_one_says_how_short():
    assert "15 characters" in describe("27AAPFU0939F")


def test_something_that_is_not_a_gstin_at_all_says_so():
    assert "Not shaped like a GSTIN" in describe("HELLO WORLD 123")


def test_a_state_code_the_gstn_does_not_issue_is_named():
    # 45 is not a state; the rest of the string is shaped perfectly.
    assert "not a state code" in describe("45AAPFU0939F1ZV")


def test_a_transposed_pair_survives_the_shape_and_fails_the_checksum():
    """The commonest real mistype, and the reason the checksum is here at all."""
    reason = describe("27AAPFU0993F1ZV")
    assert "check digit" in reason


def test_the_last_character_being_wrong_is_caught():
    assert "check digit" in describe("27AAPFU0939F1ZW")


def test_case_and_spaces_are_the_counter_typing_not_a_mistake():
    assert is_well_formed("  27aapfu0939f1zv  ")
    assert normalise("  27aapfu0939f1zv  ") == "27AAPFU0939F1ZV"


def test_the_state_is_taken_as_typed_even_when_the_rest_is_wrong():
    """What the till printed is what the books must record (see `_b2b_tax_kind`)."""
    assert state_code("20AABCU9603R1ZM") == "20"
    assert state_code("zz-nonsense") == "ZZ"
