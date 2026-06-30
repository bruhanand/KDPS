"""Phase E golden suite — the money slice posts correctly by commercial model.

Exercises the rebuilt `post_pt_inward` / `reverse_pt_inward` directly against the DB:
  * KDPS-owned (Outright/Correction) → raises a vendor payable + Dr INVENTORY/Cr PAYABLE;
  * brand-owned (SOR/Consignment)    → NO payable, off-book Dr SOR_STOCK/Cr SOR_CONTRA;
  * stock is valued at **P RATE** (not the ex-GST BASIC);
  * P RATE > MRP blocks the post (nothing written);
  * the value GL always ties to zero (trial balance), and a reversal unwinds it.
"""

from __future__ import annotations

import pytest

from core.gl import GLAccount, account_balance, trial_balance
from finledger.models import VendorLedgerEntry
from masters.models import Brand, Gstin, LegalEntity, Season, Store
from ptmapper.models import PtFile, PtRow
from stockledger.models import StockLedgerEntry
from stockledger.posting import PtPostingError, post_pt_inward, reverse_pt_inward
from vendors.models import Booking, Vendor


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
    owned_brand = Brand.objects.create(
        code="mufti",
        name="Mufti",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    sor_brand = Brand.objects.create(
        code="lp",
        name="Louis Philippe",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    vendor = Vendor.objects.create(code="v-abfrl", name="ABFRL")
    return {
        "wh": wh,
        "season": season,
        "owned": owned_brand,
        "sor": sor_brand,
        "vendor": vendor,
    }


def _booking(world, brand, *, number):
    return Booking.objects.create(
        number=number,
        vendor=world["vendor"],
        brand=brand,
        season=world["season"],
        status=Booking.Status.BOOKED,
        ownership=brand.ownership,
        return_terms=brand.return_terms,
    )


def _pt_with_row(*, prate="100", basic="80", mrp="200", qty="2", design="STYLE1", size="M"):
    pt = PtFile.objects.create(
        original_filename="test.xlsx", draft_stage=PtFile.DraftStage.SENT, row_count=1
    )
    PtRow.objects.create(
        pt_file=pt,
        line_no=1,
        data={
            "BARCODE": "B1",
            "DESIGN": design,
            "SIZE": size,
            "BRAND": "X",
            "SEASON": "SS26",
            "P RATE": prate,
            "BASIC": basic,
            "MRP": mrp,
            "QTY": qty,
            "NAG": qty,
        },
    )
    return pt


def test_owned_brand_raises_payable_with_balanced_inventory_gl(world):
    booking = _booking(world, world["owned"], number="BK-OWNED-1")
    pt = _pt_with_row(prate="100", mrp="200", qty="2")

    result = post_pt_inward(pt, None, booking=booking)

    assert result["commercial_model"] == "Outright"
    assert result["vendor_bill"] is not None
    # one vendor payable (bill), +ve amount, equal to stock value
    bill = VendorLedgerEntry.objects.get(kind=VendorLedgerEntry.Kind.BILL, pt_file=pt)
    assert bill.amount == 20000 == result["stock_value_paise"]
    # balanced value voucher: Dr INVENTORY / Cr VENDOR_PAYABLE, and the books tie
    assert account_balance(GLAccount.INVENTORY) == 20000
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -20000
    assert account_balance(GLAccount.SOR_STOCK) == 0
    assert trial_balance() == 0


def test_brand_owned_sor_raises_no_payable_and_posts_off_book(world):
    booking = _booking(world, world["sor"], number="BK-SOR-1")
    pt = _pt_with_row(prate="150", mrp="500", qty="4")

    result = post_pt_inward(pt, None, booking=booking)

    assert result["commercial_model"] == "SOR"
    assert result["vendor_bill"] is None
    assert not VendorLedgerEntry.objects.filter(pt_file=pt).exists()
    # off-book memo only — never a payable, never on-book inventory
    assert account_balance(GLAccount.SOR_STOCK) == 60000
    assert account_balance(GLAccount.SOR_CONTRA) == -60000
    assert account_balance(GLAccount.VENDOR_PAYABLE) == 0
    assert account_balance(GLAccount.INVENTORY) == 0
    assert trial_balance() == 0


def test_stock_is_valued_at_p_rate_not_basic(world):
    booking = _booking(world, world["owned"], number="BK-OWNED-2")
    pt = _pt_with_row(prate="100", basic="80", mrp="200", qty="2")

    post_pt_inward(pt, None, booking=booking)

    entry = StockLedgerEntry.objects.get(pt_file=pt, kind=StockLedgerEntry.Kind.PT_INWARD)
    # P RATE (100) × qty (2) = ₹200 = 20000 paise — NOT the ex-GST BASIC (80 → 16000)
    assert entry.amount == 20000
    assert entry.qty == 2


def test_p_rate_above_mrp_blocks_the_post(world):
    booking = _booking(world, world["owned"], number="BK-OWNED-3")
    pt = _pt_with_row(prate="300", mrp="200", qty="1")

    with pytest.raises(PtPostingError):
        post_pt_inward(pt, None, booking=booking)

    # all-or-none: nothing landed in any book
    assert StockLedgerEntry.objects.filter(pt_file=pt).count() == 0
    assert trial_balance() == 0
    assert not VendorLedgerEntry.objects.filter(pt_file=pt).exists()


def test_reversal_unwinds_stock_payable_and_value_gl(world):
    booking = _booking(world, world["owned"], number="BK-OWNED-4")
    pt = _pt_with_row(prate="100", mrp="200", qty="2")
    post_pt_inward(pt, None, booking=booking)

    rev = reverse_pt_inward(pt, None)

    assert rev["vendor_reversed"] == 1
    # stock nets to zero (inward + negative mirror); value GL nets to zero
    assert sum(e.amount for e in StockLedgerEntry.objects.filter(pt_file=pt)) == 0
    assert account_balance(GLAccount.INVENTORY) == 0
    assert account_balance(GLAccount.VENDOR_PAYABLE) == 0
    assert trial_balance() == 0
    # vendor ledger: a bill and its reversal both present (append-only)
    assert (
        VendorLedgerEntry.objects.filter(pt_file=pt, kind=VendorLedgerEntry.Kind.BILL).count() == 1
    )
    assert (
        VendorLedgerEntry.objects.filter(pt_file=pt, kind=VendorLedgerEntry.Kind.REVERSAL).count()
        == 1
    )
