"""Golden unit test for the Ginesys colour-prefix fix (SKU = Style × Size × Color).

Ginesys/Madura PT files (MUFTI, BEEVEE, GO COLOURS) encode colour in CATEGORY3 as
"<code>-NAME" (e.g. "16-BLUE"), so the bare-name colour lookup missed and stock
posted with EMPTY colour. The ginesys_pt_email profile now carries
`color_strip_code_prefix`, which strips the numeric code before lookup.

Pure function — no DB, no server — so it runs in CI's `pytest tests` step.
"""

from __future__ import annotations

from ptmapper.engine import _color_src


def _g(value: str):
    """A minimal _getter: returns `value` for COLOR_SRC, None otherwise."""
    return lambda role: value if role == "COLOR_SRC" else None


def test_strips_numeric_code_prefix_when_flag_set():
    profile = {"flags": {"color_strip_code_prefix": True}}
    assert _color_src(_g("16-BLUE"), profile) == "BLUE"
    assert _color_src(_g("163-LIGHT BLUE"), profile) == "LIGHT BLUE"
    assert _color_src(_g("04-GREEN"), profile) == "GREEN"
    # whitespace around the code/dash is tolerated
    assert _color_src(_g(" 86 - TINTED "), profile) == "TINTED"


def test_plain_colour_name_is_unchanged_even_with_flag():
    profile = {"flags": {"color_strip_code_prefix": True}}
    assert _color_src(_g("BLUE"), profile) == "BLUE"
    assert _color_src(_g("NAVY BLUE"), profile) == "NAVY BLUE"  # no leading code → untouched


def test_no_strip_without_the_flag():
    profile = {"flags": {}}
    assert _color_src(_g("16-BLUE"), profile) == "16-BLUE"
    assert _color_src(_g("BLUE"), profile) == "BLUE"
