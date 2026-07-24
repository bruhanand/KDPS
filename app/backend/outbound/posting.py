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
from outbound.maker_checker import require_approved
from stockledger.models import (
    InTransitStock,
    QuarantineStock,
    StockLedgerEntry,
    StockOnHand,
    merch_dims,
)

if TYPE_CHECKING:
    from outbound.models import (
        MarkDamaged,
        ReturnToVendor,
        StockAdjustment,
        StoreTransfer,
        VFlip,
        WriteOff,
    )


class OutboundPostingError(Exception):
    """Raised when an outbound document cannot be posted."""


def _check_stock(store_id: int, sku_code: str, required_qty: int) -> None:
    """Block if insufficient stock at the source location.

    Row-locks the on-hand row (``select_for_update``) so two concurrent
    dispatches of the same pieces serialize instead of both passing the check
    and overselling — callers run inside ``transaction.atomic``.
    """
    try:
        on_hand = StockOnHand.objects.select_for_update().get(store_id=store_id, sku_code=sku_code)
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
    amount_paise = qty * (line.unit_cost_paise if hasattr(line, "unit_cost_paise") else 0)
    entry = StockLedgerEntry.objects.create(
        store=store,
        gstin=gstin,
        sku_code=line.sku_code,
        design=getattr(line, "design", ""),
        color=getattr(line, "color", ""),
        size=getattr(line, "size", ""),
        brand=getattr(line, "brand", ""),
        season=getattr(line, "season", ""),
        item=getattr(line, "item", ""),
        hsn=getattr(line, "hsn", ""),
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
            "design": getattr(line, "design", ""),
            "color": getattr(line, "color", ""),
            "size": getattr(line, "size", ""),
            "brand": getattr(line, "brand", ""),
            "season": getattr(line, "season", ""),
            "item": getattr(line, "item", ""),
            "hsn": getattr(line, "hsn", ""),
            "net_qty": 0,
            "net_value_paise": 0,
        },
    )
    obj.net_qty += qty
    obj.net_value_paise += amount_paise
    # Refresh descriptive fields on inward (positive qty)
    if qty > 0:
        obj.design = getattr(line, "design", "") or obj.design
        obj.color = getattr(line, "color", "") or obj.color
        obj.size = getattr(line, "size", "") or obj.size
        obj.brand = getattr(line, "brand", "") or obj.brand
        obj.season = getattr(line, "season", "") or obj.season
        obj.item = getattr(line, "item", "") or obj.item
        obj.hsn = getattr(line, "hsn", "") or obj.hsn
        obj.gstin = gstin
    obj.save()
    return entry


# ---------------------------------------------------------------------------
# 1. Store Transfer — scanned dispatch / receive with an in-transit bucket
# ---------------------------------------------------------------------------
#
# Dispatch: source −qty (transfer_out) + in-transit +qty (transit_in), both
# under the transfer's doc number. Receive: in-transit −qty (transit_out) +
# destination +qty (transfer_in). The pieces are never in no location, and
# free-to-sell (StockOnHand) excludes in-transit throughout.
#
# Scan-is-truth (#68): the scanned quantities are the only quantities that
# post. A scanned-vs-plan gap is flagged, never blocked (Rule 5); a barcode
# outside the plan (or, at receive, outside the dispatched lines) is rejected.

# line_no bands — one doc number carries all four leg types, so each type gets
# its own band (dispatch writes OUT+TRANSIT_IN, receive TRANSIT_OUT+IN).
LINE_NO_TRANSFER_OUT = 0
LINE_NO_TRANSIT_IN = 500
LINE_NO_TRANSFER_IN = 1000
LINE_NO_TRANSIT_OUT = 1500


def _validate_scans(scans: dict[str, int], allowed: set[str] | None, context: str) -> None:
    """Shared scan-payload guard: non-empty, qty ≥ 1, and (when a line set is
    given) every scanned barcode on it — the wrong-piece beep, server-side."""
    if not scans or any(q < 1 for q in scans.values()):
        raise OutboundPostingError(f"{context} needs scanned lines (barcode × qty ≥ 1).")
    if allowed is not None:
        unknown = sorted(set(scans) - allowed)
        if unknown:
            raise OutboundPostingError(
                f"Not on this transfer: {', '.join(unknown)}. "
                "Scanned pieces must match the transfer receipt."
            )


def _write_transit_entry(
    *,
    transfer: StoreTransfer,
    line,
    qty: int,
    kind: str,
    line_no: int,
    posted_by=None,
) -> StockLedgerEntry:
    """One in-transit ledger leg + the InTransitStock projection update.

    Transit legs ride on the *source* store (the sender is answerable until
    the receiver scans in) and deliberately do NOT touch StockOnHand — the
    bucket lives in InTransitStock, keyed to the transfer's doc number.
    """
    amount_paise = qty * line.unit_cost_paise
    entry = StockLedgerEntry.objects.create(
        store=transfer.source_store,
        gstin=transfer.source_store.gstin,
        sku_code=line.sku_code,
        **merch_dims(line),
        qty=qty,
        amount=amount_paise,
        kind=kind,
        doc_number=transfer.doc_number,
        line_no=line_no,
        posted_by=posted_by,
    )
    bucket, _ = InTransitStock.objects.get_or_create(
        transfer_doc_number=transfer.doc_number,
        sku_code=line.sku_code,
        defaults={
            "source_store": transfer.source_store,
            "destination_store": transfer.destination_store,
            "gstin": transfer.source_store.gstin,
            **merch_dims(line),
            "qty": 0,
            "value_paise": 0,
        },
    )
    bucket.qty += qty
    bucket.value_paise += amount_paise
    if bucket.qty == 0:
        # A fully-received transfer leaves no bucket row — matching the rebuild
        # command, which also emits no row for a zeroed (doc, sku) pair.
        bucket.delete()
    else:
        bucket.save()
    return entry


def book_unit_cost(store_id: int, sku_code: str) -> int:
    """What the books say one piece costs at this location, in paise.

    The cohort's frozen P-RATE where there is one, else the on-hand average.
    Returns 0 when the location holds no such stock — "unknown", which every
    caller must treat as unknown rather than as free.
    """
    from masters.models import Cohort

    on_hand = StockOnHand.objects.filter(store_id=store_id, sku_code=sku_code).first()
    if on_hand is None:
        return 0
    cohort = Cohort.objects.filter(barcode=sku_code, season=on_hand.season).first()
    if cohort is not None:
        return int(cohort.unit_cost_paise or 0)
    if on_hand.net_qty > 0:
        return int(on_hand.net_value_paise or 0) // on_hand.net_qty
    return 0


def _resolve_scan_identity(store_id: int, barcode: str) -> dict[str, int | str]:
    """Merchandising dims + unit cost for a scanned barcode, from the source
    location's stock (the ledger is self-describing) and the cohort's frozen
    P-RATE cost where one exists (falling back to the on-hand average)."""
    try:
        on_hand = StockOnHand.objects.get(store_id=store_id, sku_code=barcode)
    except StockOnHand.DoesNotExist:
        raise OutboundPostingError(
            f"Barcode {barcode} has no stock at the source location."
        ) from None

    return {**merch_dims(on_hand), "unit_cost_paise": book_unit_cost(store_id, barcode)}


@transaction.atomic
def post_transfer_dispatch(
    transfer: StoreTransfer, scans: dict[str, int], user=None
) -> list[StockLedgerEntry]:
    """Post the dispatch side from scanned quantities only.

    ``scans`` maps barcode → scanned qty. With plan lines, every scanned
    barcode must be on the plan (wrong-piece beep otherwise); a quantity gap
    is flagged, never blocked. With no plan lines (store→store scan-to-build)
    the scans *become* the lines, enriched from the source stock.

    Stock move only, no GL (cross-state IGST invoice is manual by decision).
    """
    from core.documents import DocStatus
    from outbound.models import StoreTransfer, StoreTransferLine

    # Serialize on the transfer row: a concurrent dispatch of the same draft
    # blocks here, then sees SUBMITTED and fails instead of double-posting.
    locked = StoreTransfer.objects.select_for_update().get(pk=transfer.pk)
    if locked.docstatus != DocStatus.DRAFT:
        raise OutboundPostingError("Transfer already dispatched.")

    plan_lines = {line.sku_code: line for line in transfer.lines.all()}
    _validate_scans(scans, set(plan_lines) if plan_lines else None, "Dispatch")

    # Validate stock + resolve identity/cost from the source location
    for barcode, qty in scans.items():
        _check_stock(transfer.source_store_id, barcode, qty)

    dispatch_lines = []
    for barcode, qty in sorted(scans.items()):
        identity = _resolve_scan_identity(transfer.source_store_id, barcode)
        line = plan_lines.get(barcode)
        if line is None:
            line = StoreTransferLine(transfer=transfer, sku_code=barcode, qty_planned=None)
        line.qty_dispatched = qty
        for field, value in identity.items():
            setattr(line, field, value)
        line.save()
        dispatch_lines.append(line)

    # Set dispatch metadata BEFORE post() (submitted docs are DB-immutable)
    transfer.dispatch_date = timezone.now()
    transfer.dispatched_by = user

    # Post the document (mint number, set SUBMITTED — saves everything atomically)
    transfer.post()

    entries = []
    for i, line in enumerate(dispatch_lines, start=1):
        # Stock OUT at source (free-to-sell drops immediately)
        entries.append(
            _write_stock_entry(
                store=transfer.source_store,
                gstin=transfer.source_store.gstin,
                line=line,
                qty=-line.qty_dispatched,
                kind="transfer_out",
                doc_number=transfer.doc_number,
                line_no=LINE_NO_TRANSFER_OUT + i,
                posted_by=user,
            )
        )
        # Stock INTO the in-transit bucket under this transfer
        entries.append(
            _write_transit_entry(
                transfer=transfer,
                line=line,
                qty=line.qty_dispatched,
                kind="transit_in",
                line_no=LINE_NO_TRANSIT_IN + i,
                posted_by=user,
            )
        )

    return entries


@transaction.atomic
def post_transfer_receipt(
    transfer: StoreTransfer, scans: dict[str, int], user=None
) -> list[StockLedgerEntry]:
    """Post the receive side from scanned quantities only.

    ``scans`` maps barcode → scanned-in qty. Each scanned piece moves from
    the in-transit bucket to the destination. A short receive leaves the
    remainder in-transit and flags the receipt (shortfall); scanning a
    barcode that wasn't dispatched, or more than was sent, is rejected
    (extra/damaged handling is a later slice). Creates a TransferReceipt
    companion record (submitted docs are immutable).
    """
    from core.documents import DocStatus
    from outbound.models import ReceiptStatus, StoreTransfer, TransferReceipt

    if transfer.docstatus != DocStatus.SUBMITTED:
        raise OutboundPostingError("Transfer must be dispatched (submitted) before receipt.")
    # Serialize on the transfer row: a concurrent receive of the same transfer
    # blocks here, then the already-received check below sees the first receipt.
    StoreTransfer.objects.select_for_update().get(pk=transfer.pk)
    if TransferReceipt.objects.filter(transfer=transfer).exists():
        raise OutboundPostingError("Transfer already received.")

    lines = {line.sku_code: line for line in transfer.lines.all() if line.qty_dispatched > 0}
    _validate_scans(scans, set(lines), "Receive")

    for barcode, qty in scans.items():
        if qty > lines[barcode].qty_dispatched:
            raise OutboundPostingError(
                f"Scanned more than was sent for {barcode}: "
                f"sent={lines[barcode].qty_dispatched}, scanned={qty}."
            )

    entries = []
    has_shortfall = False

    for i, (barcode, line) in enumerate(sorted(lines.items()), start=1):
        qty_recv = scans.get(barcode, 0)
        line.qty_received = qty_recv
        line.save(update_fields=["qty_received"])

        if qty_recv != line.qty_dispatched:
            has_shortfall = True
        if qty_recv == 0:
            continue

        # OUT of the in-transit bucket…
        entries.append(
            _write_transit_entry(
                transfer=transfer,
                line=line,
                qty=-qty_recv,
                kind="transit_out",
                line_no=LINE_NO_TRANSIT_OUT + i,
                posted_by=user,
            )
        )
        # …and INTO the destination (ready for sale)
        entries.append(
            _write_stock_entry(
                store=transfer.destination_store,
                gstin=transfer.destination_store.gstin,
                line=line,
                qty=qty_recv,
                kind="transfer_in",
                doc_number=transfer.doc_number,
                line_no=LINE_NO_TRANSFER_IN + i,
                posted_by=user,
            )
        )

    # Create the receipt companion record (short remainder stays in-transit,
    # flagged; gap closure is a later slice)
    TransferReceipt.objects.create(
        transfer=transfer,
        received_by=user,
        receipt_status=(ReceiptStatus.SHORTFALL if has_shortfall else ReceiptStatus.COMPLETE),
    )

    return entries


# ---------------------------------------------------------------------------
# 1b. Mark damaged — global action moving a piece to quarantine
# ---------------------------------------------------------------------------
#
# A mark-damaged document posts, under its own DMG voucher number, two legs at
# the store: damage_out (−qty, drops free-to-sell in StockOnHand) + quarantine_in
# (+qty, into the QuarantineStock bucket). The piece never leaves the store and
# stays owned — it is just no longer sellable. No GL: the two legs net to zero,
# so total inventory value is unchanged (the same shape as the in-transit pair).

# line_no bands — one DMG doc number carries both leg types.
LINE_NO_DAMAGE_OUT = 0
LINE_NO_QUARANTINE_IN = 500


def _write_quarantine_entry(
    *,
    store,
    gstin,
    line,
    qty: int,
    doc_number: str,
    line_no: int,
    posted_by=None,
) -> StockLedgerEntry:
    """One ``quarantine_in`` ledger leg + the QuarantineStock projection update.

    Deliberately does NOT touch StockOnHand — the quarantine bucket lives in
    QuarantineStock, keyed by (store × barcode). ``marked_by``/``marked_at`` on
    the bucket record the most-recent mark-damaged actor + time for the
    inventory quarantine filter.
    """
    amount_paise = qty * line.unit_cost_paise
    entry = StockLedgerEntry.objects.create(
        store=store,
        gstin=gstin,
        sku_code=line.sku_code,
        **merch_dims(line),
        qty=qty,
        amount=amount_paise,
        kind=StockLedgerEntry.Kind.QUARANTINE_IN,
        doc_number=doc_number,
        line_no=line_no,
        posted_by=posted_by,
    )
    bucket, _ = QuarantineStock.objects.get_or_create(
        store=store,
        sku_code=line.sku_code,
        defaults={
            "gstin": gstin,
            **merch_dims(line),
            "qty": 0,
            "value_paise": 0,
        },
    )
    bucket.qty += qty
    bucket.value_paise += amount_paise
    bucket.marked_by = posted_by
    bucket.marked_at = entry.created_at
    if bucket.qty == 0:
        # A fully-cleared quarantine (later slice: return / release) leaves no
        # row — matching the rebuild command, which emits no zero-qty row.
        bucket.delete()
    else:
        bucket.save()
    return entry


@transaction.atomic
def mark_damaged(store, scans: dict[str, int], user=None, note: str = "") -> MarkDamaged:
    """The global mark-damaged action, end to end (Rule 1 — every event is a
    document): create a DMG document, enrich each scanned piece from the store's
    stock (dims + frozen cost, never typed), and post it — moving the pieces from
    free-to-sell into quarantine at the store, all in one transaction so a bad
    scan rolls the whole thing back (no orphan draft).
    """
    from outbound.models import MarkDamaged, MarkDamagedLine

    if not scans:
        raise OutboundPostingError("Mark-damaged needs scanned pieces.")

    mark = MarkDamaged.objects.create(store=store, note=note, created_by=user)
    for barcode, qty in sorted(scans.items()):
        identity = _resolve_scan_identity(store.id, barcode)
        MarkDamagedLine.objects.create(mark=mark, sku_code=barcode, qty=qty, **identity)
    post_mark_damaged(mark, user=user)
    return mark


@transaction.atomic
def post_mark_damaged(mark: MarkDamaged, user=None) -> list[StockLedgerEntry]:
    """Post a mark-damaged document: move each line's pieces from free-to-sell
    into quarantine at the store.

    Blocks (Rule 5's dangerous-exception) if the store has too little sellable
    stock of a piece — you cannot quarantine stock that isn't there. Stock move
    only, no GL.
    """
    lines = list(mark.lines.all())
    if not lines:
        raise OutboundPostingError("Mark-damaged has no lines.")

    # Row-lock + validate sellable stock at the store before minting a number.
    for line in lines:
        _check_stock(mark.store_id, line.sku_code, line.qty)

    mark.post()

    entries: list[StockLedgerEntry] = []
    for i, line in enumerate(lines, start=1):
        # Out of free-to-sell at the store…
        entries.append(
            _write_stock_entry(
                store=mark.store,
                gstin=mark.store.gstin,
                line=line,
                qty=-line.qty,
                kind=StockLedgerEntry.Kind.DAMAGE_OUT,
                doc_number=mark.doc_number,
                line_no=LINE_NO_DAMAGE_OUT + i,
                posted_by=user,
            )
        )
        # …and into quarantine at the same store
        entries.append(
            _write_quarantine_entry(
                store=mark.store,
                gstin=mark.store.gstin,
                line=line,
                qty=line.qty,
                doc_number=mark.doc_number,
                line_no=LINE_NO_QUARANTINE_IN + i,
                posted_by=user,
            )
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
            sku_code__in=[line.sku_code for line in lines],
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
        post_entries(
            doc_ref,
            [
                dr(
                    GLAccount.VENDOR_PAYABLE,
                    total_value_paise,
                    party_type="vendor",
                    party_code=vendor_code,
                    memo=f"RTV {rtv.return_type}: reduces payable",
                ),
                cr(
                    GLAccount.INVENTORY,
                    total_value_paise,
                    memo=f"RTV {rtv.return_type}: stock returned",
                ),
            ],
            posted_by=user,
        )

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

    require_approved(adj)  # maker ≠ checker (#70)

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
                cr(
                    GLAccount.INVENTORY, abs(total_debit_paise), memo="Adjustment: shrinkage contra"
                ),
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

    require_approved(wo)  # maker ≠ checker (#70)

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
        post_entries(
            doc_ref,
            [
                dr(GLAccount.SUSPENSE, total_value_paise, memo="Write-off: loss"),
                cr(GLAccount.INVENTORY, total_value_paise, memo="Write-off: stock exit"),
            ],
            posted_by=user,
        )

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

    require_approved(vflip)  # maker ≠ checker (#70)

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
        original_brand_name = line.brand or (
            vflip.original_brand.name if vflip.original_brand else "KDPS"
        )
        v_brand_name = f"V {original_brand_name}"

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
        post_entries(
            doc_ref,
            [
                # Reverse the SOR memo pair
                dr(GLAccount.SOR_CONTRA, total_value_paise, memo="V-flip: reverse SOR contra"),
                cr(GLAccount.SOR_STOCK, total_value_paise, memo="V-flip: reverse SOR stock memo"),
                # Book as KDPS-owned
                dr(GLAccount.INVENTORY, total_value_paise, memo="V-flip: now KDPS-owned"),
                cr(
                    GLAccount.SUSPENSE,
                    total_value_paise,
                    memo="V-flip: settlement claim (Sprint 8)",
                ),
            ],
            posted_by=user,
        )

    return entries
