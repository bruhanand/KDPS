"""Vendor (accounts-payable) and Cash ledgers — append-only over `core.LedgerEntry`.

Sign conventions (so a running Σ(amount) IS the balance):
  VendorLedgerEntry  +amount = we owe more (a bill/credit), −amount = a payment.
                     Σ = outstanding payable to that vendor.
  CashLedgerEntry    +amount = cash in (receipt),           −amount = cash out (payment).
                     Σ = cash on hand in that account.

Append-only (ADR-0004): every correction is a new today-dated reversing row, never
an edit/delete (ORM base + BEFORE UPDATE/DELETE trigger + REVOKE).
"""

from __future__ import annotations

from django.db import models

from core.ledger import LedgerEntry


class VendorLedgerEntry(LedgerEntry):
    class Kind(models.TextChoices):
        BILL = "bill", "Bill / purchase"
        PAYMENT = "payment", "Payment"
        REVERSAL = "reversal", "Reversal"

    vendor = models.ForeignKey(
        "vendors.Vendor", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    doc_number = models.CharField(max_length=128, db_index=True)
    description = models.CharField(max_length=240, blank=True, default="")
    reference = models.CharField(max_length=120, blank=True, default="")  # vendor invoice no etc.
    mode = models.CharField(max_length=24, blank=True, default="")  # cash / bank / upi (payments)
    pt_file = models.ForeignKey(
        "ptmapper.PtFile", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="vendor_entries",
    )
    booking = models.ForeignKey(
        "vendors.Booking", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="vendor_entries",
    )
    posted_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "finledger_vendor_entry"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.doc_number} · {self.vendor_id} · {self.amount}"


class CashLedgerEntry(LedgerEntry):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt (cash in)"
        PAYMENT = "payment", "Payment (cash out)"
        REVERSAL = "reversal", "Reversal"

    account = models.CharField(max_length=24, default="CASH")  # CASH / BANK / UPI …
    kind = models.CharField(max_length=12, choices=Kind.choices)
    doc_number = models.CharField(max_length=128, db_index=True)
    description = models.CharField(max_length=240, blank=True, default="")
    mode = models.CharField(max_length=24, blank=True, default="")
    vendor = models.ForeignKey(
        "vendors.Vendor", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="cash_entries",
    )  # set when this cash-out pays a vendor
    link_doc = models.CharField(max_length=128, blank=True, default="")  # paired vendor doc_number
    posted_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "finledger_cash_entry"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.doc_number} · {self.account} · {self.amount}"
