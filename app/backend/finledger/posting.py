"""Posting services for the vendor & cash ledgers.

These subledgers are append-only running balances *and* — since the F1 hardening —
every event also posts a **balanced value voucher** through the single kernel
posting engine (`core.post_entries`). So the value GL is the one book of record:
its `VENDOR_PAYABLE` control account equals the vendor subledger sum, and its
`CASH` control account equals the cash subledger sum. A vendor payment now clears
the payable against cash (`Dr VENDOR_PAYABLE / Cr CASH`) in the GL, not just in the
subledgers — the trial balance ties across inbound *and* money-out.

Gap-free voucher numbers are minted from `core.VoucherSeries` under a synthetic
store_code 'HO' (head office) — these ledgers are not store-scoped. Vendor doc_type
'VEND', cash doc_type 'CASH'. Corrections are append-only reversing rows (subledger)
plus the negated GL mirror.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.db import transaction

from core.documents import VoucherSeries
from core.gl import GLAccount, GLEntry
from core.posting import Leg, PostingRef, cr, dr, post_entries
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from masters.models import Brand

HO_CODE = "HO"
VENDOR_DOC = "VEND"
CASH_DOC = "CASH"

#: Which value-GL control account each cash-ledger account rolls up into.
#:
#: Cash and bank share one control account because the GL does not split them yet;
#: card and UPI have their own, because the customer has paid and the bank has not
#: settled, and the gap between the two is what the daily settlement reconciliation
#: is for. One map, used by everything that writes a cash row *and* by the
#: books-health tie - so the F1 reconciliation can be checked account by account
#: instead of as one lump total that a mis-file inside the family would hide.
CASH_CONTROL_ACCOUNTS: dict[str, str] = {
    CashLedgerEntry.Account.CASH: GLAccount.CASH,
    CashLedgerEntry.Account.BANK: GLAccount.CASH,
    CashLedgerEntry.Account.CARD: GLAccount.CARD_CLEARING,
    CashLedgerEntry.Account.UPI: GLAccount.UPI_CLEARING,
}


def gl_control_for(account: str) -> str:
    """The value account a cash-ledger account answers to.

    An account nobody has mapped answers to CASH, which is where every cash row
    went before this map existed - a row that fell through would otherwise have no
    control account at all and would break the tie rather than merely be filed
    coarsely.
    """
    return CASH_CONTROL_ACCOUNTS.get(account, GLAccount.CASH)


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


def _user(user: Any) -> Any:
    return user if getattr(user, "is_authenticated", False) else None


# --- GL bridge (F1: one balanced book of record) --------------------------


def _post_gl(doc_type: str, doc_number: str, legs, user) -> None:
    """Post one balanced GL voucher for a finledger event. Vendor/cash are HO-level,
    so no store/gstin dims. Balanced-or-fail via the single kernel posting engine."""
    ref = PostingRef(doc_type=doc_type, doc_number=doc_number, posted_by=_user(user))
    post_entries(ref, legs, posted_by=_user(user))


def _reverse_gl(orig_doc_number: str, rev_doc_number: str, doc_type: str, user) -> None:
    """Append the negated mirror of a finledger event's GL voucher, if it had one.

    A PT auto-bill has no GL leg on its VEND number (the PT path books the payable
    itself, then reverses it), and a payment's paired cash row has no GL leg on its
    CASH number (the GL cash leg lives on the vendor voucher) — in both cases there is
    nothing to mirror here, so this is a safe no-op that never double-reverses."""
    source = list(GLEntry.objects.filter(doc_number=orig_doc_number))
    if not source:
        return
    ref = PostingRef(doc_type=doc_type, doc_number=rev_doc_number, posted_by=_user(user))
    legs = [
        Leg(
            account=g.account,
            amount=-g.amount,
            party_type=g.party_type,
            party_code=g.party_code,
            against_voucher=g.against_voucher,
            memo=f"reversal of {orig_doc_number}",
        )
        for g in source
    ]
    post_entries(ref, legs, posted_by=_user(user))


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
    gl: bool = True,
) -> VendorLedgerEntry:
    """+amount: increases what we owe the vendor.

    ``gl=True`` (manual bill) also books the balanced value voucher
    Dr SUSPENSE / Cr VENDOR_PAYABLE, so the vendor subledger and the GL payable
    control account stay equal. The PT inward path passes ``gl=False`` because it
    books the payable itself (Dr INVENTORY / Cr VENDOR_PAYABLE); the finledger bill
    is then subledger detail only, so the payable is never double-booked.
    """
    entry = VendorLedgerEntry.objects.create(
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
    if gl and amount_paise:
        _post_gl(
            VENDOR_DOC,
            entry.doc_number,
            [
                dr(GLAccount.SUSPENSE, amount_paise, memo=description or "vendor bill"),
                cr(
                    GLAccount.VENDOR_PAYABLE,
                    amount_paise,
                    party_type="vendor",
                    party_code=vendor.code,
                    against_voucher=reference,
                ),
            ],
            user,
        )
    return entry


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
    """−amount on the vendor ledger; optionally a paired cash-out on the cash ledger.

    Also books ONE balanced GL voucher Dr VENDOR_PAYABLE / Cr CASH (or Cr SUSPENSE if
    the payment isn't paired to a cash movement). The paired cash subledger row is
    detail only — the GL cash leg lives on this voucher, so cash is booked once."""
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
    if amount_paise:
        # Paid out of whichever account the cash row named, so the payment relieves
        # the same control account the subledger row does.
        credit_account = gl_control_for(account) if also_cash else GLAccount.SUSPENSE
        _post_gl(
            VENDOR_DOC,
            entry.doc_number,
            [
                dr(
                    GLAccount.VENDOR_PAYABLE,
                    abs(amount_paise),
                    party_type="vendor",
                    party_code=vendor.code,
                ),
                cr(
                    credit_account,
                    abs(amount_paise),
                    memo=description or f"Payment to {vendor.name}",
                ),
            ],
            user,
        )
    return entry


@transaction.atomic
def reverse_vendor_entry(entry: VendorLedgerEntry, user) -> VendorLedgerEntry:
    """Append a negative mirror; also reverse a paired cash-out if one exists, and
    append the negated GL mirror of the entry's value voucher.

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
    _reverse_gl(entry.doc_number, number, VENDOR_DOC, user)
    return rev


def post_pt_vendor_bill(pt, booking, total_value_paise: int, user) -> VendorLedgerEntry | None:
    """Auto vendor liability when a PT file is posted against a booking — but ONLY
    for KDPS-owned goods (Outright / Correction). Brand-owned models never raise a
    payable from the PT: SOR accrues liability on the *Sale*, Consignment never does
    (CONTEXT.md commercial-model timing). The booking carries the snapshot.

    ``gl=False``: the PT inward already booked the payable in the value GL
    (Dr INVENTORY / Cr VENDOR_PAYABLE); this bill is the vendor subledger detail, so
    the payable is booked exactly once."""
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
        gl=False,
    )


def post_sale_sor_liability(
    vendor: Any, amount_paise: int, description: str, user: Any, *, reference: str = ""
) -> VendorLedgerEntry | None:
    """The SOR/consignment liability a *bill* raises, as vendor-subledger detail.

    Brand-owned stock raises nothing at the PT (`post_pt_vendor_bill` refuses it):
    the goods were never ours, so what we owe the brand is not known until a piece
    sells. It accrues here, at the settlement rate frozen on the piece - never at
    the price the customer happened to pay for it.

    Detail only, deliberately: the Sale's own cost event books the payable in the
    value GL (Dr COGS / Cr VENDOR_PAYABLE), so this row must not book it a second
    time. What it buys is that the vendor's account shows the accrual, and the
    subledger sum still equals the GL payable control account (F1).

    A negative amount is an exchange handing a brand-owned piece back inside the
    bill: what we owe falls, so the row is a reversal of accrual, not a bill.
    """
    if vendor is None or not amount_paise:
        return None
    return VendorLedgerEntry.objects.create(
        vendor=vendor,
        amount=amount_paise,
        kind=(VendorLedgerEntry.Kind.BILL if amount_paise > 0 else VendorLedgerEntry.Kind.REVERSAL),
        doc_number=_allocate(VENDOR_DOC),
        description=description,
        reference=reference,
        posted_by=_user(user),
    )


def post_sale_collection(
    *,
    account: str,
    amount_paise: int,
    doc_number: str,
    description: str,
    mode: str,
    user: Any,
) -> CashLedgerEntry:
    """One tender on a bill, as a cash-ledger receipt row.

    Projection only, and that is the whole point of it not going through
    `post_cash_movement`: the Sale's money event has already booked this tender in
    the value GL (Dr CASH / CARD_CLEARING / UPI_CLEARING), and that helper would
    book its own balanced voucher against SUSPENSE - the same rupees twice.

    The row carries the *bill's* number rather than a CASH-series one, because it
    is not an event of its own: it is what the bill collected, and the store's cash
    summary and the D4 three-way audit both want to get from a collection back to
    the bill that made it.
    """
    return CashLedgerEntry.objects.create(
        account=account,
        amount=abs(amount_paise),
        kind=CashLedgerEntry.Kind.RECEIPT,
        doc_number=doc_number,
        description=description,
        mode=mode,
        posted_by=_user(user),
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
    entry = CashLedgerEntry.objects.create(
        account=account or "CASH",
        amount=abs(amount_paise) if is_in else -abs(amount_paise),
        kind=CashLedgerEntry.Kind.RECEIPT if is_in else CashLedgerEntry.Kind.PAYMENT,
        doc_number=_allocate(CASH_DOC),
        description=description,
        mode=mode,
        posted_by=_user(user),
    )
    if amount_paise:
        # Standalone cash movement books against SUSPENSE — a holding account until it
        # is classified (to store collection / expense) in a later slice; keeps Σ=0.
        control = gl_control_for(entry.account)
        legs = (
            [
                dr(control, abs(amount_paise), memo=description),
                cr(GLAccount.SUSPENSE, abs(amount_paise), memo=description),
            ]
            if is_in
            else [
                dr(GLAccount.SUSPENSE, abs(amount_paise), memo=description),
                cr(control, abs(amount_paise), memo=description),
            ]
        )
        _post_gl(CASH_DOC, entry.doc_number, legs, user)
    return entry


@transaction.atomic
def reverse_cash_entry(entry: CashLedgerEntry, user) -> CashLedgerEntry:
    if entry.kind == CashLedgerEntry.Kind.REVERSAL:
        raise AlreadyReversedError("a reversal cannot itself be reversed")
    if CashLedgerEntry.objects.filter(reverses=entry).exists():
        raise AlreadyReversedError(f"{entry.doc_number} has already been reversed")
    number = _allocate(CASH_DOC)
    rev = CashLedgerEntry.objects.create(
        account=entry.account,
        amount=-entry.amount,
        kind=CashLedgerEntry.Kind.REVERSAL,
        doc_number=number,
        description=f"Reversal of {entry.doc_number}",
        mode=entry.mode,
        vendor=entry.vendor,
        link_doc=entry.doc_number,
        reverses=entry,
        posted_by=_user(user),
    )
    _reverse_gl(entry.doc_number, number, CASH_DOC, user)
    return rev
