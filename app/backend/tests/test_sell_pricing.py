"""Taking a price tag apart (#177).

An Indian apparel price tag is GST-inclusive, so the counter works backwards
from what the customer paid. Two rules decide the answer and both are easy to get
subtly wrong, which is why they are pinned here rather than only through the API:

  · the slab is chosen on the GST-**exclusive**, post-discount, **per-piece**
    price (CONTEXT.md) - so two ₹2,000 shirts on one line are two 5% pieces, not
    one 18% line;
  · the base is rounded and the tax is the **remainder**, so base + tax is
    exactly what was paid, with no half-paisa left over to explain at day end.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from sell.pricing import Slab, base_from_inclusive, split_inclusive, split_line

SLAB = Slab(
    threshold_paise=250000,  # ₹2,500 a piece
    rate_below=Decimal("5"),
    rate_above=Decimal("18"),
    effective_from=date(2025, 9, 22),
)


def test_base_and_tax_always_add_back_to_what_was_paid():
    """The property that matters. Anything else drifts, a paisa a line, until a
    day's takings and a day's GST disagree and nobody can say by how much."""
    for paise in (1, 99, 149900, 250000, 250001, 999999, 1234567):
        for rate in (Decimal("5"), Decimal("18")):
            split = split_inclusive(paise, rate)
            assert split.base_paise + split.gst_paise == paise


def test_a_fifteen_hundred_rupee_shirt_carries_five_percent():
    split = split_line(149900, 1, SLAB)

    assert split.rate == Decimal("5")
    assert split.base_paise == 142762  # 1499 / 1.05, half-up
    assert split.gst_paise == 7138


def test_a_five_thousand_rupee_jacket_carries_eighteen_percent():
    split = split_line(500000, 1, SLAB)

    assert split.rate == Decimal("18")
    assert split.base_paise + split.gst_paise == 500000


def test_the_threshold_is_per_piece_not_per_line():
    """Two ₹2,000 shirts are ₹4,000 on the line and 5% all the same."""
    two_shirts = split_line(400000, 2, SLAB)
    one_jacket = split_line(400000, 1, SLAB)

    assert two_shirts.rate == Decimal("5")
    assert one_jacket.rate == Decimal("18")


def test_the_slab_is_decided_on_the_price_without_tax_in_it():
    """A piece whose *inclusive* price is over ₹2,500 but whose base is not stays
    at 5% - anchoring on the tag instead would push it over its own boundary."""
    inclusive = 262000  # ₹2,620 on the tag; base at 5% is ₹2,495.24
    split = split_line(inclusive, 1, SLAB)

    assert split.rate == Decimal("5")
    assert split.base_paise <= SLAB.threshold_paise


def test_a_discount_can_move_a_piece_down_a_slab():
    """The slab follows the post-discount price, so an EOSS jacket is 5%."""
    assert split_line(500000, 1, SLAB).rate == Decimal("18")
    assert split_line(200000, 1, SLAB).rate == Decimal("5")


def test_rounding_is_half_up_and_never_loses_the_odd_paisa():
    assert base_from_inclusive(105, Decimal("5")) == 100
    assert base_from_inclusive(1, Decimal("5")) == 1
    assert split_inclusive(1, Decimal("5")).gst_paise == 0


def test_a_line_with_no_pieces_is_not_a_line():
    with pytest.raises(ValueError):
        split_line(1000, 0, SLAB)
