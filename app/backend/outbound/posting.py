"""Outbound posting engine — stock movements out of a location + balanced GL.

Follows the kernel pattern: every event writes append-only stock entries AND
(where applicable) balanced value GL vouchers via `core.post_entries`.
Stock-on-hand is updated atomically within the same transaction.

All amounts are integer paise. Debit is positive, credit is negative.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from core.gl import GLAccount
from core.posting import PostingRef, cr, dr, post_entries
from stockledger.models import StockLedgerEntry, StockOnHand

if TYPE_CHECKING:
    from outbound.models import (
        ReturnToVendor,
        StockAdjustment,
        StoreTransfer,
        VFlip,
        WriteOff,
    )


class OutboundPostingError(Exception):
    """Raised when an outbound document cannot be posted."""


def _check_stock(store_id: int, sku_code: str, required_qty: int) -> None:
    """Block if insufficient stock at the source location."""
    try:
        on_hand = StockOnHand.objects.get(store_id=store_id, sku_code=sku_code)
        available = on_hand.net_qty
    except StockOnHand.DoesNotExist:
        available = 0
    if available < required_qty:
        raise OutboundPostingError(
            f"Insufficient stock for {sku_code} at store {store_id}: "
            f"available={available}, required={required_qty}"
        )


def _write_stock_entry(
    *,
    store,
    gstin,
    line,
    qty: int,
    kind: str,
    doc_number: str,
    line_no: int,
    posted_by=None,
) -> StockLedgerEntry:
    """Create a single stock ledger entry and update StockOnHand."""
    amount_paise = qty * (line.unit_cost_paise if hasattr(line, 'unit_cost_paise') else 0)
    entry = StockLedgerEntry.objects.create(
        store=store,
        gstin=gstin,
        sku_code=line.sku_code,
        design=getattr(line, 'design', ''),
        color=getattr(line, 'color', ''),
        size=getattr(line, 'size', ''),
        brand=getattr(line, 'brand', ''),
        season=getattr(line, 'season', ''),
        item=getattr(line, 'item', ''),
        hsn=getattr(line, 'hsn', ''),
        qty=qty,
        amount=amount_paise,
        kind=kind,
        doc_number=doc_number,
        line_no=line_no,
        posted_by=posted_by,
    )
    # Update materialised StockOnHand
    obj, _ = StockOnHand.objects.get_or_create(
        store=store,
        sku_code=line.sku_code,
        defaults={
            "gstin": gstin,
            "design": getattr(line, 'design', ''),
            "color": getattr(line, 'color', ''),
            "size": getattr(line, 'size', ''),
            "brand": getattr(line, 'brand', ''),
            "season": getattr(line, 'season', ''),
            "item": getattr(line, 'item', ''),
            "hsn": getattr(line, 'hsn', ''),
            "net_qty": 0,
            "net_value_paise": 0,
        },
    )
    obj.net_qty += qty
    obj.net_value_paise += amount_paise
    # Refresh descriptive fields on inward (positive qty)
    if qty > 0:
        obj.design = getattr(line, 'design', '') or obj.design
        obj.color = getattr(line, 'color', '') or obj.color
        obj.size = getattr(line, 'size', '') or obj.size
        obj.brand = getattr(line, 'brand', '') or obj.brand
        obj.season = getattr(line, 'season', '') or obj.season
        obj.item = getattr(line, 'item', '') or obj.item
        obj.hsn = getattr(line, 'hsn', '') or obj.hsn
        obj.gstin = gstin
    obj.save()
    return entry


# ---------------------------------------------------------------------------
# 1. Store Transfer — dispatch (stock out at source)
# ---------------------------------------------------------------------------

@transaction.atomic
def post_transfer_dispatch(transfer: StoreTransfer, user=None) -> list[StockLedgerEntry]:
    """Post the dispatch side: stock exits source, enters in-transit.

    For same-state: stock move only, no GL.
    For cross-state: stock move only (IGST invoice is manual).
    """
    lines = list(transfer.lines.all())
    if not lines:
        raise OutboundPostingError("Transfer has no lines.")

    # Validate stock availability at source
    for line in lines:
        _check_stock(transfer.source_store_id, line.sku_code, line.qty_dispatched)

    # Set dispatch metadata BEFORE post() (submitted docs are DB-immutable)
    transfer.dispatch_date = timezone.now()
    transfer.dispatched_by = user

    # Post the document (mint number, set SUBMITTED — saves everything atomically)
    transfer.post()

    entries = []
    for i, line in enumerate(lines, start=1):
        # Stock OUT at source
        entry = _write_stock_entry(
            store=transfer.source_store,
            gstin=transfer.source_store.gstin,
            line=line,
            qty=-line.qty_dispatched,
            kind="transfer_out",
            doc_number=transfer.doc_number,
            line_no=i,
            posted_by=user,
        )
        entries.append(entry)

    return entries


@transaction.atomic
def post_transfer_receipt(
    transfer: StoreTransfer, received_quantities: dict[int, int], user=None
) -> list[StockLedgerEntry]:
    """Post the receipt side: stock enters destination.

    `received_quantities` maps line.id → qty_received.
    Shortfall (dispatched != received) is flagged, not blocked.
    Creates a TransferReceipt companion record (submitted docs are immutable).
    """
    from core.documents import DocStatus
    from outbound.models import ReceiptStatus, TransferReceipt

    if transfer.docstatus != DocStatus.SUBMITTED:
        raise OutboundPostingError("Transfer must be dispatched (submitted) before receipt.")
    if hasattr(transfer, 'receipt') and transfer.receipt is not None:
        raise OutboundPostingError("Transfer already received.")
    # Check if receipt already exists
    if TransferReceipt.objects.filter(transfer=transfer).exists():
        raise OutboundPostingError("Transfer already received.")

    lines = list(transfer.lines.all())
    entries = []
    has_shortfall = False

    for i, line in enumerate(lines, start=1):
        qty_recv = received_quantities.get(line.id, line.qty_dispatched)
        line.qty_received = qty_recv
        line.save(update_fields=["qty_received"])

        if qty_recv != line.qty_dispatched:
            has_shortfall = True

        if qty_recv > 0:
            entry = _write_stock_entry(
                store=transfer.destination_store,
                gstin=transfer.destination_store.gstin,
                line=line,
                qty=qty_recv,
                kind="transfer_in",
                doc_number=transfer.doc_number,
                line_no=1000 + i,  # offset to distinguish from dispatch entries
                posted_by=user,
            )
            entries.append(entry)

    # Create the receipt companion record
    TransferReceipt.objects.create(
        transfer=transfer,
        received_by=user,
        receipt_status=(
            ReceiptStatus.SHORTFALL if has_shortfall else ReceiptStatus.COMPLETE
        ),
    )

    return entries


# ---------------------------------------------------------------------------
# 2. Return to Vendor (RTV) — stock out + conditional GL
# ---------------------------------------------------------------------------

@transaction.atomic
def post_rtv(rtv: ReturnToVendor, user=None) -> list[StockLedgerEntry]:
    """Post an RTV: stock exits, GL posts for owned stock only.

    - Owned (Outright/Correction): Dr VENDOR_PAYABLE / Cr INVENTORY
    - Brand-owned (SOR/Consignment): stock out only, no GL
    """
    from masters.models import Brand

    lines = list(rtv.lines.all())
    if not lines:
        raise OutboundPostingError("RTV has no lines.")

    for line in lines:
        _check_stock(rtv.store_id, line.sku_code, line.qty)

    # Block RTVs on V-flipped stock: ownership has transferred to KDPS,
    # so returning it to the brand is no longer valid.
    vflipped_skus = list(
        StockOnHand.objects.filter(
            store_id=rtv.store_id,
            sku_code__in=[l.sku_code for l in lines],
            brand__startswith="V ",
        ).values_list("sku_code", flat=True)
    )
    if vflipped_skus:
        raise OutboundPostingError(
            f"Cannot RTV V-flipped stock (ownership transferred to KDPS): "
            f"{', '.join(vflipped_skus)}"
        )

    rtv.post()

    entries = []
    total_value_paise = 0
    kind = "rtv_out" if rtv.return_type == "defective" else "seasonal_ret"

    for i, line in enumerate(lines, start=1):
        entry = _write_stock_entry(
            store=rtv.store,
            gstin=rtv.store.gstin,
            line=line,
            qty=-line.qty,
            kind=kind,
            doc_number=rtv.doc_number,
            line_no=i,
            posted_by=user,
        )
        entries.append(entry)
        total_value_paise += line.qty * line.unit_cost_paise

    # GL posting: only for KDPS-owned stock (Outright / Correction)
    is_owned = False
    if rtv.brand:
        is_owned = rtv.brand.ownership == Brand.Ownership.OWNED

    if is_owned and total_value_paise > 0:
        doc_ref = PostingRef(
            doc_type="RTV",
            doc_number=rtv.doc_number,
            store=rtv.store,
            gstin=rtv.store.gstin,
            posted_by=user,
        )
        vendor_code = str(rtv.vendor_id) if rtv.vendor_id else ""
        post_entries(doc_ref, [
            dr(GLAccount.VENDOR_PAYABLE, total_value_paise,
               party_type="vendor", party_code=vendor_code,
               memo=f"RTV {rtv.return_type}: reduces payable"),
            cr(GLAccount.INVENTORY, total_value_paise,
               memo=f"RTV {rtv.return_type}: stock returned"),
        ], posted_by=user)

        # Vendor subledger mirror — reduces what we owe (negative amount).
        # GL is already posted above via post_entries, so gl=False to avoid
        # double-booking the payable (same pattern as post_pt_vendor_bill).
        from finledger.posting import post_vendor_bill
        post_vendor_bill(
            rtv.vendor,
            -total_value_paise,
            f"RTV {rtv.return_type}: credit for {rtv.doc_number}",
            user,
            reference=rtv.doc_number,
            gl=False,
        )

    return entries


# ---------------------------------------------------------------------------
# 3. Stock Adjustment — count vs book
# ---------------------------------------------------------------------------

@transaction.atomic
def post_adjustment(adj: StockAdjustment, user=None) -> list[StockLedgerEntry]:
    """Post a stock adjustment: +/− qty at frozen cost.

    GL: Dr/Cr INVENTORY vs Cr/Dr SUSPENSE.
    Reductions are blocked if insufficient stock.
    """
    lines = list(adj.lines.all())
    if not lines:
        raise OutboundPostingError("Adjustment has no lines.")

    # Block if any line reduces stock below zero
    for line in lines:
        if line.adj_qty < 0:
            _check_stock(adj.store_id, line.sku_code, abs(line.adj_qty))

    adj.post()

    entries = []
    total_debit_paise = 0  # net: + means inventory increases, - means decreases

    for i, line in enumerate(lines, start=1):
        if line.adj_qty == 0:
            continue
        entry = _write_stock_entry(
            store=adj.store,
            gstin=adj.store.gstin,
            line=line,
            qty=line.adj_qty,
            kind="adjustment",
            doc_number=adj.doc_number,
            line_no=i,
            posted_by=user,
        )
        entries.append(entry)
        total_debit_paise += line.adj_qty * line.unit_cost_paise

    # GL posting: balanced voucher
    if total_debit_paise != 0:
        doc_ref = PostingRef(
            doc_type="ADJ",
            doc_number=adj.doc_number,
            store=adj.store,
            gstin=adj.store.gstin,
            posted_by=user,
        )
        if total_debit_paise > 0:
            # Surplus: Dr INVENTORY / Cr SUSPENSE
            legs = [
                dr(GLAccount.INVENTORY, total_debit_paise, memo="Adjustment: surplus"),
                cr(GLAccount.SUSPENSE, total_debit_paise, memo="Adjustment: surplus contra"),
            ]
        else:
            # Shrinkage: Dr SUSPENSE / Cr INVENTORY
            legs = [
                dr(GLAccount.SUSPENSE, abs(total_debit_paise), memo="Adjustment: shrinkage"),
                cr(GLAccount.INVENTORY, abs(total_debit_paise), memo="Adjustment: shrinkage contra"),
            ]
        post_entries(doc_ref, legs, posted_by=user)

    return entries


# ---------------------------------------------------------------------------
# 4. Write-off — owner-approved stock exit
# ---------------------------------------------------------------------------

@transaction.atomic
def post_writeoff(wo: WriteOff, user=None) -> list[StockLedgerEntry]:
    """Post a write-off: stock exits, loss booked.

    GL: Dr SUSPENSE (loss) / Cr INVENTORY.
    """
    lines = list(wo.lines.all())
    if not lines:
        raise OutboundPostingError("Write-off has no lines.")

    for line in lines:
        _check_stock(wo.store_id, line.sku_code, line.qty)

    wo.post()

    entries = []
    total_value_paise = 0

    for i, line in enumerate(lines, start=1):
        entry = _write_stock_entry(
            store=wo.store,
            gstin=wo.store.gstin,
            line=line,
            qty=-line.qty,
            kind="write_off",
            doc_number=wo.doc_number,
            line_no=i,
            posted_by=user,
        )
        entries.append(entry)
        total_value_paise += line.qty * line.unit_cost_paise

    if total_value_paise > 0:
        doc_ref = PostingRef(
            doc_type="WRO",
            doc_number=wo.doc_number,
            store=wo.store,
            gstin=wo.store.gstin,
            posted_by=user,
        )
        post_entries(doc_ref, [
            dr(GLAccount.SUSPENSE, total_value_paise, memo="Write-off: loss"),
            cr(GLAccount.INVENTORY, total_value_paise, memo="Write-off: stock exit"),
        ], posted_by=user)

    return entries


# ---------------------------------------------------------------------------
# 5. V-flip — brand-owned → KDPS-owned (GL reclass, no physical move)
# ---------------------------------------------------------------------------

@transaction.atomic
def post_vflip(vflip: VFlip, user=None) -> list[StockLedgerEntry]:
    """Post a V-flip: ownership changes, stock stays.

    GL: reverse SOR pair, book as owned.
      Dr SOR_CONTRA / Cr SOR_STOCK (remove memo)
      Dr INVENTORY / Cr SUSPENSE (now owned, settlement claim in Sprint 8)

    Stock: write -qty (old brand) and +qty (V-prefixed brand) entries
    to leave an audit trail of the ownership change.
    """
    lines = list(vflip.lines.all())
    if not lines:
        raise OutboundPostingError("V-flip has no lines.")

    for line in lines:
        _check_stock(vflip.store_id, line.sku_code, line.qty)

    vflip.post()

    entries = []
    total_value_paise = 0

    for i, line in enumerate(lines, start=1):
        # Stock OUT from old brand identity
        _write_stock_entry(
            store=vflip.store,
            gstin=vflip.store.gstin,
            line=line,
            qty=-line.qty,
            kind="vflip_out",
            doc_number=vflip.doc_number,
            line_no=i,
            posted_by=user,
        )
        # Stock IN as "V <brand>" (KDPS-owned)
        v_brand_name = f"V {line.brand}" if line.brand else "V KDPS"

        class _VLine:
            pass

        vline = _VLine()
        vline.sku_code = line.sku_code
        vline.design = line.design
        vline.color = line.color
        vline.size = line.size
        vline.brand = v_brand_name
        vline.season = line.season
        vline.item = line.item
        vline.hsn = line.hsn
        vline.unit_cost_paise = line.unit_cost_paise

        entry_in = _write_stock_entry(
            store=vflip.store,
            gstin=vflip.store.gstin,
            line=vline,
            qty=line.qty,
            kind="vflip_in",
            doc_number=vflip.doc_number,
            line_no=1000 + i,
            posted_by=user,
        )
        entries.append(entry_in)
        total_value_paise += line.qty * line.unit_cost_paise

    # GL: reverse SOR pair + book as owned
    if total_value_paise > 0:
        doc_ref = PostingRef(
            doc_type="VFL",
            doc_number=vflip.doc_number,
            store=vflip.store,
            gstin=vflip.store.gstin,
            posted_by=user,
        )
        post_entries(doc_ref, [
            # Reverse the SOR memo pair
            dr(GLAccount.SOR_CONTRA, total_value_paise,
               memo="V-flip: reverse SOR contra"),
            cr(GLAccount.SOR_STOCK, total_value_paise,
               memo="V-flip: reverse SOR stock memo"),
            # Book as KDPS-owned
            dr(GLAccount.INVENTORY, total_value_paise,
               memo="V-flip: now KDPS-owned"),
            cr(GLAccount.SUSPENSE, total_value_paise,
               memo="V-flip: settlement claim (Sprint 8)"),
        ], posted_by=user)

    return entries
