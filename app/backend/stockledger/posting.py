"""Post / reverse a mapped PT file into the append-only stock ledger.

Patna "Push into system" mints a gap-free `PT` voucher number for the Ranchi
warehouse and writes one inward `StockLedgerEntry` per KDPS row (qty = NAG/QTY,
value = BASIC × qty in paise). It can optionally reconcile against a Booking,
bumping each matched line's `inwarded_qty` (matched by style[DESIGN]+size).

A correction never edits: "Reverse posting" mints its own PT number and writes a
negative entry for every original inward row (append-only), and un-bumps the
booking — leaving the file back in 'sent' so it can be fixed and re-posted.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from core.documents import VoucherSeries
from finledger.posting import post_pt_vendor_bill, reverse_pt_vendor_bills
from masters.models import Store
from stockledger.models import StockLedgerEntry

WAREHOUSE_CODE = "RAN-WH"
DOC_TYPE = "PT"


def financial_year(d: date) -> str:
    """Indian FY (Apr–Mar) as `YY-YY`, e.g. Jun-2026 → '26-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _to_paise(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0


def _row_qty(data: dict) -> int:
    for key in ("NAG", "QTY"):
        v = data.get(key)
        if v in (None, ""):
            continue
        try:
            return int(Decimal(str(v)))
        except (InvalidOperation, ValueError):
            continue
    return 0


def _norm(s) -> str:
    return " ".join(str(s or "").split()).upper()


def _allocate_number() -> str:
    fy = financial_year(date.today())
    VoucherSeries.objects.get_or_create(fy=fy, store_code=WAREHOUSE_CODE, doc_type=DOC_TYPE)
    _, number = VoucherSeries.allocate(fy=fy, store_code=WAREHOUSE_CODE, doc_type=DOC_TYPE)
    return number


def _stock_entry_from_pt_row(row, store: Store, number: str, user, booking=None) -> StockLedgerEntry | None:
    data = row.data
    qty = _row_qty(data)
    if qty <= 0:
        return None
    unit_paise = _to_paise(data.get("BASIC"))
    return StockLedgerEntry(
        store=store,
        gstin=store.gstin,
        qty=qty,
        amount=unit_paise * qty,
        sku_code=str(data.get("BARCODE") or "")[:64],
        design=str(data.get("DESIGN") or "")[:120],
        color=str(data.get("COLOR") or "")[:60],
        size=str(data.get("SIZE") or "")[:24],
        brand=str(data.get("BRAND") or "")[:120],
        season=str(data.get("SEASON") or "")[:120],
        item=str(data.get("ITEM") or "")[:120],
        hsn=str(data.get("HSN") or "")[:24],
        kind=StockLedgerEntry.Kind.PT_INWARD,
        doc_number=number,
        line_no=row.line_no,
        pt_file=row.pt_file,
        booking=booking,
        posted_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _build_inward_entries(pt, store: Store, number: str, user, booking=None) -> list[StockLedgerEntry]:
    entries: list[StockLedgerEntry] = []
    for row in pt.rows.all():
        entry = _stock_entry_from_pt_row(row, store, number, user, booking)
        if entry is not None:
            entries.append(entry)
    return entries


def _mark_pt_posted(pt, number: str, booking=None) -> None:
    pt.stage = pt.Stage.POSTED
    pt.posted_at = timezone.now()
    pt.inward_doc_number = number
    pt.booking = booking
    pt.save(update_fields=["stage", "posted_at", "inward_doc_number", "booking", "updated_at"])


def _reconcile(booking, pt, sign: int) -> int:
    """Bump (+1) or un-bump (−1) booking line `inwarded_qty` by matched PT qty."""
    agg: dict[tuple[str, str], int] = defaultdict(int)
    for row in pt.rows.all():
        qty = _row_qty(row.data)
        if qty <= 0:
            continue
        agg[(_norm(row.data.get("DESIGN")), _norm(row.data.get("SIZE")))] += qty
    touched = 0
    for line in booking.lines.all():
        matched = agg.get((_norm(line.style_code), _norm(line.size)), 0)
        if matched:
            line.inwarded_qty = max(0, line.inwarded_qty + sign * matched)
            line.save(update_fields=["inwarded_qty", "updated_at"])
            touched += 1
    return touched


@transaction.atomic
def post_pt_inward(pt, user, booking=None) -> dict:
    """Write the inward stock-ledger entries for a sent PT file and lock it."""
    store = Store.objects.get(code=WAREHOUSE_CODE)
    number = _allocate_number()
    entries = _build_inward_entries(pt, store, number, user, booking)
    StockLedgerEntry.objects.bulk_create(entries)
    reconciled = _reconcile(booking, pt, sign=1) if booking is not None else 0
    total_value = sum(e.amount for e in entries)
    vendor_bill = post_pt_vendor_bill(pt, booking, total_value, user)
    _mark_pt_posted(pt, number, booking)
    return {
        "doc_number": number,
        "entries": len(entries),
        "reconciled_lines": reconciled,
        "vendor_bill": vendor_bill.doc_number if vendor_bill else None,
    }


@transaction.atomic
def reverse_pt_inward(pt, user) -> dict:
    """Append a negative mirror of every live inward row; return the file to 'sent'."""
    number = _allocate_number()
    originals = list(
        StockLedgerEntry.objects.filter(
            pt_file=pt,
            doc_number=pt.inward_doc_number,
            kind=StockLedgerEntry.Kind.PT_INWARD,
        )
    )
    reversals = [
        StockLedgerEntry(
            store=o.store,
            gstin=o.gstin,
            qty=-o.qty,
            amount=-o.amount,
            sku_code=o.sku_code,
            design=o.design,
            color=o.color,
            size=o.size,
            brand=o.brand,
            season=o.season,
            item=o.item,
            hsn=o.hsn,
            kind=StockLedgerEntry.Kind.PT_REVERSAL,
            doc_number=number,
            line_no=o.line_no,
            pt_file=pt,
            booking=o.booking,
            posted_by=user if getattr(user, "is_authenticated", False) else None,
        )
        for o in originals
    ]
    StockLedgerEntry.objects.bulk_create(reversals)
    if pt.booking_id:
        _reconcile(pt.booking, pt, sign=-1)
    vendor_reversed = reverse_pt_vendor_bills(pt, user)

    pt.stage = pt.Stage.SENT
    pt.posted_at = None
    pt.inward_doc_number = ""
    pt.booking = None
    pt.save(update_fields=["stage", "posted_at", "inward_doc_number", "booking", "updated_at"])
    return {"doc_number": number, "entries": len(reversals), "vendor_reversed": vendor_reversed}
