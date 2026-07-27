"""Phase E golden suite — the money slice posts correctly by commercial model.

Exercises the rebuilt `post_pt_inward` / `reverse_pt_inward` directly against the DB:
  * KDPS-owned (Outright/Correction) → raises a vendor payable + Dr INVENTORY/Cr PAYABLE;
  * brand-owned (SOR/Consignment)    → NO payable, off-book Dr SOR_STOCK/Cr SOR_CONTRA;
  * stock is valued at **P RATE** (not the ex-GST BASIC);
  * P RATE > MRP blocks the post (nothing written);
  * an unreadable NAG/QTY blocks the post too - the same strict-money rule on the
    quantity axis - while a blank/zero quantity is skipped and *counted*;
  * the value GL always ties to zero (trial balance), and a reversal unwinds it.
"""

from __future__ import annotations

import pytest

from accounts.models import Role, User
from core.gl import GLAccount, account_balance, trial_balance
from finledger.models import VendorLedgerEntry
from masters.models import Brand, Gstin, LegalEntity, Season, Store
from ptmapper.models import PtFile, PtRow
from stockledger.models import StockLedgerEntry, StockOnHand
from stockledger.posting import PtPostingError, post_pt_inward, reverse_pt_inward
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
    accounts_role = Role.objects.create(code="accounts", name="Accounts")
    actor = User.objects.create(
        username="phase-e-head-office",
        full_name="Phase E Head Office",
        scope_type="all",
        role=accounts_role,
    )
    return {
        "wh": wh,
        "season": season,
        "owned": owned_brand,
        "sor": sor_brand,
        "vendor": vendor,
        "actor": actor,
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


def _pt_with_rows(*rows: dict):
    """A sent PT file whose rows are the given overrides on top of a valued row."""
    pt = PtFile.objects.create(
        original_filename="test.xlsx", draft_stage=PtFile.DraftStage.SENT, row_count=len(rows)
    )
    for line_no, overrides in enumerate(rows, start=1):
        data = {
            "BARCODE": f"B{line_no}",
            "DESIGN": f"STYLE{line_no}",
            "SIZE": "M",
            "BRAND": "X",
            "SEASON": "SS26",
            "P RATE": "100",
            "BASIC": "80",
            "MRP": "200",
            "QTY": "2",
            "NAG": "2",
        }
        data.update(overrides)
        PtRow.objects.create(pt_file=pt, line_no=line_no, data=data)
    return pt


def test_owned_brand_raises_payable_with_balanced_inventory_gl(world):
    booking = _booking(world, world["owned"], number="BK-OWNED-1")
    pt = _pt_with_row(prate="100", mrp="200", qty="2")

    result = post_pt_inward(pt, world["actor"], booking=booking)

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

    result = post_pt_inward(pt, world["actor"], booking=booking)

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

    post_pt_inward(pt, world["actor"], booking=booking)

    entry = StockLedgerEntry.objects.get(pt_file=pt, kind=StockLedgerEntry.Kind.PT_INWARD)
    # P RATE (100) × qty (2) = ₹200 = 20000 paise — NOT the ex-GST BASIC (80 → 16000)
    assert entry.amount == 20000
    assert entry.qty == 2


def test_p_rate_above_mrp_blocks_the_post(world):
    booking = _booking(world, world["owned"], number="BK-OWNED-3")
    pt = _pt_with_row(prate="300", mrp="200", qty="1")

    with pytest.raises(PtPostingError):
        post_pt_inward(pt, world["actor"], booking=booking)

    # all-or-none: nothing landed in any book
    assert StockLedgerEntry.objects.filter(pt_file=pt).count() == 0
    assert trial_balance() == 0
    assert not VendorLedgerEntry.objects.filter(pt_file=pt).exists()


def test_unreadable_quantity_blocks_the_post(world):
    """A NAG cell that exists but cannot be read is a quantity defect - it blocks the
    whole post exactly like an unreadable cost, instead of silently becoming qty 0."""
    booking = _booking(world, world["owned"], number="BK-QTY-1")
    pt = _pt_with_rows({"NAG": "2", "QTY": "2"}, {"NAG": "2 pcs", "QTY": "2 pcs"})

    with pytest.raises(PtPostingError) as caught:
        post_pt_inward(pt, world["actor"], booking=booking)

    assert "row 2" in str(caught.value)
    # all-or-none: the good row didn't land either
    assert StockLedgerEntry.objects.filter(pt_file=pt).count() == 0
    assert trial_balance() == 0
    assert not VendorLedgerEntry.objects.filter(pt_file=pt).exists()


def test_blank_or_zero_quantity_rows_are_skipped_and_counted(world):
    """Filler/summary rows carry no quantity - still skipped, but the post says how
    many, so the drop is visible at the point of posting instead of invisible."""
    booking = _booking(world, world["owned"], number="BK-QTY-2")
    pt = _pt_with_rows(
        {"NAG": "2", "QTY": "2"},
        {"NAG": "", "QTY": ""},
        {"NAG": "0", "QTY": "0"},
    )

    result = post_pt_inward(pt, world["actor"], booking=booking)

    assert result["entries"] == 1
    assert result["skipped_rows"] == 2
    assert StockLedgerEntry.objects.filter(pt_file=pt).count() == 1
    assert trial_balance() == 0


def test_thousands_separated_quantity_still_parses(world):
    """`1,000` is a formatted number, not garbage - it must not block the post."""
    booking = _booking(world, world["owned"], number="BK-QTY-3")
    pt = _pt_with_rows({"NAG": "1,000", "QTY": "1,000"})

    result = post_pt_inward(pt, world["actor"], booking=booking)

    assert result["skipped_rows"] == 0
    assert StockLedgerEntry.objects.get(pt_file=pt).qty == 1000


def test_unreadable_nag_falls_back_to_a_readable_qty(world):
    """The NAG → QTY fallback survives: only a row with no readable quantity at all
    blocks, so a junk NAG artifact beside a clean QTY still posts the right count."""
    booking = _booking(world, world["owned"], number="BK-QTY-4")
    pt = _pt_with_rows({"NAG": "2 pcs", "QTY": "3"})

    result = post_pt_inward(pt, world["actor"], booking=booking)

    assert result["skipped_rows"] == 0
    assert StockLedgerEntry.objects.get(pt_file=pt).qty == 3


def test_negative_quantity_blocks_the_post(world):
    """A PT brings goods in - a negative inward quantity is a data defect, not a
    filler row, so it must not be quietly counted among the skipped."""
    booking = _booking(world, world["owned"], number="BK-QTY-5")
    pt = _pt_with_rows({"NAG": "-3", "QTY": "-3"})

    with pytest.raises(PtPostingError) as caught:
        post_pt_inward(pt, world["actor"], booking=booking)

    assert "row 1" in str(caught.value)
    assert StockLedgerEntry.objects.filter(pt_file=pt).count() == 0
    assert trial_balance() == 0


def test_non_finite_mrp_is_refused_not_crashed(world):
    """`inf` parses into a Decimal and slips past `cost > mrp`, then poisons the paise
    conversion. It has to be refused as a bad price cell, like any other garbage."""
    booking = _booking(world, world["owned"], number="BK-QTY-6")
    pt = _pt_with_rows({"MRP": "inf"})

    with pytest.raises(PtPostingError):
        post_pt_inward(pt, world["actor"], booking=booking)

    assert StockLedgerEntry.objects.filter(pt_file=pt).count() == 0
    assert trial_balance() == 0


def test_booking_is_reconciled_from_the_ledger_and_unwound_on_reversal(world):
    """Reconciliation follows the stock rows, not a re-read of the PT file, so the
    reversal un-bumps exactly what the post bumped even with a filler row present."""
    booking = _booking(world, world["owned"], number="BK-QTY-7")
    line = BookingLine.objects.create(booking=booking, style_code="STYLE1", size="M", booked_qty=10)
    pt = _pt_with_rows(
        {"DESIGN": "STYLE1", "SIZE": "M", "NAG": "2", "QTY": "2"},
        {"DESIGN": "STYLE1", "SIZE": "M", "NAG": "", "QTY": ""},
    )

    result = post_pt_inward(pt, world["actor"], booking=booking)
    line.refresh_from_db()
    assert result["reconciled_lines"] == 1
    assert result["skipped_rows"] == 1
    assert line.inwarded_qty == 2

    reverse_pt_inward(pt, world["actor"])
    line.refresh_from_db()
    assert line.inwarded_qty == 0


def test_reversal_unwinds_stock_payable_and_value_gl(world):
    booking = _booking(world, world["owned"], number="BK-OWNED-4")
    pt = _pt_with_row(prate="100", mrp="200", qty="2")
    post_pt_inward(pt, world["actor"], booking=booking)

    rev = reverse_pt_inward(pt, world["actor"])

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


def test_stock_on_hand_projection_reflects_inward(world):
    booking = _booking(world, world["owned"], number="BK-OH-1")
    pt = _pt_with_row(prate="100", mrp="200", qty="2")
    post_pt_inward(pt, world["actor"], booking=booking)

    soh = StockOnHand.objects.get(sku_code="B1")
    assert soh.net_qty == 2
    assert soh.net_value_paise == 20000  # P RATE 100 × qty 2
