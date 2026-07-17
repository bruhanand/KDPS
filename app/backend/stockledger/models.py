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
from core.money import MoneyField


class StockLedgerEntry(LedgerEntry):
    """One signed stock movement (barcode × store), with value in paise (`amount`)."""

    class Kind(models.TextChoices):
        PT_INWARD = "pt_inward", "PT inward"
        PT_REVERSAL = "pt_reversal", "PT reversal"
        # Outbound kinds (Sprint 1)
        TRANSFER_OUT = "transfer_out", "Transfer out"
        TRANSFER_IN = "transfer_in", "Transfer in"
        RTV_OUT = "rtv_out", "RTV out"
        SEASONAL_RET = "seasonal_ret", "Seasonal return"
        ADJUSTMENT = "adjustment", "Adjustment"
        WRITE_OFF = "write_off", "Write-off"
        VFLIP_OUT = "vflip_out", "V-flip out"
        VFLIP_IN = "vflip_in", "V-flip in"

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
        "ptmapper.PtFile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_entries",
    )
    booking = models.ForeignKey(
        "vendors.Booking",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_entries",
    )
    posted_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = "stockledger_entry"
        ordering = ["-created_at", "line_no"]

    def __str__(self) -> str:
        return f"{self.doc_number} · {self.sku_code} × {self.qty}"


class StockOnHand(models.Model):
    """Materialised net stock position per (store × barcode) — a fast, indexed
    projection of the append-only ledger, maintained INSIDE each post/reverse
    transaction and fully rebuildable (`manage.py rebuild_stock_on_hand`). It is a
    cache, never the source of truth: the ledger is. Mutable (no append-only
    trigger) so it can be updated/rebuilt."""

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="on_hand")
    gstin = models.ForeignKey(
        "masters.Gstin",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="on_hand",
    )
    sku_code = models.CharField(max_length=64, db_index=True)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    net_qty = models.IntegerField(default=0)
    net_value_paise = MoneyField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stockledger_on_hand"
        ordering = ["brand", "-net_qty"]
        constraints = [
            models.UniqueConstraint(fields=["store", "sku_code"], name="uq_on_hand_store_sku"),
        ]
        indexes = [
            models.Index(fields=["brand"], name="onhand_brand_idx"),
            models.Index(fields=["season"], name="onhand_season_idx"),
            models.Index(fields=["net_qty"], name="onhand_net_qty_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.store_id}/{self.sku_code} = {self.net_qty}"
