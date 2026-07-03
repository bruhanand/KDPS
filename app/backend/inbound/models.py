"""Receiving against a booking — the GRN (Goods Receipt Note).

The booking's order list pre-fills a confirm-and-adjust GRN; a booking can have
many GRNs (stock arrives in lots). Goods can also be received with NO booking at
all (direct receipt, branded too). Store-delivered receipts hand off to the
Ranchi warehouse; the warehouse later makes the PT and the Patna HO office
inwards it (those are the next slice, D→E)."""

from __future__ import annotations

from django.db import models

from core.base import TimeStampedModel
from core.documents import Document
from core.fiscal import financial_year


class Grn(Document):
    """Goods Receipt Note — a document (ADR-0004): created as a draft, then `post()`
    mints its gap-free `{FY}/{store}/GRN/{n}` number and freezes it. A receipt is an
    immutable fact; corrections are new documents, never edits."""

    class Status(models.TextChoices):
        """The D2 receiving lifecycle (received → sent_to_ho → inwarded). NOT a stored
        column: a GRN is posted (frozen) the moment it exists, and the docstatus FSM
        forbids updating a submitted row — so where the arrival sits in the process is
        *derived* from its linked PT files (see ``effective_status``), never written."""

        RECEIVED = "received", "Received"
        SENT_TO_HO = "sent_to_ho", "Sent to HO (Patna)"
        INWARDED = "inwarded", "Inwarded"

    class ReceivedAt(models.TextChoices):
        STORE = "store", "Store"
        WAREHOUSE = "warehouse", "Warehouse"

    booking = models.ForeignKey(
        "vendors.Booking", null=True, blank=True, on_delete=models.SET_NULL, related_name="grns"
    )
    vendor = models.ForeignKey(
        "vendors.Vendor", null=True, blank=True, on_delete=models.SET_NULL, related_name="grns"
    )
    vendor_name_raw = models.CharField(max_length=160, blank=True, default="")
    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="grns")
    received_at = models.CharField(
        max_length=12, choices=ReceivedAt.choices, default=ReceivedAt.STORE
    )
    is_direct = models.BooleanField(default=False)  # booking-less receipt
    invoice_number = models.CharField(max_length=80, blank=True, default="")
    invoice_file = models.ForeignKey(
        "files.StoredFile", null=True, blank=True, on_delete=models.SET_NULL
    )
    notes = models.CharField(max_length=400, blank=True, default="")
    received_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta(Document.Meta):
        db_table = "inbound_grn"
        ordering = ["-created_at"]

    def series_lookup(self) -> tuple[str, str, str]:
        return financial_year(), self.store.code, "GRN"

    @property
    def effective_status(self) -> str:
        """Where this arrival sits in the D2 flow, derived from its live (non-reversed)
        PT files: one posted → ``inwarded``; one sent to Patna → ``sent_to_ho``; else
        ``received`` (a recalled or reversed PT rolls the arrival straight back).
        Duck-types on ``PtFile.stage`` so inbound never imports ptmapper. Callers
        should ``prefetch_related("pt_files")``."""
        stages = {p.stage for p in self.pt_files.all()}
        if "posted" in stages:
            return self.Status.INWARDED
        if "sent" in stages:
            return self.Status.SENT_TO_HO
        return self.Status.RECEIVED

    @property
    def effective_status_label(self) -> str:
        return self.Status(self.effective_status).label

    def __str__(self) -> str:
        return self.doc_number or f"GRN draft #{self.pk}"


class GrnLine(TimeStampedModel):
    grn = models.ForeignKey(Grn, on_delete=models.CASCADE, related_name="lines")
    booking_line = models.ForeignKey(
        "vendors.BookingLine", null=True, blank=True, on_delete=models.SET_NULL
    )
    style_code = models.CharField(max_length=80)
    size = models.CharField(max_length=24, blank=True, default="")
    color = models.CharField(max_length=40, blank=True, default="")
    barcode = models.CharField(max_length=40, blank=True, default="")
    received_qty = models.IntegerField(default=0)
    damaged_qty = models.IntegerField(default=0)
    is_variance = models.BooleanField(default=False)  # not on the booking / over-receipt
    remark = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.style_code}/{self.size} × {self.received_qty}"
