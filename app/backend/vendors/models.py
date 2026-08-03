"""Branded Vendor master (minimal, v1) + Booking.

A vendor is the company KDPS buys from; one vendor carries many brands, and the
commercial model lives on the brand (masters.Brand). A Booking is one vendor +
one brand + one season (never mixed) tracked from order → delivery → close.
Lines are style-code → size → quantity (no colour at booking — deliberate);
price/MRP is optional and indicative. The brand's commercial model is snapshotted
onto the booking (Rule 3) and is overridable here.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.utils import timezone

from core.base import TimeStampedModel
from core.money import MoneyField
from masters.models import Brand


class Vendor(TimeStampedModel):
    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=160)
    city = models.CharField(max_length=80, blank=True, default="")
    gstin = models.CharField(max_length=15, blank=True, default="")
    state_code = models.CharField(max_length=2, blank=True, default="")
    state_name = models.CharField(max_length=40, blank=True, default="")
    pan = models.CharField(max_length=10, blank=True, default="")
    payment_terms = models.CharField(max_length=120, blank=True, default="")
    brands = models.ManyToManyField(Brand, blank=True, related_name="vendors")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Booking(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        BOOKED = "booked", "Booked"
        PARTIALLY_RECEIVED = "partially_received", "Partially received"
        RECEIVED = "received", "Received"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=32, unique=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="bookings")
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="bookings")
    season = models.ForeignKey("masters.Season", on_delete=models.PROTECT, related_name="bookings")
    destination_store = models.ForeignKey(
        "masters.Store",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bookings",
        help_text="Where the goods are expected to land (store delivery). Null = warehouse/HO.",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    vendor_ref = models.CharField(max_length=80, blank=True, default="")
    # commercial model snapshot (defaulted from brand, overridable on the booking)
    ownership = models.CharField(max_length=12, default="")
    return_terms = models.CharField(max_length=12, default="")
    estimated_value_paise = MoneyField(null=True, blank=True)
    notes = models.CharField(max_length=400, blank=True, default="")
    source_file = models.ForeignKey(
        "files.StoredFile", null=True, blank=True, on_delete=models.SET_NULL
    )
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    # How a commitment ends. Every ERP needs the short-close: the season is over,
    # 40 of 100 pieces came, and the other 60 never will. Without this the
    # booking sits at "Partially received" for ever, the open-order report reads
    # 60 pieces that are not coming, and the only ways out are editing the
    # quantity (which rewrites history) or ignoring the row. So: an explicit end,
    # with a reason, an actor and a time. `recompute_status` already refuses to
    # reopen a closed booking, so a late receipt cannot undo the decision.
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bookings_closed",
    )
    close_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.number

    @property
    def is_open(self) -> bool:
        return self.status not in (self.Status.CLOSED, self.Status.CANCELLED)

    @property
    def received_total(self) -> int:
        return sum(line.received_qty for line in self.lines.all())

    @property
    def open_qty(self) -> int:
        """Pieces ordered and not yet received — what a short-close writes off."""
        return max(sum(line.booked_qty - line.received_qty for line in self.lines.all()), 0)

    def end(self, *, user: Any, reason: str, cancel: bool = False) -> None:
        """Short-close (or cancel) the booking. Callers check the rung; this
        enforces the two facts of the document itself: a cancellation is only
        honest while nothing has arrived, and an ended booking cannot be ended
        twice."""
        if not self.is_open:
            raise ValueError(f"This booking is already {self.get_status_display().lower()}.")
        if cancel and self.received_total > 0:
            raise ValueError(
                "Goods have already been received against this booking — "
                "close it (writing off the balance) instead of cancelling it."
            )
        self.status = self.Status.CANCELLED if cancel else self.Status.CLOSED
        self.close_reason = reason.strip()[:200]
        self.closed_by = user
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "close_reason", "closed_by", "closed_at", "updated_at"])

    def recompute_status(self) -> None:
        lines = list(self.lines.all())
        if not lines:
            return
        booked = sum(line.booked_qty for line in lines)
        received = sum(line.received_qty for line in lines)
        if received <= 0:
            new = self.Status.BOOKED
        elif received < booked:
            new = self.Status.PARTIALLY_RECEIVED
        else:
            new = self.Status.RECEIVED
        if self.status not in (self.Status.CLOSED, self.Status.CANCELLED) and new != self.status:
            self.status = new
            self.save(update_fields=["status", "updated_at"])


class BookingLine(TimeStampedModel):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="lines")
    store = models.ForeignKey(
        "masters.Store",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="booking_lines",
        help_text="Destination store for this line (multi-store booking). "
        "Null = use the booking's default destination_store (else warehouse/HO).",
    )
    style_code = models.CharField(max_length=80)
    size = models.CharField(max_length=24, blank=True, default="")
    description = models.CharField(max_length=200, blank=True, default="")
    booked_qty = models.IntegerField(default=0)
    mrp_paise = MoneyField(null=True, blank=True)
    received_qty = models.IntegerField(default=0)
    inwarded_qty = models.IntegerField(default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.style_code} / {self.size} × {self.booked_qty}"
