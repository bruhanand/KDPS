"""MRP-inclusive tax arithmetic for a bill line - pure functions, no ORM.

A price tag in an Indian apparel store is GST-inclusive, so the counter works
backwards: the customer pays the tag less the offer, and the tax already sits
inside that number. Two things follow, and both are easy to get subtly wrong.

**Which slab.** `CONTEXT.md` locks it: 5% at or under ₹2,500 per piece, 18% above,
decided on the GST-**exclusive**, post-discount, per-piece price. That is
circular on the face of it - the base depends on the rate and the rate depends on
the base - and it resolves cleanly because the mapping is monotone: price the
piece at the lower rate first, and if the base that produces is still inside the
threshold, the lower rate is the right one. There is no tie to break and the MRP
can never cross the boundary its own slab was chosen by. `ptmapper.pricing`
anchors on the same base going the other way, which is what keeps a piece priced
by head office and the same piece sold at the counter in the same slab.

**Where the half-paisa goes.** The base is rounded half-up and the tax is the
remainder, never rounded separately - so base + tax is exactly what the customer
paid, on every line, with no drift to explain at the end of the day.

Both functions are advisory here: the till has already priced the bill and
printed it. The server recomputes to *compare* (contract step 12), and a
disagreement raises a flag rather than a refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class Slab:
    """One date-effective apparel GST slab, in the units the till speaks."""

    threshold_paise: int
    rate_below: Decimal
    rate_above: Decimal
    effective_from: date

    def rate_for_base(self, base_paise: int) -> Decimal:
        return self.rate_below if base_paise <= self.threshold_paise else self.rate_above


@dataclass(frozen=True)
class TaxSplit:
    """A GST-inclusive line, taken apart."""

    rate: Decimal
    base_paise: int
    gst_paise: int


def base_from_inclusive(inclusive_paise: int, rate: Decimal) -> int:
    """The GST-exclusive base inside a tax-inclusive amount, rounded half-up."""
    return int(
        (Decimal(inclusive_paise) * _HUNDRED / (_HUNDRED + rate)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )


def split_inclusive(inclusive_paise: int, rate: Decimal) -> TaxSplit:
    """Split a tax-inclusive amount at a known rate. Tax is the remainder."""
    base = base_from_inclusive(inclusive_paise, rate)
    return TaxSplit(rate=rate, base_paise=base, gst_paise=inclusive_paise - base)


def split_line(inclusive_paise: int, qty: int, slab: Slab) -> TaxSplit:
    """Split a line, choosing the slab from its per-piece GST-exclusive price.

    `qty` matters because the threshold is per piece: two ₹2,000 shirts on one
    line are two 5% pieces, not one 18% line.
    """
    if qty <= 0:  # pragma: no cover - the model's CHECK refuses this first
        raise ValueError("a line must carry a positive quantity to be priced")
    per_piece = Decimal(inclusive_paise) / qty
    base_at_low = int(
        (per_piece * _HUNDRED / (_HUNDRED + slab.rate_below)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )
    rate = slab.rate_for_base(base_at_low)
    return split_inclusive(inclusive_paise, rate)
