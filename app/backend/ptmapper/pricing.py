"""Deterministic pricing for authored (invoice-source) PTs — D2 Q7, pure functions.

The formula (locked in the D2 design; the exact order is to be confirmed against
one worked KDPS example before go-live — flagged open item):

    P RATE = BASIC = rate            (the ex-GST payable per unit, Q36 — never derived)
    landed = rate × (1 + 1.1%)       (Q7 transport loading, a constant of the business)
    base   = landed × (1 + margin%)  (margin from the category master, band-validated)
    GST slab = the slab the GST-**exclusive** per-piece price (``base``) lands in
               (CONTEXT.md: "5% ≤ ₹2,500/piece, 18% above; GST-exclusive, on
               post-discount per-piece price"). ≤ threshold ⇒ 5%, else 18%.
    MRP    = base grossed up with that slab, whole rupees
    OUTPUT TAX = that slab (decided on the ex-GST base, never the grossed-up MRP)
    INPUT TAX  = the slab the ex-GST purchase rate lands in (may differ near the boundary)
    MARGIN     = (MRP − P RATE) / MRP × 100   (derived, never hand-entered)

Every number is a Decimal in; the caller converts for the JSON row cells. GST
slab values arrive as data (``masters.GstSlab``, date-effective — Rule 12), never
constants here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

#: Q7 — freight/transport loading on the purchase rate, in percent.
TRANSPORT_PCT = Decimal("1.1")

_HUNDRED = Decimal("100")
_RUPEE = Decimal("1")
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Slab:
    """One date-effective apparel GST slab (mirrors ``masters.GstSlab``)."""

    threshold: Decimal  # per-piece boundary in rupees (₹2,500)
    rate_below: Decimal  # percent at or under the threshold (5)
    rate_above: Decimal  # percent above it (18)

    def rate_for(self, value: Decimal) -> Decimal:
        return self.rate_below if value <= self.threshold else self.rate_above


@dataclass(frozen=True)
class PricedRow:
    mrp: Decimal  # whole rupees, GST-inclusive
    input_tax: Decimal  # percent on the purchase rate
    output_tax: Decimal  # percent the final MRP lands in
    margin_pct: Decimal  # (MRP − rate) / MRP × 100, 2dp


def _pct(base: Decimal, pct: Decimal) -> Decimal:
    return base * (_HUNDRED + pct) / _HUNDRED


def price_from_rate(rate: Decimal, margin_pct: Decimal, slab: Slab) -> PricedRow:
    """Price one unit from its purchase rate. Deterministic; raises ``ValueError``
    on a non-positive rate (strict money — no silent ₹0 pricing)."""
    if rate <= 0:
        raise ValueError("rate must be a positive rupee amount")
    landed = _pct(rate, TRANSPORT_PCT)
    base = _pct(landed, margin_pct)
    # The slab is decided on the GST-*exclusive* per-piece price (``base``), not the
    # grossed-up MRP — CONTEXT.md locks it "GST-exclusive, on post-discount per-piece
    # price". Anchoring on ``base`` is unambiguous: no tie-break, and the MRP can never
    # cross the threshold that its own slab was chosen by.
    gst_rate = slab.rate_for(base)
    mrp = _pct(base, gst_rate).quantize(_RUPEE, rounding=ROUND_HALF_UP)
    margin = ((mrp - rate) / mrp * _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)
    return PricedRow(
        mrp=mrp,
        input_tax=slab.rate_for(rate),
        output_tax=gst_rate,
        margin_pct=margin,
    )
