"""Golden tests for the F1 hardening: vendor & cash subledgers are unified into
the single balanced value GL (`core.post_entries`).

The invariants proven here are the "books tie" contract:
  * every finledger event posts a *balanced* voucher, so the whole GL trial
    balance stays exactly ₹0 (`trial_balance() == 0`);
  * the GL `VENDOR_PAYABLE` control account equals the vendor subledger sum
    (Σ vendor rows == −GL payable, since payable is credit-side);
  * the GL `CASH` control account equals the cash subledger sum (same sign);
  * a PT auto-bill (`gl=False`) posts NO GL voucher of its own — the PT inward
    already booked the payable — so the payable is never double-booked.

Hermetic (`db` fixture), so it runs in CI's `pytest tests` step.
"""

from __future__ import annotations

from django.db.models import Sum

from accounts.models import User
from core.gl import GLAccount, GLEntry, account_balance, trial_balance
from core.posting import PostingRef, cr, dr, post_entries
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from finledger.posting import (
    post_cash_movement,
    post_vendor_bill,
    post_vendor_payment,
    reverse_vendor_entry,
)
from vendors.models import Vendor


def _head_office_actor() -> User:
    return User.objects.create(
        username="f1-head-office", full_name="F1 Head Office", scope_type="all"
    )


def _vendor_subledger_total() -> int:
    return VendorLedgerEntry.objects.aggregate(b=Sum("amount"))["b"] or 0


def _cash_subledger_total() -> int:
    return CashLedgerEntry.objects.aggregate(b=Sum("amount"))["b"] or 0


def _assert_reconciled() -> None:
    """The books-tie invariant that the F1 fix guarantees."""
    # Whole-ledger checksum: every voucher balances, so their sum is 0.
    assert trial_balance() == 0
    # Payable is credit-side (negative paise), the subledger is +ve when we owe.
    assert _vendor_subledger_total() == -account_balance(GLAccount.VENDOR_PAYABLE)
    # Cash is an asset (debit +), same sign as the cash subledger.
    assert _cash_subledger_total() == account_balance(GLAccount.CASH)


def test_manual_bill_posts_balanced_payable_and_reconciles(db):
    vendor = Vendor.objects.create(code="f1v1", name="F1 Vendor 1")
    post_vendor_bill(vendor, 12345, "manual bill", _head_office_actor())

    # Balanced voucher: Dr SUSPENSE / Cr VENDOR_PAYABLE.
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -12345
    assert account_balance(GLAccount.SUSPENSE) == 12345
    assert _vendor_subledger_total() == 12345
    _assert_reconciled()


def test_payment_clears_payable_against_cash_and_reconciles(db):
    vendor = Vendor.objects.create(code="f1v2", name="F1 Vendor 2")
    actor = _head_office_actor()
    post_vendor_bill(vendor, 50000, "bill", actor)
    post_vendor_payment(vendor, 20000, "part payment", actor)

    # Payment fans Dr VENDOR_PAYABLE / Cr CASH on ONE voucher; a paired cash-out
    # row lands in the cash subledger (detail only — GL cash leg is on this voucher).
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -30000  # 50000 billed − 20000 paid
    assert account_balance(GLAccount.CASH) == -20000
    assert _vendor_subledger_total() == 30000
    assert _cash_subledger_total() == -20000
    assert CashLedgerEntry.objects.filter(kind=CashLedgerEntry.Kind.PAYMENT).count() == 1
    _assert_reconciled()


def test_payment_without_cash_leg_uses_suspense(db):
    vendor = Vendor.objects.create(code="f1v3", name="F1 Vendor 3")
    actor = _head_office_actor()
    post_vendor_bill(vendor, 40000, "bill", actor)
    post_vendor_payment(vendor, 40000, "settled off-cash", actor, also_cash=False)

    # No cash movement: the GL credit lands in SUSPENSE, cash untouched, books still tie.
    assert account_balance(GLAccount.VENDOR_PAYABLE) == 0
    assert account_balance(GLAccount.CASH) == 0
    assert CashLedgerEntry.objects.count() == 0
    _assert_reconciled()


def test_standalone_cash_movement_reconciles(db):
    post_cash_movement("in", 75000, "opening float", None)
    assert account_balance(GLAccount.CASH) == 75000
    assert account_balance(GLAccount.SUSPENSE) == -75000
    assert _cash_subledger_total() == 75000
    _assert_reconciled()

    post_cash_movement("out", 25000, "petty spend", None)
    assert account_balance(GLAccount.CASH) == 50000
    assert _cash_subledger_total() == 50000
    _assert_reconciled()


def test_reversal_mirrors_gl_and_keeps_books_tied(db):
    vendor = Vendor.objects.create(code="f1v4", name="F1 Vendor 4")
    actor = _head_office_actor()
    bill = post_vendor_bill(vendor, 60000, "bill", actor)
    payment = post_vendor_payment(vendor, 60000, "payment", actor)
    _assert_reconciled()

    reverse_vendor_entry(payment, actor)  # unwind the payment (and its paired cash row)
    reverse_vendor_entry(bill, actor)  # unwind the bill

    # Everything nets back to zero across both books.
    assert account_balance(GLAccount.VENDOR_PAYABLE) == 0
    assert account_balance(GLAccount.CASH) == 0
    assert _vendor_subledger_total() == 0
    assert _cash_subledger_total() == 0
    _assert_reconciled()


def test_pt_auto_bill_does_not_double_book_the_payable(db):
    """The PT inward books Dr INVENTORY / Cr VENDOR_PAYABLE itself; the finledger
    auto-bill is subledger detail only (`gl=False`) so the payable is booked once."""
    vendor = Vendor.objects.create(code="f1v5", name="F1 Vendor 5")
    actor = _head_office_actor()

    # Simulate the PT inward value voucher (as stockledger.post_value_gl would).
    ref = PostingRef(doc_type="PT", doc_number="PT-0001")
    post_entries(
        ref,
        [
            dr(GLAccount.INVENTORY, 90000, brand="ACME", season="SS26"),
            cr(GLAccount.VENDOR_PAYABLE, 90000, party_type="vendor", party_code=vendor.code),
        ],
        posted_by=actor,
    )
    # The finledger auto-bill for the same goods — MUST NOT post its own GL voucher.
    entry = post_vendor_bill(
        vendor, 90000, "PT inward auto-bill", actor, reference="BK-1", gl=False
    )
    assert GLEntry.objects.filter(doc_number=entry.doc_number).count() == 0

    # Payable booked exactly once (−90000), inventory once (+90000), books tie,
    # and the subledger still reconciles to the single GL payable.
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -90000
    assert account_balance(GLAccount.INVENTORY) == 90000
    assert _vendor_subledger_total() == 90000
    _assert_reconciled()
