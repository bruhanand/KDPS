"""The GSTIN checker on its own (#187) - no database, one string at a time.

The cases are not written here. They live in `sell/vectors/gstin.json`, and the
TypeScript port reads the very same file (`src/till/gstin.vectors.test.ts`) -
the "two engines, one set of golden files" shape the offer rulebook already uses,
and for the same reason.

The reason is the whole point of this module. The bill's tax split is decided at
the counter, offline, and printed on the customer's copy minutes before this
server hears about the sale; the accept pipeline then derives it again. Two
implementations that could disagree would put one tax on the paper and another in
the books, silently, on every B2B bill. A shared vector file is what makes
"they agree" a red build rather than a hope - including the *messages*, which are
what a head-office clerk reads off the flag.

What is asserted here and not in the vectors is the check digit itself, against
three real registrations. A checksum subtly wrong would pass its own unit tests
happily and flag every genuine B2B bill KDPS ever takes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sell.gstin import WELL_FORMED, check_digit, describe, is_well_formed, normalise, state_code

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "sell" / "vectors" / "gstin.json").read_text()
)


def _ids(cases: list[dict[str, Any]], key: str) -> list[str]:
    """Name each parametrised case by the string it drives, so a failure says which."""
    return [repr(case[key]) for case in cases]


@pytest.mark.parametrize(
    "case", VECTORS["well_formedness"], ids=_ids(VECTORS["well_formedness"], "gstin")
)
def test_well_formedness(case):
    assert describe(case["gstin"]) == case["reason"]
    assert is_well_formed(case["gstin"]) is (case["reason"] == WELL_FORMED)


@pytest.mark.parametrize("case", VECTORS["state_code"], ids=_ids(VECTORS["state_code"], "gstin"))
def test_the_state_is_the_first_two_characters_as_typed(case):
    assert state_code(case["gstin"]) == case["state_code"]


@pytest.mark.parametrize("case", VECTORS["tax_kind"], ids=_ids(VECTORS["tax_kind"], "buyer_gstin"))
def test_which_split_the_bill_carries(case):
    """The rule itself, spelled once here and once in `accept._b2b_tax_kind`.

    Not imported from the pipeline, because the pipeline's copy takes a `Store`
    and this is a question about two strings; what keeps them in step is that
    both are three lines long and both are on this file's cases.
    """
    kind = "none"
    if normalise(case["buyer_gstin"]):
        kind = (
            "cgst_sgst" if state_code(case["buyer_gstin"]) == case["store_state_code"] else "igst"
        )
    assert kind == case["kind"]


#: Registrations that exist. Two different check digits and a letter one, so a
#: checksum off by a constant could not pass all three.
REAL = ["27AAPFU0939F1ZV", "27AAACR5055K1Z7", "09AAACH7409R1ZZ"]


@pytest.mark.parametrize("gstin", REAL)
def test_the_check_digit_is_the_one_the_gstn_issued(gstin):
    assert check_digit(gstin[:14]) == gstin[14]


def test_the_counters_typing_is_tidied_once(gstin="  27aapfu0939f1zv  "):
    assert normalise(gstin) == "27AAPFU0939F1ZV"
