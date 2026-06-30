"""Posting services for the vendor & cash ledgers (the only writers of these tables).

Gap-free voucher numbers are minted from `core.VoucherSeries` under a synthetic
store_code 'HO' (head office) — these ledgers are not store-scoped. Vendor doc_type
'VEND', cash doc_type 'CASH'. Corrections are append-only reversing rows.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from core.documents import VoucherSeries
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from masters.models import Brand

HO_CODE = "HO"
VENDOR_DOC = "VEND"
CASH_DOC = "CASH"


class AlreadyReversedError(Exception):
    """A ledger entry that already has a live reversal cannot be reversed again
    (a second reversal would over-credit the vendor / over-pay the cash account)."""


def financial_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def rupees_to_paise(value) -> int:
    """Tolerant rupee→paise (accepts str/Decimal/number; never lets float into money)."""
    if value in (None, ""):
        return 0
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0


def _allocate(doc_type: str) -> str:
    fy = financial_year(date.today())
    VoucherSeries.objects.get_or_create(fy=fy, store_code=HO_CODE, doc_type=doc_type)
    _, number = VoucherSeries.allocate(fy=fy, store_code=HO_CODE, doc_type=doc_type)
    return number


def _user(user):
    return user if getattr(user, "is_authenticated", False) else None


# --- Vendor ledger ---------------------------------------------------------


@transaction.atomic
def post_vendor_bill(
    vendor,
    amount_paise: int,
    description: str,
    user,
    *,
    pt_file=None,
    booking=None,
    reference: str = "",
) -> VendorLedgerEntry:
    """+amount: increases what we owe the vendor."""
    return VendorLedgerEntry.objects.create(
        vendor=vendor,
        amount=amount_paise,
        kind=VendorLedgerEntry.Kind.BILL,
        doc_number=_allocate(VENDOR_DOC),
        description=description,
        reference=reference,
        pt_file=pt_file,
        booking=booking,
        posted_by=_user(user),
    )


@transaction.atomic
def post_vendor_payment(
    vendor,
    amount_paise: int,
    description: str,
    user,
    *,
    mode: str = "",
    account: str = "CASH",
    also_cash: bool = True,
) -> VendorLedgerEntry:
    """−amount on the vendor ledger; optionally a paired cash-out on the cash ledger."""
    entry = VendorLedgerEntry.objects.create(
        vendor=vendor,
        amount=-abs(amount_paise),
        kind=VendorLedgerEntry.Kind.PAYMENT,
        doc_number=_allocate(VENDOR_DOC),
        description=description,
        mode=mode,
        posted_by=_user(user),
    )
    if also_cash and amount_paise:
        CashLedgerEntry.objects.create(
            account=account,
            amount=-abs(amount_paise),
            kind=CashLedgerEntry.Kind.PAYMENT,
            doc_number=_allocate(CASH_DOC),
            description=description or f"Payment to {vendor.name}",
            mode=mode,
            vendor=vendor,
            link_doc=entry.doc_number,
            posted_by=_user(user),
        )
    return entry


@transaction.atomic
def reverse_vendor_entry(entry: VendorLedgerEntry, user) -> VendorLedgerEntry:
    """Append a negative mirror; also reverse a paired cash-out if one exists.

    Refuses to reverse a reversal, or to reverse the same entry twice (a second
    reversal would over-credit the vendor)."""
    if entry.kind == VendorLedgerEntry.Kind.REVERSAL:
        raise AlreadyReversedError("a reversal cannot itself be reversed")
    if VendorLedgerEntry.objects.filter(reverses=entry).exists():
        raise AlreadyReversedError(f"{entry.doc_number} has already been reversed")
    number = _allocate(VENDOR_DOC)
    rev = VendorLedgerEntry.objects.create(
        vendor=entry.vendor,
        amount=-entry.amount,
        kind=VendorLedgerEntry.Kind.REVERSAL,
        doc_number=number,
        description=f"Reversal of {entry.doc_number}",
        pt_file=entry.pt_file,
        booking=entry.booking,
        reverses=entry,
        posted_by=_user(user),
    )
    for cash in CashLedgerEntry.objects.filter(
        link_doc=entry.doc_number, kind=CashLedgerEntry.Kind.PAYMENT
    ):
        if CashLedgerEntry.objects.filter(reverses=cash).exists():
            continue  # this paired cash-out was already reversed
        CashLedgerEntry.objects.create(
            account=cash.account,
            amount=-cash.amount,
            kind=CashLedgerEntry.Kind.REVERSAL,
            doc_number=_allocate(CASH_DOC),
            description=f"Reversal of {cash.doc_number}",
            mode=cash.mode,
            vendor=cash.vendor,
            link_doc=number,
            reverses=cash,
            posted_by=_user(user),
        )
    return rev


def post_pt_vendor_bill(pt, booking, total_value_paise: int, user) -> VendorLedgerEntry | None:
    """Auto vendor liability when a PT file is posted against a booking — but ONLY
    for KDPS-owned goods (Outright / Correction). Brand-owned models never raise a
    payable from the PT: SOR accrues liability on the *Sale*, Consignment never does
    (CONTEXT.md commercial-model timing). The booking carries the snapshot."""
    if booking is None or total_value_paise <= 0:
        return None
    if booking.ownership != Brand.Ownership.OWNED:
        return None
    return post_vendor_bill(
        booking.vendor,
        total_value_paise,
        f"PT inward {pt.original_filename}",
        user,
        pt_file=pt,
        booking=booking,
        reference=booking.number,
    )


@transaction.atomic
def reverse_pt_vendor_bills(pt, user) -> int:
    """Reverse the live auto-bills raised for a PT file (called on PT reversal)."""
    count = 0
    for entry in VendorLedgerEntry.objects.filter(pt_file=pt, kind=VendorLedgerEntry.Kind.BILL):
        if VendorLedgerEntry.objects.filter(reverses=entry).exists():
            continue  # already reversed — never double-reverse
        reverse_vendor_entry(entry, user)
        count += 1
    return count


# --- Cash ledger -----------------------------------------------------------


@transaction.atomic
def post_cash_movement(
    direction: str,
    amount_paise: int,
    description: str,
    user,
    *,
    account: str = "CASH",
    mode: str = "",
) -> CashLedgerEntry:
    is_in = direction == "in"
    return CashLedgerEntry.objects.create(
        account=account or "CASH",
        amount=abs(amount_paise) if is_in else -abs(amount_paise),
        kind=CashLedgerEntry.Kind.RECEIPT if is_in else CashLedgerEntry.Kind.PAYMENT,
        doc_number=_allocate(CASH_DOC),
        description=description,
        mode=mode,
        posted_by=_user(user),
    )


@transaction.atomic
def reverse_cash_entry(entry: CashLedgerEntry, user) -> CashLedgerEntry:
    if entry.kind == CashLedgerEntry.Kind.REVERSAL:
        raise AlreadyReversedError("a reversal cannot itself be reversed")
    if CashLedgerEntry.objects.filter(reverses=entry).exists():
        raise AlreadyReversedError(f"{entry.doc_number} has already been reversed")
    return CashLedgerEntry.objects.create(
        account=entry.account,
        amount=-entry.amount,
        kind=CashLedgerEntry.Kind.REVERSAL,
        doc_number=_allocate(CASH_DOC),
        description=f"Reversal of {entry.doc_number}",
        mode=entry.mode,
        vendor=entry.vendor,
        link_doc=entry.doc_number,
        reverses=entry,
        posted_by=_user(user),
    )
