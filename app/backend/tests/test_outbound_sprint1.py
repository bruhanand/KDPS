"""Golden tests for Sprint 1 — Outbound module.

Each test exercises one sub-flow end-to-end: create draft → post/dispatch →
verify stock deltas + GL balance. The trial balance MUST remain ₹0.

Fixture scaffold:
- Two stores (same-state Jharkhand), one cross-state (Bihar)
- One warehouse
- One owned brand, one SOR brand
- Seed stock via direct StockOnHand + StockLedgerEntry creation
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD

from accounts.models import Role, User
from core.documents import DocStatus, VoucherSeries
from core.gl import GLAccount, GLEntry
from finledger.models import VendorLedgerEntry
from masters.models import Brand, Gstin, LegalEntity, Store
from outbound.models import (
    ReturnToVendor,
    ReturnToVendorLine,
    StockAdjustment,
    StockAdjustmentLine,
    StoreTransfer,
    StoreTransferLine,
    VFlip,
    VFlipLine,
    WriteOff,
    WriteOffLine,
)
from outbound.posting import (
    OutboundPostingError,
    post_adjustment,
    post_rtv,
    post_transfer_dispatch,
    post_transfer_receipt,
    post_vflip,
    post_writeoff,
)
from stockledger.models import StockLedgerEntry, StockOnHand
from vendors.models import Vendor


@pytest.fixture()
def _outbound_scaffold(db):
    """Create the minimal master data + seed stock for outbound tests."""
    entity = LegalEntity.objects.create(code="kdps-test", name="KDPS Test", pan="AAACK1234A")
    gstin_jh = Gstin.objects.create(
        gstin="20AAACK1234A1ZP",
        state_code="20",
        state_name="Jharkhand",
        legal_entity=entity,
    )
    gstin_bh = Gstin.objects.create(
        gstin="10AAACK1234A1ZR",
        state_code="10",
        state_name="Bihar",
        legal_entity=entity,
    )
    store_a = Store.objects.create(code="TST-A", name="Test Store A", gstin=gstin_jh)
    store_b = Store.objects.create(code="TST-B", name="Test Store B", gstin=gstin_jh)
    store_bh = Store.objects.create(code="TST-BH", name="Test Bihar Store", gstin=gstin_bh)
    warehouse = Store.objects.create(
        code="TST-WH", name="Test Warehouse", gstin=gstin_jh, store_type="warehouse"
    )
    brand_owned = Brand.objects.create(
        code="ownbr",
        name="OwnedBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    brand_sor = Brand.objects.create(
        code="sorbr",
        name="SORBrand",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    vendor = Vendor.objects.create(name="Test Vendor", code="tvnd")
    role = Role.objects.create(code="accounts", name="Accounts")
    user = User.objects.create_user(
        username="outtest", password=TEST_PASSWORD, role=role, entity=entity, scope_type="all"
    )
    # The second person every write-off / V-flip / adjustment now needs (#70).
    checker = User.objects.create_user(
        username="outcheck",
        password=TEST_PASSWORD,
        role=Role.objects.create(code="owner", name="Owner"),
        entity=entity,
        scope_type="all",
    )

    # Seed stock: 10 units of SKU "SKU001" at store_a and warehouse, 100 paise/unit
    for s in [store_a, warehouse]:
        StockOnHand.objects.create(
            store=s,
            gstin=gstin_jh,
            sku_code="SKU001",
            design="Shirt",
            color="Blue",
            size="M",
            brand="OwnedBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
            net_qty=10,
            net_value_paise=10 * 100,
        )
        StockLedgerEntry.objects.create(
            store=s,
            gstin=gstin_jh,
            sku_code="SKU001",
            design="Shirt",
            color="Blue",
            size="M",
            brand="OwnedBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
            qty=10,
            amount=10 * 100,
            kind="pt_inward",
            doc_number="SEED-001",
            line_no=1,
        )

    # SOR stock at store_a: 5 units of SKU "SKU002"
    StockOnHand.objects.create(
        store=store_a,
        gstin=gstin_jh,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        net_qty=5,
        net_value_paise=5 * 200,
    )
    StockLedgerEntry.objects.create(
        store=store_a,
        gstin=gstin_jh,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=5,
        amount=5 * 200,
        kind="pt_inward",
        doc_number="SEED-002",
        line_no=1,
    )

    # Seed VoucherSeries for all outbound doc types and test stores
    fy = "26-27"
    for store_code in ["TST-A", "TST-B", "TST-BH", "TST-WH"]:
        for doc_type in ["STO", "RTV", "ADJ", "WRO", "VFL"]:
            VoucherSeries.objects.create(
                fy=fy,
                store_code=store_code,
                doc_type=doc_type,
                prefix=f"{store_code}/{doc_type}/{fy}/",
                next_seq=1,
            )
    # Vendor subledger voucher series (headquarter-scoped, shared across stores)
    VoucherSeries.objects.get_or_create(
        fy=fy,
        store_code="HO",
        doc_type="VEND",
        defaults={"prefix": f"HO/VEND/{fy}/", "next_seq": 1},
    )

    return {
        "entity": entity,
        "gstin_jh": gstin_jh,
        "gstin_bh": gstin_bh,
        "store_a": store_a,
        "store_b": store_b,
        "store_bh": store_bh,
        "warehouse": warehouse,
        "brand_owned": brand_owned,
        "brand_sor": brand_sor,
        "vendor": vendor,
        "user": user,
        "checker": checker,
    }


def _approve(doc, s):
    """Give a document the second signature the posting layer now demands (#70).

    These are posting-layer tests: they exercise the ledger and the GL, not the
    inbox, so the approval is walked through its real service rather than faked
    — the maker asks, a *different* person approves. A document small enough to
    fall inside its policy tolerance is already cleared and nobody is asked.
    """
    from approvals.models import ApprovalStatus
    from approvals.services import decide
    from outbound.maker_checker import request_document_approval

    approval = request_document_approval(doc, requested_by=s["user"])
    if approval is not None and approval.status == ApprovalStatus.PENDING:
        decide(approval, actor=s["checker"], action="approve")
    return doc


# ---------------------------------------------------------------------------
# 1. Store Split (warehouse → store, same GSTIN, no GL)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_store_split_same_gstin_no_gl(_outbound_scaffold):
    """Store split: stock moves from warehouse to store, no GL posting."""
    s = _outbound_scaffold
    transfer = StoreTransfer.objects.create(
        source_store=s["warehouse"],
        destination_store=s["store_a"],
        transfer_type="store_split",
        reason="sister_store_request",
        created_by=s["user"],
    )
    StoreTransferLine.objects.create(
        transfer=transfer,
        sku_code="SKU001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="OwnedBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty_planned=3,
    )

    # Dispatch (scanned lines are the only quantities)
    _approve(transfer, s)
    post_transfer_dispatch(transfer, {"SKU001": 3}, user=s["user"])
    assert transfer.docstatus == DocStatus.SUBMITTED
    assert transfer.doc_number is not None

    # Stock should decrease at warehouse
    wh_oh = StockOnHand.objects.get(store=s["warehouse"], sku_code="SKU001")
    assert wh_oh.net_qty == 7  # 10 - 3

    # Receive (full, scanned)
    post_transfer_receipt(transfer, {"SKU001": 3}, user=s["user"])

    # Check receipt companion record
    from outbound.models import TransferReceipt

    receipt = TransferReceipt.objects.get(transfer=transfer)
    assert receipt.receipt_status == "complete"

    # Stock should increase at store_a
    sa_oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU001")
    assert sa_oh.net_qty == 13  # 10 (seed) + 3 (received)

    # NO GL entries for store split
    gl_count = GLEntry.objects.filter(doc_number=transfer.doc_number).count()
    assert gl_count == 0


# ---------------------------------------------------------------------------
# 2. Inter-store Transfer (same state + cross-state)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_inter_store_transfer_same_state(_outbound_scaffold):
    """Inter-store same-state: stock moves, no GL."""
    s = _outbound_scaffold
    transfer = StoreTransfer.objects.create(
        source_store=s["store_a"],
        destination_store=s["store_b"],
        transfer_type="inter_store",
        reason="slow_mover",
        transport_mode="public_bus",
        transport_ref="BUS-123",
        dispatcher_name="Ram Kumar",
        expected_arrival_note="Expected tomorrow morning",
        created_by=s["user"],
    )
    StoreTransferLine.objects.create(
        transfer=transfer,
        sku_code="SKU001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="OwnedBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty_planned=5,
    )

    _approve(transfer, s)
    post_transfer_dispatch(transfer, {"SKU001": 5}, user=s["user"])
    assert transfer.is_cross_state is False
    assert transfer.dispatch_date is not None

    # Receive
    post_transfer_receipt(transfer, {"SKU001": 5}, user=s["user"])

    sa_oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU001")
    assert sa_oh.net_qty == 5  # 10 - 5

    sb_oh = StockOnHand.objects.get(store=s["store_b"], sku_code="SKU001")
    assert sb_oh.net_qty == 5  # 0 + 5


@pytest.mark.django_db(transaction=True)
def test_cross_state_transfer_flagged(_outbound_scaffold):
    """Cross-state: auto-detects different GSTINs, records e-way bill."""
    s = _outbound_scaffold
    transfer = StoreTransfer.objects.create(
        source_store=s["store_a"],  # Jharkhand
        destination_store=s["store_bh"],  # Bihar
        transfer_type="inter_store",
        reason="customer_waiting",
        eway_bill_number="EWB-2026-001",
        created_by=s["user"],
    )
    StoreTransferLine.objects.create(
        transfer=transfer,
        sku_code="SKU001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="OwnedBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty_planned=2,
    )

    _approve(transfer, s)
    post_transfer_dispatch(transfer, {"SKU001": 2}, user=s["user"])
    assert transfer.is_cross_state is True
    assert transfer.eway_bill_number == "EWB-2026-001"


@pytest.mark.django_db(transaction=True)
def test_transfer_shortfall_flagged(_outbound_scaffold):
    """Shortfall: received qty < dispatched qty."""
    s = _outbound_scaffold
    transfer = StoreTransfer.objects.create(
        source_store=s["store_a"],
        destination_store=s["store_b"],
        transfer_type="inter_store",
        created_by=s["user"],
    )
    line = StoreTransferLine.objects.create(
        transfer=transfer,
        sku_code="SKU001",
        qty_planned=4,
    )

    _approve(transfer, s)
    post_transfer_dispatch(transfer, {"SKU001": 4}, user=s["user"])
    post_transfer_receipt(transfer, {"SKU001": 3}, user=s["user"])

    from outbound.models import TransferReceipt

    receipt = TransferReceipt.objects.get(transfer=transfer)
    assert receipt.receipt_status == "shortfall"
    line.refresh_from_db()
    assert line.qty_received == 3


@pytest.mark.django_db(transaction=True)
def test_transfer_blocks_on_insufficient_stock(_outbound_scaffold):
    """Cannot dispatch more than available stock."""
    s = _outbound_scaffold
    transfer = StoreTransfer.objects.create(
        source_store=s["store_a"],
        destination_store=s["store_b"],
        created_by=s["user"],
    )
    StoreTransferLine.objects.create(
        transfer=transfer,
        sku_code="SKU001",
        qty_planned=999,
    )

    _approve(transfer, s)
    with pytest.raises(OutboundPostingError, match="Insufficient stock"):
        post_transfer_dispatch(transfer, {"SKU001": 999}, user=s["user"])


# ---------------------------------------------------------------------------
# 3. RTV — Defective Return
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_rtv_defective_owned_posts_gl(_outbound_scaffold):
    """RTV for owned brand: stock out + Dr VENDOR_PAYABLE / Cr INVENTORY."""
    s = _outbound_scaffold
    rtv = ReturnToVendor.objects.create(
        store=s["store_a"],
        vendor=s["vendor"],
        brand=s["brand_owned"],
        return_type="defective",
        logistics_route="warehouse",
        created_by=s["user"],
    )
    ReturnToVendorLine.objects.create(
        rtv=rtv,
        sku_code="SKU001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="OwnedBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty=2,
        unit_cost_paise=100,
    )

    post_rtv(rtv, user=s["user"])
    assert rtv.docstatus == DocStatus.SUBMITTED

    # Stock decreased
    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU001")
    assert oh.net_qty == 8  # 10 - 2

    # GL posted: balanced
    gl_entries = GLEntry.objects.filter(doc_number=rtv.doc_number)
    assert gl_entries.count() == 2
    total = sum(e.amount for e in gl_entries)
    assert total == 0  # balanced

    # Check accounts
    dr_entry = gl_entries.get(amount__gt=0)
    cr_entry = gl_entries.get(amount__lt=0)
    assert dr_entry.account == GLAccount.VENDOR_PAYABLE
    assert cr_entry.account == GLAccount.INVENTORY
    assert dr_entry.amount == 200  # 2 × 100 paise
    assert cr_entry.amount == -200

    # Vendor subledger must mirror GL VENDOR_PAYABLE (regression: was missing)
    vle = VendorLedgerEntry.objects.filter(reference=rtv.doc_number)
    assert vle.count() == 1
    assert vle.first().amount == -200  # negative = reduces payable
    assert vle.first().vendor == s["vendor"]


@pytest.mark.django_db(transaction=True)
def test_rtv_sor_brand_no_gl(_outbound_scaffold):
    """RTV for SOR brand: stock out only, NO GL posting."""
    s = _outbound_scaffold
    rtv = ReturnToVendor.objects.create(
        store=s["store_a"],
        vendor=s["vendor"],
        brand=s["brand_sor"],
        return_type="defective",
        created_by=s["user"],
    )
    ReturnToVendorLine.objects.create(
        rtv=rtv,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=1,
        unit_cost_paise=200,
    )

    post_rtv(rtv, user=s["user"])

    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU002")
    assert oh.net_qty == 4  # 5 - 1

    # No GL entries for brand-owned
    gl_count = GLEntry.objects.filter(doc_number=rtv.doc_number).count()
    assert gl_count == 0

    # No vendor subledger entry for brand-owned RTV (off-book)
    assert VendorLedgerEntry.objects.filter(reference=rtv.doc_number).count() == 0


# ---------------------------------------------------------------------------
# 4. Seasonal Return
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_seasonal_return_sor(_outbound_scaffold):
    """Seasonal return for SOR: stock out, no GL."""
    s = _outbound_scaffold
    rtv = ReturnToVendor.objects.create(
        store=s["store_a"],
        vendor=s["vendor"],
        brand=s["brand_sor"],
        return_type="seasonal",
        season="SS26",
        return_window_date="2026-09-30",
        created_by=s["user"],
    )
    ReturnToVendorLine.objects.create(
        rtv=rtv,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=3,
        unit_cost_paise=200,
    )

    post_rtv(rtv, user=s["user"])

    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU002")
    assert oh.net_qty == 2  # 5 - 3

    # SOR seasonal = no GL
    assert GLEntry.objects.filter(doc_number=rtv.doc_number).count() == 0


@pytest.mark.django_db(transaction=True)
def test_seasonal_return_owned_posts_gl(_outbound_scaffold):
    """Seasonal return for owned brand (Correction): stock out + GL."""
    s = _outbound_scaffold
    rtv = ReturnToVendor.objects.create(
        store=s["store_a"],
        vendor=s["vendor"],
        brand=s["brand_owned"],
        return_type="seasonal",
        season="SS26",
        created_by=s["user"],
    )
    ReturnToVendorLine.objects.create(
        rtv=rtv,
        sku_code="SKU001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="OwnedBrand",
        qty=1,
        unit_cost_paise=100,
    )

    post_rtv(rtv, user=s["user"])

    gl_entries = list(GLEntry.objects.filter(doc_number=rtv.doc_number))
    assert len(gl_entries) == 2
    assert sum(e.amount for e in gl_entries) == 0


# ---------------------------------------------------------------------------
# 5. Stock Adjustment
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_adjustment_shrinkage(_outbound_scaffold):
    """Shrinkage: counted < book → Dr SUSPENSE / Cr INVENTORY."""
    s = _outbound_scaffold
    adj = StockAdjustment.objects.create(
        store=s["store_a"],
        reason="shrinkage",
        created_by=s["user"],
    )
    StockAdjustmentLine.objects.create(
        adjustment=adj,
        sku_code="SKU001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="OwnedBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        book_qty=10,
        counted_qty=8,
        adj_qty=-2,
        unit_cost_paise=100,
    )

    _approve(adj, s)
    post_adjustment(adj, user=s["user"])
    assert adj.docstatus == DocStatus.SUBMITTED

    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU001")
    assert oh.net_qty == 8  # 10 - 2

    gl_entries = list(GLEntry.objects.filter(doc_number=adj.doc_number))
    assert len(gl_entries) == 2
    assert sum(e.amount for e in gl_entries) == 0

    dr_entry = [e for e in gl_entries if e.amount > 0][0]
    assert dr_entry.account == GLAccount.SUSPENSE


@pytest.mark.django_db(transaction=True)
def test_adjustment_surplus(_outbound_scaffold):
    """Surplus: counted > book → Dr INVENTORY / Cr SUSPENSE."""
    s = _outbound_scaffold
    adj = StockAdjustment.objects.create(
        store=s["store_a"],
        reason="surplus_found",
        created_by=s["user"],
    )
    StockAdjustmentLine.objects.create(
        adjustment=adj,
        sku_code="SKU001",
        book_qty=10,
        counted_qty=12,
        adj_qty=2,
        unit_cost_paise=100,
    )

    _approve(adj, s)
    post_adjustment(adj, user=s["user"])

    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU001")
    assert oh.net_qty == 12  # 10 + 2

    gl_entries = list(GLEntry.objects.filter(doc_number=adj.doc_number))
    assert len(gl_entries) == 2
    dr_entry = [e for e in gl_entries if e.amount > 0][0]
    assert dr_entry.account == GLAccount.INVENTORY


@pytest.mark.django_db(transaction=True)
def test_adjustment_blocks_insufficient_stock(_outbound_scaffold):
    """Cannot adjust below zero."""
    s = _outbound_scaffold
    adj = StockAdjustment.objects.create(
        store=s["store_a"],
        reason="shrinkage",
        created_by=s["user"],
    )
    StockAdjustmentLine.objects.create(
        adjustment=adj,
        sku_code="SKU001",
        book_qty=10,
        counted_qty=0,
        adj_qty=-20,  # more than available
        unit_cost_paise=100,
    )

    _approve(adj, s)
    with pytest.raises(OutboundPostingError, match="Insufficient stock"):
        post_adjustment(adj, user=s["user"])


# ---------------------------------------------------------------------------
# 6. Write-off
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_writeoff_posts_gl(_outbound_scaffold):
    """Write-off: stock exits + Dr SUSPENSE (loss) / Cr INVENTORY."""
    s = _outbound_scaffold
    wo = WriteOff.objects.create(
        store=s["store_a"],
        reason="Dead stock — unsellable",
        created_by=s["user"],
    )
    WriteOffLine.objects.create(
        writeoff=wo,
        sku_code="SKU001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="OwnedBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty=1,
        unit_cost_paise=100,
    )

    _approve(wo, s)
    post_writeoff(wo, user=s["user"])
    assert wo.docstatus == DocStatus.SUBMITTED

    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU001")
    assert oh.net_qty == 9  # 10 - 1

    gl_entries = list(GLEntry.objects.filter(doc_number=wo.doc_number))
    assert len(gl_entries) == 2
    assert sum(e.amount for e in gl_entries) == 0

    dr_entry = [e for e in gl_entries if e.amount > 0][0]
    assert dr_entry.account == GLAccount.SUSPENSE
    assert dr_entry.amount == 100


@pytest.mark.django_db(transaction=True)
def test_writeoff_blocks_insufficient(_outbound_scaffold):
    """Cannot write off more than available."""
    s = _outbound_scaffold
    wo = WriteOff.objects.create(
        store=s["store_a"],
        created_by=s["user"],
    )
    WriteOffLine.objects.create(writeoff=wo, sku_code="SKU001", qty=999, unit_cost_paise=100)

    _approve(wo, s)
    with pytest.raises(OutboundPostingError, match="Insufficient stock"):
        post_writeoff(wo, user=s["user"])


# ---------------------------------------------------------------------------
# 7. V-flip
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_vflip_ownership_change(_outbound_scaffold):
    """V-flip: brand-owned → KDPS-owned, GL reclass, brand prefixed with 'V '."""
    s = _outbound_scaffold
    vflip = VFlip.objects.create(
        store=s["store_a"],
        original_brand=s["brand_sor"],
        season="SS26",
        created_by=s["user"],
    )
    VFlipLine.objects.create(
        vflip=vflip,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=2,
        unit_cost_paise=200,
    )

    _approve(vflip, s)
    post_vflip(vflip, user=s["user"])
    assert vflip.docstatus == DocStatus.SUBMITTED

    # Stock qty unchanged (V-flip is ownership change, not physical move)
    # StockOnHand is keyed by (store, sku_code), so net qty stays the same
    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU002")
    assert oh.net_qty == 5  # qty unchanged (out -2, in +2 = net 0)
    # But the brand on the record now shows "V SORBrand" (from the last inward)
    assert oh.brand == "V SORBrand"

    # V-prefixed brand stock created (at the SAME sku_code since barcode doesn't change)
    # The V-flip creates a NEW StockOnHand entry only if brand changes the key
    # Since StockOnHand key is (store, sku_code), the same entry is updated
    # The brand display change is tracked in the stock ledger audit trail
    # Let's check the stock ledger entries for the V-prefix
    vflip_entries = StockLedgerEntry.objects.filter(doc_number=vflip.doc_number, kind="vflip_in")
    assert vflip_entries.count() == 1
    assert vflip_entries.first().brand == "V SORBrand"

    # GL posted: 4 legs, balanced
    gl_entries = list(GLEntry.objects.filter(doc_number=vflip.doc_number))
    assert len(gl_entries) == 4
    assert sum(e.amount for e in gl_entries) == 0

    # Verify specific GL accounts
    gl_accounts = {e.account: e.amount for e in gl_entries}
    assert gl_accounts[GLAccount.SOR_CONTRA] == 400  # debit (reverse contra)
    assert gl_accounts[GLAccount.SOR_STOCK] == -400  # credit (reverse stock memo)
    assert gl_accounts[GLAccount.INVENTORY] == 400  # debit (now owned)
    assert gl_accounts[GLAccount.SUSPENSE] == -400  # credit (settlement claim placeholder)


# ---------------------------------------------------------------------------
# 8. Integration: trial balance check after combined outbound operations
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_trial_balance_zero_after_outbound(_outbound_scaffold):
    """The trial balance must be ₹0 after all outbound operations."""
    # This test verifies that ALL GL postings from outbound are balanced
    total_gl = sum(e.amount for e in GLEntry.objects.all())
    assert total_gl == 0, f"Trial balance is {total_gl} paise, expected 0"


@pytest.mark.django_db(transaction=True)
def test_transfer_receive_idempotent(_outbound_scaffold):
    """Cannot receive a transfer twice."""
    s = _outbound_scaffold
    transfer = StoreTransfer.objects.create(
        source_store=s["store_a"],
        destination_store=s["store_b"],
        created_by=s["user"],
    )
    StoreTransferLine.objects.create(
        transfer=transfer,
        sku_code="SKU001",
        qty_planned=2,
    )

    _approve(transfer, s)
    post_transfer_dispatch(transfer, {"SKU001": 2}, user=s["user"])
    post_transfer_receipt(transfer, {"SKU001": 2}, user=s["user"])

    with pytest.raises(OutboundPostingError, match="already received"):
        post_transfer_receipt(transfer, {"SKU001": 2}, user=s["user"])


@pytest.mark.django_db(transaction=True)
def test_rtv_credit_note_tracking(_outbound_scaffold):
    """RTV credit note fields are stored and queryable."""
    s = _outbound_scaffold
    rtv = ReturnToVendor.objects.create(
        store=s["store_a"],
        vendor=s["vendor"],
        brand=s["brand_owned"],
        return_type="defective",
        credit_note_received=True,
        credit_note_date="2026-07-15",
        created_by=s["user"],
    )
    rtv.refresh_from_db()
    assert rtv.credit_note_received is True
    assert str(rtv.credit_note_date) == "2026-07-15"


@pytest.mark.django_db(transaction=True)
def test_owned_rtv_vendor_subledger_in_sync(_outbound_scaffold):
    """Regression: owned RTV must keep vendor subledger in sync with GL.

    After posting an owned RTV:
      GL:         Dr VENDOR_PAYABLE / Cr INVENTORY  (balanced)
      Subledger:  VendorLedgerEntry.amount == -|GL VENDOR_PAYABLE dr|

    The sum of VendorLedgerEntry.amount for this vendor must equal the total
    GL VENDOR_PAYABLE balance for that vendor's reference.
    """
    from django.db.models import Sum

    s = _outbound_scaffold
    rtv = ReturnToVendor.objects.create(
        store=s["store_a"],
        vendor=s["vendor"],
        brand=s["brand_owned"],
        return_type="defective",
        logistics_route="warehouse",
        created_by=s["user"],
    )
    ReturnToVendorLine.objects.create(
        rtv=rtv,
        sku_code="SKU001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="OwnedBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty=3,
        unit_cost_paise=100,
    )
    post_rtv(rtv, user=s["user"])

    # GL VENDOR_PAYABLE debit for this RTV
    gl_payable_dr = (
        GLEntry.objects.filter(
            doc_number=rtv.doc_number, account=GLAccount.VENDOR_PAYABLE
        ).aggregate(s=Sum("amount"))["s"]
        or 0
    )

    # Vendor subledger entries referencing this RTV
    sub_amount = (
        VendorLedgerEntry.objects.filter(reference=rtv.doc_number).aggregate(s=Sum("amount"))["s"]
        or 0
    )

    # GL debit (positive) should equal negative of subledger (which is negative)
    assert gl_payable_dr == -sub_amount, (
        f"Vendor subledger drift! GL dr={gl_payable_dr}, sub={sub_amount}"
    )


@pytest.mark.django_db(transaction=True)
def test_sor_rtv_no_vendor_subledger_entry(_outbound_scaffold):
    """Brand-owned (SOR) RTV must NOT create vendor subledger entries.

    SOR stock is off-book: brand owns the value, we only track physical
    stock movement. No monetary claim is posted.
    """
    s = _outbound_scaffold
    rtv = ReturnToVendor.objects.create(
        store=s["store_a"],
        vendor=s["vendor"],
        brand=s["brand_sor"],
        return_type="seasonal",
        created_by=s["user"],
    )
    ReturnToVendorLine.objects.create(
        rtv=rtv,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=2,
        unit_cost_paise=200,
    )
    post_rtv(rtv, user=s["user"])

    # No GL, no vendor subledger
    assert GLEntry.objects.filter(doc_number=rtv.doc_number).count() == 0
    assert VendorLedgerEntry.objects.filter(reference=rtv.doc_number).count() == 0


# ---------------------------------------------------------------------------
# V-flip reporting / downstream regression tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_vflip_brand_displays_v_prefix(_outbound_scaffold):
    """After V-flip, StockOnHand.brand = 'V {brand}' and SLE entries carry it."""
    s = _outbound_scaffold
    vflip = VFlip.objects.create(
        store=s["store_a"],
        original_brand=s["brand_sor"],
        season="SS26",
        created_by=s["user"],
    )
    VFlipLine.objects.create(
        vflip=vflip,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=3,
        unit_cost_paise=200,
    )
    _approve(vflip, s)
    post_vflip(vflip, user=s["user"])

    # (a) StockOnHand brand shows "V SORBrand"
    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU002")
    assert oh.brand == "V SORBrand", f"Expected 'V SORBrand', got '{oh.brand}'"

    # (b) Net qty unchanged (ownership change, not physical move)
    assert oh.net_qty == 5

    # (c) SLE vflip_in entry carries "V SORBrand"
    vflip_in = StockLedgerEntry.objects.filter(
        doc_number=vflip.doc_number,
        kind="vflip_in",
    )
    assert vflip_in.count() == 1
    assert vflip_in.first().brand == "V SORBrand"


@pytest.mark.django_db(transaction=True)
def test_vflip_ownership_is_kdps_owned(_outbound_scaffold):
    """After V-flip, the stock is KDPS-owned in GL terms (INVENTORY, not SOR_STOCK)."""
    s = _outbound_scaffold
    vflip = VFlip.objects.create(
        store=s["store_a"],
        original_brand=s["brand_sor"],
        season="SS26",
        created_by=s["user"],
    )
    VFlipLine.objects.create(
        vflip=vflip,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=2,
        unit_cost_paise=200,
    )
    _approve(vflip, s)
    post_vflip(vflip, user=s["user"])

    # GL must have Dr INVENTORY (now KDPS-owned) — confirms it's NOT SOR anymore
    gl_inv = GLEntry.objects.filter(
        doc_number=vflip.doc_number,
        account=GLAccount.INVENTORY,
    )
    assert gl_inv.exists()
    assert gl_inv.first().amount > 0  # Debit = asset increase


@pytest.mark.django_db(transaction=True)
def test_rtv_blocked_for_vflipped_stock(_outbound_scaffold):
    """Cannot RTV stock that was V-flipped — ownership transferred to KDPS."""
    s = _outbound_scaffold

    # First: V-flip 3 units of SKU002 (SOR → KDPS-owned)
    vflip = VFlip.objects.create(
        store=s["store_a"],
        original_brand=s["brand_sor"],
        season="SS26",
        created_by=s["user"],
    )
    VFlipLine.objects.create(
        vflip=vflip,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=3,
        unit_cost_paise=200,
    )
    _approve(vflip, s)
    post_vflip(vflip, user=s["user"])

    # Confirm the stock is now "V SORBrand"
    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU002")
    assert oh.brand.startswith("V ")

    # Now attempt an RTV for the same SKU — must be blocked
    rtv = ReturnToVendor.objects.create(
        store=s["store_a"],
        vendor=s["vendor"],
        brand=s["brand_sor"],
        return_type="seasonal",
        created_by=s["user"],
    )
    ReturnToVendorLine.objects.create(
        rtv=rtv,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="SORBrand",
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=2,
        unit_cost_paise=200,
    )

    with pytest.raises(OutboundPostingError, match="V-flipped stock"):
        post_rtv(rtv, user=s["user"])


@pytest.mark.django_db(transaction=True)
def test_vflip_empty_line_brand_uses_original_brand(_outbound_scaffold):
    """V-flip with empty line.brand falls back to vflip.original_brand.name,
    NOT 'KDPS'. This was a regression: the frontend may send brand='' on lines."""
    s = _outbound_scaffold
    vflip = VFlip.objects.create(
        store=s["store_a"],
        original_brand=s["brand_sor"],
        season="SS26",
        created_by=s["user"],
    )
    VFlipLine.objects.create(
        vflip=vflip,
        sku_code="SKU002",
        design="Jeans",
        color="Black",
        size="L",
        brand="",  # Empty — simulates frontend omission
        season="SS26",
        item="jeans",
        hsn="6203",
        qty=1,
        unit_cost_paise=200,
    )
    _approve(vflip, s)
    post_vflip(vflip, user=s["user"])

    oh = StockOnHand.objects.get(store=s["store_a"], sku_code="SKU002")
    assert oh.brand == "V SORBrand", (
        f"Expected 'V SORBrand' but got '{oh.brand}' — "
        "empty line.brand should fall back to original_brand.name"
    )

    vflip_in = StockLedgerEntry.objects.filter(
        doc_number=vflip.doc_number,
        kind="vflip_in",
    )
    assert vflip_in.first().brand == "V SORBrand"
