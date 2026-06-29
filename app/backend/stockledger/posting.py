"""Post / reverse a mapped PT file into the append-only stock ledger AND the value
general ledger (ADR-0006 — one event, two books).

Patna "Push into system" mints a gap-free `PT` voucher for the Ranchi warehouse and:
  * writes one inward `StockLedgerEntry` per KDPS row (quantity + value),
  * **values stock at P RATE** — the locked unit cost frozen at the PT, never the
    ex-GST BASIC — and refuses any row where P RATE > MRP or the cost is unreadable
    (strict money: a bad cell blocks the post, it never silently values at ₹0),
  * posts a **balanced** value voucher via `core.post_entries`, branching by the
    booking's commercial model (Rule 3 snapshot):
        - Outright / Correction (KDPS-owned) → Dr INVENTORY / Cr VENDOR_PAYABLE,
        - SOR / Consignment (brand-owned)     → Dr SOR_STOCK / Cr SOR_CONTRA
                                                 (off-book; NEVER a payable at PT),
        - direct receipt (no booking)         → Dr INVENTORY / Cr GRNI.

A correction never edits: "Reverse posting" mints its own PT number, writes the
negative mirror of every inward stock row AND the reversing value voucher, reverses
any vendor bill, and un-bumps the booking — leaving the file back in 'sent'.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from core.gl import GLAccount, GLEntry
from core.posting import Leg, PostingRef, cr, dr, post_entries
from finledger.posting import post_pt_vendor_bill, reverse_pt_vendor_bills
from masters.models import Brand, Store
from stockledger.models import StockLedgerEntry

WAREHOUSE_CODE = "RAN-WH"
DOC_TYPE = "PT"
OWNED = Brand.Ownership.OWNED


class PtPostingError(Exception):
    """A PT file cannot be posted as-is (unreadable/missing cost, or P RATE > MRP).

    Surfaced to the API as a 422 listing the offending rows — the warehouse fixes
    the data and re-sends, rather than the engine silently valuing stock at zero.
    """


def financial_year(d: date) -> str:
    """Indian FY (Apr–Mar) as `YY-YY`, e.g. Jun-2026 → '26-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _decimal(value) -> Decimal | None:
    """Strict rupee cell → Decimal (None if blank). Raises on garbage — no silent 0."""
    if value in (None, ""):
        return None
    return Decimal(str(value).replace(",", "").strip())


def _rupees_to_paise(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _unit_cost_paise(data: dict, line_no: int) -> int:
    """Unit cost in paise = P RATE (the locked cost), falling back to BASIC only if
    P RATE is absent. Enforces P RATE ≤ MRP. Raises PtPostingError on a bad cost."""
    try:
        prate = _decimal(data.get("P RATE"))
        basic = _decimal(data.get("BASIC"))
        mrp = _decimal(data.get("MRP"))
    except (InvalidOperation, ValueError, ArithmeticError):
        raise PtPostingError(f"row {line_no}: unreadable price cell (P RATE / BASIC / MRP)")
    cost = prate if (prate is not None and prate > 0) else basic
    if cost is None or cost <= 0:
        raise PtPostingError(f"row {line_no}: missing P RATE / BASIC — cannot value the stock")
    if mrp is not None and mrp > 0 and cost > mrp:
        raise PtPostingError(f"row {line_no}: cost {cost} exceeds MRP {mrp} (P RATE ≤ MRP)")
    return _rupees_to_paise(cost)


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
    from core.documents import VoucherSeries

    fy = financial_year(date.today())
    VoucherSeries.objects.get_or_create(fy=fy, store_code=WAREHOUSE_CODE, doc_type=DOC_TYPE)
    _, number = VoucherSeries.allocate(fy=fy, store_code=WAREHOUSE_CODE, doc_type=DOC_TYPE)
    return number


def _stock_entry_from_pt_row(row, store: Store, number: str, unit_paise: int, qty: int, user, booking=None) -> StockLedgerEntry:
    data = row.data
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
    """Value every positive-qty row at P RATE; raise (blocking the whole post) if any
    row has an unreadable/missing cost or P RATE > MRP."""
    entries: list[StockLedgerEntry] = []
    issues: list[str] = []
    for row in pt.rows.all():
        qty = _row_qty(row.data)
        if qty <= 0:
            continue
        try:
            unit_paise = _unit_cost_paise(row.data, row.line_no)
        except PtPostingError as exc:
            issues.append(str(exc))
            continue
        entries.append(_stock_entry_from_pt_row(row, store, number, unit_paise, qty, user, booking))
    if issues:
        raise PtPostingError("Cannot post — fix these rows first:\n" + "\n".join(issues))
    return entries


def _model_label(booking) -> str:
    return booking.brand.commercial_label if booking is not None else "Direct receipt"


def _post_value_gl(pt, store: Store, number: str, booking, total_value_paise: int, user) -> bool:
    """Post the balanced value voucher for this inward, branching by commercial model."""
    if total_value_paise <= 0:
        return False
    ref = PostingRef(
        doc_type=DOC_TYPE, doc_number=number, store=store, gstin=store.gstin, posted_by=user
    )
    brand = booking.brand.name if booking is not None else ""
    season = booking.season.name if booking is not None else ""
    if booking is None:
        legs = [
            dr(GLAccount.INVENTORY, total_value_paise, brand=brand, season=season),
            cr(GLAccount.GRNI, total_value_paise, memo=f"PT inward {pt.original_filename}"),
        ]
    elif booking.ownership == OWNED:  # Outright / Correction → on-book asset + payable
        legs = [
            dr(GLAccount.INVENTORY, total_value_paise, brand=brand, season=season),
            cr(GLAccount.VENDOR_PAYABLE, total_value_paise, party_type="vendor",
               party_code=booking.vendor.code, against_voucher=booking.number),
        ]
    else:  # SOR / Consignment → brand-owned, off-book memo, NEVER a payable from the PT
        legs = [
            dr(GLAccount.SOR_STOCK, total_value_paise, brand=brand, season=season),
            cr(GLAccount.SOR_CONTRA, total_value_paise, brand=brand, season=season),
        ]
    post_entries(ref, legs, posted_by=user)
    return True


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


def _mark_pt_posted(pt, number: str, booking=None) -> None:
    from django.utils import timezone

    pt.stage = pt.Stage.POSTED
    pt.posted_at = timezone.now()
    pt.inward_doc_number = number
    pt.booking = booking
    pt.save(update_fields=["stage", "posted_at", "inward_doc_number", "booking", "updated_at"])


@transaction.atomic
def post_pt_inward(pt, user, booking=None) -> dict:
    """Write the inward stock-ledger + value-GL entries for a sent PT file and lock it.

    Raises `PtPostingError` (rolling back everything) if any row cannot be valued.
    """
    store = Store.objects.get(code=WAREHOUSE_CODE)
    number = _allocate_number()
    entries = _build_inward_entries(pt, store, number, user, booking)
    StockLedgerEntry.objects.bulk_create(entries)
    reconciled = _reconcile(booking, pt, sign=1) if booking is not None else 0
    total_value = sum(e.amount for e in entries)
    _post_value_gl(pt, store, number, booking, total_value, user)
    vendor_bill = post_pt_vendor_bill(pt, booking, total_value, user)
    _mark_pt_posted(pt, number, booking)
    return {
        "doc_number": number,
        "entries": len(entries),
        "reconciled_lines": reconciled,
        "commercial_model": _model_label(booking),
        "stock_value_paise": total_value,
        "vendor_bill": vendor_bill.doc_number if vendor_bill else None,
    }


def _reverse_value_gl(original_number: str, reversal_number: str, store: Store, user) -> bool:
    """Append the negated mirror of the original value voucher (balanced reversal)."""
    source = list(GLEntry.objects.filter(doc_number=original_number))
    if not source:
        return False
    ref = PostingRef(
        doc_type=DOC_TYPE, doc_number=reversal_number, store=store, gstin=store.gstin, posted_by=user
    )
    legs = [
        Leg(
            account=g.account, amount=-g.amount, store=g.store, gstin=g.gstin,
            brand=g.brand, season=g.season, party_type=g.party_type,
            party_code=g.party_code, against_voucher=g.against_voucher,
            memo=f"reversal of {original_number}",
        )
        for g in source
    ]
    post_entries(ref, legs, posted_by=user)
    return True


@transaction.atomic
def reverse_pt_inward(pt, user) -> dict:
    """Append a negative mirror of every live inward row + value voucher; return the
    file to 'sent'."""
    store = Store.objects.get(code=WAREHOUSE_CODE)
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
            store=o.store, gstin=o.gstin, qty=-o.qty, amount=-o.amount,
            sku_code=o.sku_code, design=o.design, color=o.color, size=o.size,
            brand=o.brand, season=o.season, item=o.item, hsn=o.hsn,
            kind=StockLedgerEntry.Kind.PT_REVERSAL, doc_number=number, line_no=o.line_no,
            pt_file=pt, booking=o.booking,
            posted_by=user if getattr(user, "is_authenticated", False) else None,
        )
        for o in originals
    ]
    StockLedgerEntry.objects.bulk_create(reversals)
    _reverse_value_gl(pt.inward_doc_number, number, store, user)
    if pt.booking_id:
        _reconcile(pt.booking, pt, sign=-1)
    vendor_reversed = reverse_pt_vendor_bills(pt, user)

    pt.stage = pt.Stage.SENT
    pt.posted_at = None
    pt.inward_doc_number = ""
    pt.booking = None
    pt.save(update_fields=["stage", "posted_at", "inward_doc_number", "booking", "updated_at"])
    return {"doc_number": number, "entries": len(reversals), "vendor_reversed": vendor_reversed}
