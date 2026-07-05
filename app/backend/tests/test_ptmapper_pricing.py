"""Deterministic non-brand pricing (D2 Q7) — golden files for the pure formula
and the source-gated "Price blank rows" endpoint.

Formula under test (open item: order to be confirmed against one worked KDPS
example before go-live):
    landed = rate × 1.011 ; base = landed × (1+margin)
    MRP = base grossed up with GST, low slab first (≤ ₹2,500 ⇒ 5%, else 18%),
    whole rupees; INPUT TAX follows the purchase rate; MARGIN = (MRP−rate)/MRP.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from _creds import TEST_PASSWORD
from rest_framework.test import APIClient

from accounts.models import Role, User
from masters.models import CategoryMargin, GstSlab
from ptmapper.models import ControlledValue, PtFile, PtRow
from ptmapper.pricing import Slab, price_from_rate

SLAB = Slab(threshold=Decimal(2500), rate_below=Decimal(5), rate_above=Decimal(18))


# ---------------------------------------------------------------- pure golden files


def test_low_slab_price():
    # 500 → landed 505.50 → base 672.315 → ×1.05 = 705.93 ≤ 2500 ⇒ 5%
    row = price_from_rate(Decimal(500), Decimal(33), SLAB)
    assert row.mrp == Decimal(706)
    assert row.output_tax == Decimal(5)
    assert row.input_tax == Decimal(5)
    assert row.margin_pct == Decimal("29.18")  # (706-500)/706


def test_high_slab_price():
    # 2000 → landed 2022 → base 2689.26 → ×1.05 = 2823.72 > 2500 ⇒ 18% ⇒ 3173.33
    row = price_from_rate(Decimal(2000), Decimal(33), SLAB)
    assert row.mrp == Decimal(3173)
    assert row.output_tax == Decimal(18)
    assert row.input_tax == Decimal(5)  # the purchase rate itself is ≤ 2500


def test_boundary_band_prefers_the_low_slab():
    # 1700 → landed 1718.70 → base 2285.87 → ×1.05 = 2400.16 ≤ 2500 ⇒ 5% stands
    # (×1.18 = 2697.33 would also be self-consistent — the tie-break is the
    # lower customer price)
    row = price_from_rate(Decimal(1700), Decimal(33), SLAB)
    assert row.mrp == Decimal(2400)
    assert row.output_tax == Decimal(5)


def test_input_tax_follows_the_purchase_rate():
    row = price_from_rate(Decimal(3000), Decimal(33), SLAB)
    assert row.input_tax == Decimal(18)
    assert row.output_tax == Decimal(18)


def test_exact_threshold_rate_is_low_slab():
    row = price_from_rate(Decimal(2500), Decimal(33), SLAB)
    assert row.input_tax == Decimal(5)  # ≤ threshold, not <


def test_non_positive_rate_is_refused():
    with pytest.raises(ValueError):
        price_from_rate(Decimal(0), Decimal(33), SLAB)


# ---------------------------------------------------------------- the endpoint


@pytest.fixture
def client(db):
    role, _ = Role.objects.get_or_create(code="warehouse", defaults={"name": "warehouse"})
    user = User.objects.create_user(username="pricer", password=TEST_PASSWORD, role=role)
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def pricing_world(db):
    GstSlab.objects.create(
        name="Apparel (GST 2.0)",
        threshold_paise=250000,
        rate_below=5,
        rate_above=18,
        effective_from=date(2025, 9, 22),
    )
    # the data migration seeds the global row; make the test self-sufficient anyway
    CategoryMargin.objects.get_or_create(
        item="", defaults={"margin_pct": 33, "band_min_pct": 30, "band_max_pct": 35}
    )
    CategoryMargin.objects.create(item="SAREE", margin_pct=40, band_min_pct=38, band_max_pct=45)
    ControlledValue.objects.get_or_create(dimension="gst", value="5")
    ControlledValue.objects.get_or_create(dimension="gst", value="18")


def _authored_pt(rows: list[dict]) -> PtFile:
    pt = PtFile.objects.create(
        original_filename="authored.pdf", source=PtFile.Source.INVOICE, row_count=len(rows)
    )
    for i, data in enumerate(rows, start=1):
        PtRow.objects.create(pt_file=pt, line_no=i, data=data, blanks=[])
    return pt


def test_price_endpoint_fills_blank_mrp_rows_only(client, pricing_world):
    pt = _authored_pt(
        [
            {"DESIGN": "A", "P RATE": 500, "MRP": "", "ITEM": ""},
            {"DESIGN": "B", "P RATE": 500, "MRP": 999, "ITEM": ""},  # already priced
            {"DESIGN": "C", "P RATE": "", "MRP": "", "ITEM": ""},  # no rate → skipped
            {"DESIGN": "D", "P RATE": 500, "MRP": "", "ITEM": "SAREE"},  # category margin
        ]
    )
    r = client.post(f"/api/ptmapper/files/{pt.id}/price", {}, format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["price_result"]["priced"] == 2
    assert body["price_result"]["skipped"] == [{"line_no": 3, "reason": "no purchase rate"}]
    rows = {row["line_no"]: row for row in body["rows"]}
    assert rows[1]["data"]["MRP"] == 706  # default 33%
    assert rows[1]["data"]["OUTPUT TAX"] == 5
    assert rows[1]["provenance"]["MRP"] == "derived"
    assert rows[2]["data"]["MRP"] == 999  # untouched
    assert rows[4]["data"]["MRP"] == 743  # SAREE 40%: 505.5×1.40×1.05 = 743.08 → 743


def test_price_override_is_band_validated(client, pricing_world):
    pt = _authored_pt([{"DESIGN": "A", "P RATE": 500, "MRP": "", "ITEM": ""}])
    bad = client.post(f"/api/ptmapper/files/{pt.id}/price", {"margin_pct": 50}, format="json")
    assert bad.status_code == 400
    assert "outside" in bad.json()["detail"]
    # nothing was written
    assert PtRow.objects.get(pt_file=pt).data["MRP"] == ""

    ok = client.post(f"/api/ptmapper/files/{pt.id}/price", {"margin_pct": 35}, format="json")
    assert ok.status_code == 200
    assert PtRow.objects.get(pt_file=pt).data["MRP"] == 717  # 505.5×1.35×1.05 = 716.55 → 717


def test_price_is_source_gated(client, pricing_world):
    pt = PtFile.objects.create(original_filename="brand.xlsx", row_count=1)
    PtRow.objects.create(pt_file=pt, line_no=1, data={"P RATE": 500, "MRP": ""}, blanks=[])
    r = client.post(f"/api/ptmapper/files/{pt.id}/price", {}, format="json")
    assert r.status_code == 409


def test_price_needs_an_effective_slab(client, db):
    CategoryMargin.objects.get_or_create(
        item="", defaults={"margin_pct": 33, "band_min_pct": 30, "band_max_pct": 35}
    )
    pt = _authored_pt([{"DESIGN": "A", "P RATE": 500, "MRP": ""}])
    r = client.post(f"/api/ptmapper/files/{pt.id}/price", {}, format="json")
    assert r.status_code == 422
