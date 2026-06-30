"""Phase F golden suite — identity & scale.

Covers the P0 hardening:
  * MoneyField refuses float/Decimal on the *_paise columns (no silent truncation);
  * a PT post registers the SKU master + the (barcode, season) cohort with the
    locked per-unit cost, and the cohort's DB CHECK blocks unit_cost > mrp;
  * StockOnHand is materialised inside the post and zeroes on reversal;
  * the PT reader flags (never silently swallows) a row-cap truncation;
  * the books-health endpoint reports a balanced trial balance;
  * master-data writes are steward-gated (others get 403).
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from accounts.models import Role, User
from masters.models import Brand, Cohort, Gstin, LegalEntity, Season, Sku, Store
from ptmapper import engine
from ptmapper.models import PtFile, PtRow
from stockledger.models import StockOnHand
from stockledger.posting import post_pt_inward, reverse_pt_inward
from vendors.models import Booking, BookingLine, Vendor


@pytest.fixture
def world(db):
    entity = LegalEntity.objects.create(code="kdps", name="KDPS")
    gstin = Gstin.objects.create(
        legal_entity=entity, gstin="10ABCDE1234F1Z5", state_code="10", state_name="Bihar"
    )
    wh = Store.objects.create(
        code="RAN-WH", name="Ranchi WH", store_type=Store.StoreType.WAREHOUSE, gstin=gstin
    )
    season = Season.objects.create(code="SS26", name="SS26")
    owned = Brand.objects.create(
        code="mufti",
        name="Mufti",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    vendor = Vendor.objects.create(code="v1", name="V1")
    return {
        "entity": entity,
        "gstin": gstin,
        "wh": wh,
        "season": season,
        "owned": owned,
        "vendor": vendor,
    }


def _booking(world):
    return Booking.objects.create(
        number="BK-F-1",
        vendor=world["vendor"],
        brand=world["owned"],
        season=world["season"],
        status=Booking.Status.BOOKED,
        ownership=world["owned"].ownership,
        return_terms=world["owned"].return_terms,
    )


def _pt(*, qty="3", prate="100", mrp="200", barcode="B1", season="SS26"):
    pt = PtFile.objects.create(
        original_filename="t.xlsx", draft_stage=PtFile.DraftStage.SENT, row_count=1
    )
    PtRow.objects.create(
        pt_file=pt,
        line_no=1,
        data={
            "BARCODE": barcode,
            "DESIGN": "D1",
            "SIZE": "M",
            "COLOR": "RED",
            "BRAND": "Mufti",
            "SEASON": season,
            "ITEM": "SHIRT",
            "HSN": "6105",
            "P RATE": prate,
            "BASIC": "80",
            "MRP": mrp,
            "QTY": qty,
            "NAG": qty,
        },
    )
    return pt


def _user(role_code: str, scope: str = "all") -> User:
    role = Role.objects.create(code=role_code, name=role_code.title())
    return User.objects.create(username=f"u_{role_code}", role=role, scope_type=scope)


# --- MoneyField -----------------------------------------------------------


def test_moneyfield_rejects_float_on_paise_column(world):
    booking = _booking(world)
    with pytest.raises(TypeError):
        BookingLine.objects.create(booking=booking, style_code="x", booked_qty=1, mrp_paise=19.99)


# --- SKU + cohort identity -----------------------------------------------


def test_post_registers_sku_and_cohort_with_locked_cost(world):
    post_pt_inward(_pt(qty="3", prate="100", mrp="200"), None, booking=_booking(world))

    sku = Sku.objects.get(barcode="B1")
    assert sku.brand == "Mufti" and sku.mrp_paise == 20000 and sku.first_doc_number

    cohort = Cohort.objects.get(barcode="B1", season="SS26")
    assert cohort.unit_cost_paise == 10000  # P RATE 100 → paise
    assert cohort.mrp_paise == 20000 and cohort.sku_id == sku.id


def test_cohort_db_check_blocks_cost_over_mrp(world):
    sku = Sku.objects.create(barcode="BX")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Cohort.objects.create(
                sku=sku,
                barcode="BX",
                season="SS26",
                unit_cost_paise=30000,
                mrp_paise=20000,
            )


# --- Materialised stock-on-hand ------------------------------------------


def test_stock_on_hand_materialises_and_zeroes_on_reversal(world):
    pt = _pt(qty="3", prate="100", mrp="200")
    post_pt_inward(pt, None, booking=_booking(world))

    oh = StockOnHand.objects.get(store=world["wh"], sku_code="B1")
    assert oh.net_qty == 3 and oh.net_value_paise == 30000

    reverse_pt_inward(pt, None)
    oh.refresh_from_db()
    assert oh.net_qty == 0 and oh.net_value_paise == 0


# --- PT reader truncation (no longer silent) ------------------------------


def test_pt_reader_flags_row_cap_truncation(db, monkeypatch):
    monkeypatch.setattr(engine, "MAX_ROWS", 2)
    body = b"BARCODE,DESIGN,QTY,MRP\n" + b"\n".join(f"B{i},D,1,100".encode() for i in range(5))
    result = engine.run_mapping(body, "big.csv", "text/csv")
    assert result["meta"]["truncated"] is True
    assert result["meta"]["row_limit"] == 2


def test_pt_reader_not_truncated_for_small_file(db, monkeypatch):
    monkeypatch.setattr(engine, "MAX_ROWS", 8000)
    body = b"BARCODE,DESIGN,QTY,MRP\nB1,D,1,100\nB2,D,2,150\n"
    result = engine.run_mapping(body, "small.csv", "text/csv")
    assert result["meta"]["truncated"] is False


# --- Books-health (trial balance) ----------------------------------------


def test_books_health_reports_balanced_books_after_post(world):
    post_pt_inward(_pt(), None, booking=_booking(world))
    client = APIClient()
    client.force_authenticate(_user("owner"))
    r = client.get("/api/finledger/health")
    assert r.status_code == 200
    assert r.data["balanced"] is True
    assert r.data["trial_balance_paise"] == 0
    assert r.data["assets_paise"] == 30000  # Dr INVENTORY 300.00


def test_books_health_is_finance_gated(world):
    client = APIClient()
    client.force_authenticate(_user("warehouse"))
    assert client.get("/api/finledger/health").status_code == 403


# --- Master-data stewardship gate ----------------------------------------


def test_master_steward_can_create_store_others_cannot(world):
    payload = {
        "code": "NEW",
        "name": "New Store",
        "store_type": "store",
        "gstin": world["gstin"].id,
        "city": "Patna",
        "is_active": True,
    }
    steward = APIClient()
    steward.force_authenticate(_user("data_steward"))
    r = steward.post("/api/masters/stores", payload, format="json")
    assert r.status_code == 201, r.data
    assert Store.objects.filter(code="NEW").exists()

    other = APIClient()
    other.force_authenticate(_user("store_staff"))
    r2 = other.post("/api/masters/stores", {**payload, "code": "NEW2"}, format="json")
    assert r2.status_code == 403
