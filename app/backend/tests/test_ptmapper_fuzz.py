"""Fuzz / property tests for the mechanical normalisers.

No external property-testing lib available, so we use a seeded generator over a
realistic character set plus a curated adversarial corpus. The invariants that must
hold for ANY input (so a malformed brand cell can never crash the mapper or produce a
half-normalised value):
  * never raises;
  * returns a str;
  * idempotent — f(f(x)) == f(x) (re-running the engine can't drift a value);
  * output shape (colour upper-cased & code-stripped; size trimmed; gender in-vocab).
"""

from __future__ import annotations

import random
import re
import string

import pytest

from ptmapper.engine import gender_from_text, normalize_color, normalize_size

# A charset that mirrors what real brand size/colour cells throw at us.
_CHARSET = string.ascii_letters + string.digits + " /()-.,#" + "XSML" * 3 + "  "
_TOKENS = [
    "XL",
    "2XL",
    "XXL",
    "3XL",
    "S",
    "M",
    "L",
    "FS",
    "FREE",
    "36",
    "1.14M",
    "(2XL)",
    "CMS",
    "CM",
    "/XS",
    "YEARS",
    "Y",
    "7-8",
    "0-6",
    "88-",
    "BLUE",
    "LIGHT",
    "DN89",
    "BLACK73/1",
    "(105 CMS)",
    "MID",
    "PEACH",
    "MENS",
    "GIRLS",
    "",
    "  ",
    "((",
    "//",
]
_VALID_GENDERS = {"", "MALE", "FEMALE", "KIDS MALE", "KIDS FEMALE", "UNISEX"}

_ADVERSARIAL = [
    "",
    " ",
    None,
    "()",
    "(((",
    ")))",
    "//",
    "///",
    "-",
    "--",
    "12-",
    "(2XL",
    "2XL)",
    "1.14M(2XL)(L)",
    "XL/S/M",
    "36 / 38 / 40",
    "  XXL  ",
    "\t\n",
    "9" * 200,
    "ZÉBRA",
    "BLEU/ROUGE",
    "36/XS/extra",
    "0",
    "0.0",
    "()()",
    "(())",
    "M(L)(XL)",
    "FREE SIZE / XL",
    "10-11 YEARS OLD",
    "1 MTR.5 CM.",
    "##BLACK##",
    "/",
    "(/)",
]


def _gen(rng: random.Random) -> str:
    n = rng.randint(0, 18)
    if rng.random() < 0.3:  # token salad
        return " ".join(rng.choice(_TOKENS) for _ in range(rng.randint(1, 4)))
    return "".join(rng.choice(_CHARSET) for _ in range(n))


@pytest.mark.parametrize("fn", [normalize_size, normalize_color])
def test_normaliser_never_crashes_and_is_idempotent(fn):
    rng = random.Random(20260701)
    cases = list(_ADVERSARIAL) + [_gen(rng) for _ in range(600)]
    for raw in cases:
        out = fn(raw)
        assert isinstance(out, str), f"{fn.__name__}({raw!r}) -> {out!r} (not str)"
        again = fn(out)
        assert again == out, f"{fn.__name__} not idempotent: {raw!r} -> {out!r} -> {again!r}"


def test_normalize_color_output_shape():
    rng = random.Random(7)
    for raw in list(_ADVERSARIAL) + [_gen(rng) for _ in range(400)]:
        out = normalize_color(raw)
        assert out == out.strip(), f"colour not trimmed: {out!r}"
        assert out == out.upper(), f"colour not upper: {out!r}"
        # if the output carries a shade word, a leading "<digits>-" code must be stripped
        # (an all-code junk input like "12-" is preserved verbatim for review, exempt here)
        if re.search(r"[A-Z]", out):
            assert not re.match(r"^\d+\s*[-_]", out), f"leading code survived: {out!r}"


def test_normalize_size_output_shape():
    rng = random.Random(99)
    for raw in list(_ADVERSARIAL) + [_gen(rng) for _ in range(400)]:
        out = normalize_size(raw)
        assert out == out.strip(), f"size not trimmed: {out!r}"
        assert "\n" not in out and "\t" not in out


def test_gender_from_text_always_in_vocab():
    rng = random.Random(123)
    for raw in [_gen(rng) for _ in range(400)] + ["mens", "GIRLS top", "x", ""]:
        assert gender_from_text(raw or "") in _VALID_GENDERS
