"""Location-aware inward posting (money path, issue #47).

Inward posting books stock + value GL under the GRN's *receiving* location, not a
single hardcoded warehouse:

  * a branded PT linked to a **store** GRN posts at that store, under the store's own
    GSTIN, with a per-store gap-free PT number; the value voucher balances; on-hand
    lands at the store;
  * a non-branded PT at a **second warehouse** (not RAN-WH) posts under that
    warehouse's GSTIN and series;
  * reversal mirrors the original posting's store / GSTIN / series;
  * a legacy grn-less upload keeps posting at RAN-WH (back-compat);
  * from-GRN authoring is allowed at any warehouse, blocked at a store.
"""

from __future__ import annotations

from datetime import date

import pytest
from _creds import TEST_PASSWORD
from rest_framework.test import APIClient

from accounts.models import Role, User
from core.documents import VoucherSeries
from core.gl import GLEntry
from inbound.models import Grn, GrnLine
from masters.models import Gstin, LegalEntity, Store
from ptmapper.models import PtFile, PtRow
from stockledger.models import StockLedgerEntry, StockOnHand
from stockledger.posting import financial_year, post_pt_inward, reverse_pt_inward

# ---------------------------------------------------------------- fixtures


@pytest.fixture
def world(db):
    """Two distinct persons: a Jharkhand warehouse GSTIN and a Bihar store GSTIN, so a
    branded store posting proves the GSTIN follows the store (not the old RAN-WH)."""
    entity = LegalEntity.objects.create(code="kdps", name="KDPS")
    jh = Gstin.objects.create(
        legal_entity=entity, gstin="20ABCDE1234F1Z1", state_code="20", state_name="Jharkhand"
    )
    br = Gstin.objects.create(
        legal_entity=entity, gstin="10ABCDE1234F1Z5", state_code="10", state_name="Bihar"
    )
    ran = Store.objects.create(
        code="RAN-WH", name="Ranchi WH", store_type=Store.StoreType.WAREHOUSE, gstin=jh
    )
    pat = Store.objects.create(
        code="PAT-WH", name="Patna WH", store_type=Store.StoreType.WAREHOUSE, gstin=jh
    )
    deo = Store.objects.create(
        code="DEO-01", name="Deoghar", store_type=Store.StoreType.STORE, gstin=br
    )
    fy = financial_year(date.today())
    for s in (ran, pat, deo):
        VoucherSeries.objects.get_or_create(fy=fy, store_code=s.code, doc_type="GRN")
    return {"ran": ran, "pat": pat, "deo": deo, "jh": jh, "br": br}


def _user() -> User:
    role, _ = Role.objects.get_or_create(code="accounts", defaults={"name": "accounts"})
    user, _ = User.objects.get_or_create(
        username="patna-acct",
        defaults={"role": role, "scope_type": "all", "full_name": "Patna Accounts"},
    )
    if user.scope_type != "all":
        user.scope_type = "all"
        user.save(update_fields=["scope_type"])
    return user


def _grn(store: Store, kind: str, received_at: str) -> Grn:
    grn = Grn.objects.create(
        store=store,
        received_at=received_at,
        kind=kind,
        is_direct=(kind == Grn.Kind.NON_BRANDED),
        vendor_name_raw="Vend",
        invoice_number="INV-1",
    )
    GrnLine.objects.create(grn=grn, style_code="KURTA-01", size="M", color="Blue", received_qty=4)
    grn.post()
    return grn


def _postable_pt(grn: Grn) -> PtFile:
    """A sent DRAFT PtFile with one fully-valued row, ready for post_pt_inward."""
    pt = PtFile.objects.create(
        original_filename="brand.xlsx",
        grn=grn,
        draft_stage=PtFile.DraftStage.SENT,
        row_count=1,
    )
    PtRow.objects.create(
        pt_file=pt,
        line_no=1,
        data={
            "BARCODE": "BC-1",
            "DESIGN": "KURTA-01",
            "SIZE": "M",
            "COLOR": "BLUE",
            "BRAND": "LOCALWEAR",
            "SEASON": "SS26",
            "MRP": 999,
            "P RATE": 450,
            "QTY": 4,
            "NAG": 4,
        },
        blanks=[],
    )
    return pt


def _gl_balance(doc_number: str) -> int:
    from django.db.models import Sum

    return GLEntry.objects.filter(doc_number=doc_number).aggregate(b=Sum("amount"))["b"] or 0


# ---------------------------------------------------------------- money path


def test_branded_pt_posts_at_store_gstin_and_series(world):
    grn = _grn(world["deo"], Grn.Kind.BRANDED, Grn.ReceivedAt.STORE)
    result = post_pt_inward(_postable_pt(grn), _user(), booking=None)

    number = result["doc_number"]
    assert f"/{world['deo'].code}/PT/" in number  # per-store gap-free PT number

    entries = list(StockLedgerEntry.objects.filter(doc_number=number))
    assert entries
    assert all(e.store_id == world["deo"].id for e in entries)  # stock at the store
    assert all(e.gstin_id == world["br"].id for e in entries)  # under the store's own GSTIN

    # on-hand lands at the store, valued at 4 × ₹450 = ₹1800 (180000 paise)
    soh = StockOnHand.objects.get(store=world["deo"], sku_code="BC-1")
    assert soh.net_qty == 4
    assert soh.net_value_paise == 180000

    # the value voucher balances and books under the store's GSTIN
    assert _gl_balance(number) == 0
    gl = list(GLEntry.objects.filter(doc_number=number))
    assert gl and all(g.store_id == world["deo"].id and g.gstin_id == world["br"].id for g in gl)


def test_non_branded_pt_posts_at_second_warehouse(world):
    grn = _grn(world["pat"], Grn.Kind.NON_BRANDED, Grn.ReceivedAt.WAREHOUSE)
    result = post_pt_inward(_postable_pt(grn), _user(), booking=None)

    number = result["doc_number"]
    assert f"/{world['pat'].code}/PT/" in number  # numbered under PAT-WH, not RAN-WH

    entries = list(StockLedgerEntry.objects.filter(doc_number=number))
    assert entries
    assert all(e.store_id == world["pat"].id for e in entries)
    assert all(e.gstin_id == world["jh"].id for e in entries)
    assert StockOnHand.objects.get(store=world["pat"], sku_code="BC-1").net_qty == 4


def test_grnless_upload_still_posts_at_ran_wh(world):
    """Legacy back-compat: a PT with no GRN posts at the RAN-WH warehouse."""
    pt = PtFile.objects.create(
        original_filename="legacy.xlsx", draft_stage=PtFile.DraftStage.SENT, row_count=1
    )
    PtRow.objects.create(
        pt_file=pt,
        line_no=1,
        data={"BARCODE": "BC-9", "SIZE": "M", "MRP": 999, "P RATE": 450, "QTY": 1, "NAG": 1},
        blanks=[],
    )
    result = post_pt_inward(pt, _user(), booking=None)
    assert f"/{world['ran'].code}/PT/" in result["doc_number"]
    assert StockOnHand.objects.get(store=world["ran"], sku_code="BC-9").net_qty == 1


def test_reversal_mirrors_original_store_gstin_and_series(world):
    grn = _grn(world["deo"], Grn.Kind.BRANDED, Grn.ReceivedAt.STORE)
    pt = _postable_pt(grn)
    post_pt_inward(pt, _user(), booking=None)

    rev = reverse_pt_inward(pt, _user())
    rev_number = rev["doc_number"]
    assert f"/{world['deo'].code}/PT/" in rev_number  # reversal under the same store series

    reversals = list(StockLedgerEntry.objects.filter(doc_number=rev_number))
    assert reversals
    assert all(e.store_id == world["deo"].id for e in reversals)
    assert all(e.gstin_id == world["br"].id for e in reversals)
    assert all(e.qty < 0 for e in reversals)  # negative mirror

    # the reversal value voucher balances and mirrors under the store's GSTIN
    assert _gl_balance(rev_number) == 0
    assert all(g.store_id == world["deo"].id for g in GLEntry.objects.filter(doc_number=rev_number))

    # net position is flat again at the store
    assert StockOnHand.objects.get(store=world["deo"], sku_code="BC-1").net_qty == 0


# ---------------------------------------------------------------- from-grn guard


def _warehouse_client() -> APIClient:
    role, _ = Role.objects.get_or_create(code="warehouse", defaults={"name": "warehouse"})
    user = User.objects.create_user(username="wh-op", password=TEST_PASSWORD, role=role)
    user.scope_type = "all"
    user.save(update_fields=["scope_type"])
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_from_grn_allowed_at_a_second_warehouse(world):
    grn = _grn(world["pat"], Grn.Kind.NON_BRANDED, Grn.ReceivedAt.WAREHOUSE)
    r = _warehouse_client().post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert r.status_code == 201, r.content
    assert r.json()["grn"] == grn.id


def test_from_grn_blocked_at_a_store(world):
    grn = _grn(world["deo"], Grn.Kind.BRANDED, Grn.ReceivedAt.STORE)
    r = _warehouse_client().post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert r.status_code == 409
    assert "warehouse" in r.json()["detail"].lower()
