"""The stock ledger — the first concrete business ledger over `core.LedgerEntry`.

Append-only (ADR-0004): a posting is only ever INSERTed; a correction is a *new*
today-dated reversing row, never an edit or delete (enforced by the ORM base, the
`BEFORE UPDATE OR DELETE` DB trigger, and a `REVOKE`). Each row is *self-describing*
— it carries its own SKU (barcode) + merchandising dimensions — so the ledger needs
no item master to be auditable. Inward qty is positive; a reversal is negative.
"""

from __future__ import annotations

from django.db import models

from core.ledger import LedgerEntry


class StockLedgerEntry(LedgerEntry):
    """One signed stock movement (barcode × store), with value in paise (`amount`)."""

    class Kind(models.TextChoices):
        PT_INWARD = "pt_inward", "PT inward"
        PT_REVERSAL = "pt_reversal", "PT reversal"

    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="stock_entries"
    )
    gstin = models.ForeignKey(
        "masters.Gstin", on_delete=models.PROTECT, related_name="stock_entries"
    )
    sku_code = models.CharField(max_length=64, db_index=True)  # barcode = SKU identity
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()  # signed: + inward, − reversal
    kind = models.CharField(max_length=16, choices=Kind.choices)
    doc_number = models.CharField(max_length=128, db_index=True)  # gap-free PT voucher
    line_no = models.IntegerField(default=0)
    pt_file = models.ForeignKey(
        "ptmapper.PtFile", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="stock_entries",
    )
    booking = models.ForeignKey(
        "vendors.Booking", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="stock_entries",
    )
    posted_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "stockledger_entry"
        ordering = ["-created_at", "line_no"]

    def __str__(self) -> str:
        return f"{self.doc_number} · {self.sku_code} × {self.qty}"
