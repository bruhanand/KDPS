"""Master-data spine (D8) — the load-bearing registries every later slice copies
from. Foundation scope: the `LegalEntity → GSTIN → Store` hierarchy (ADR-0007),
the season calendar, the brand register with its two-axis commercial model, and
the date-effective apparel GST slab.

These are mutable masters (SCD-2 versioning arrives with the money slices); they
extend `core.base.TimeStampedModel`, not the append-only ledger base.
"""

from __future__ import annotations

from django.db import models

from core.base import TimeStampedModel


class LegalEntity(TimeStampedModel):
    """The legal company. KDPS is one PAN / one legal entity / one Tally company,
    fronting two GSTINs (Bihar + Jharkhand)."""

    code = models.SlugField(max_length=24, unique=True)
    name = models.CharField(max_length=160)
    pan = models.CharField(max_length=10, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "legal entities"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Gstin(TimeStampedModel):
    """A state tax identity. Two GSTINs = two 'distinct persons'; the first two
    digits are the state code that drives intra- vs cross-state (IGST) treatment."""

    legal_entity = models.ForeignKey(
        LegalEntity, on_delete=models.PROTECT, related_name="gstins"
    )
    gstin = models.CharField(max_length=15, unique=True)
    state_code = models.CharField(max_length=2)  # e.g. "10" Bihar, "20" Jharkhand
    state_name = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "GSTIN"
        ordering = ["state_name"]

    def __str__(self) -> str:
        return f"{self.gstin} ({self.state_name})"


class Store(TimeStampedModel):
    """A store or warehouse. Maps to exactly one state GSTIN, so its state is the
    tax context for every document raised there."""

    class StoreType(models.TextChoices):
        STORE = "store", "Store"
        WAREHOUSE = "warehouse", "Warehouse"

    code = models.SlugField(max_length=16, unique=True)  # e.g. "DEO"
    name = models.CharField(max_length=120)
    store_type = models.CharField(
        max_length=12, choices=StoreType.choices, default=StoreType.STORE
    )
    gstin = models.ForeignKey(Gstin, on_delete=models.PROTECT, related_name="stores")
    city = models.CharField(max_length=80, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"


class Season(TimeStampedModel):
    """The selling period — a name, never a date (Open → EOSS → Closed)."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        EOSS = "eoss", "EOSS"
        CLOSED = "closed", "Closed"

    code = models.SlugField(max_length=24, unique=True)  # e.g. "SS26"
    name = models.CharField(max_length=80)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["-sort_order", "code"]

    def __str__(self) -> str:
        return self.name


class Brand(TimeStampedModel):
    """A brand and its commercial model, stored as two axes (ownership ×
    return-terms) with a derived friendly label — a first-class dimension, not a
    flag (ADR / Rule 12)."""

    class Ownership(models.TextChoices):
        OWNED = "owned", "KDPS-owned"
        BRAND_OWNED = "brand_owned", "Brand-owned"

    class ReturnTerms(models.TextChoices):
        NONE = "none", "No returns"
        CAPPED = "capped", "Capped allowance"
        UNCAPPED = "uncapped", "Uncapped"
        ROLLING = "rolling", "Uncapped + rolling top-up"

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    ownership = models.CharField(
        max_length=12, choices=Ownership.choices, default=Ownership.OWNED
    )
    return_terms = models.CharField(
        max_length=12, choices=ReturnTerms.choices, default=ReturnTerms.NONE
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def commercial_label(self) -> str:
        """The derived friendly label from the two axes."""
        o, r = self.ownership, self.return_terms
        if o == self.Ownership.OWNED:
            return "Correction" if r == self.ReturnTerms.CAPPED else "Outright"
        return "Consignment" if r == self.ReturnTerms.ROLLING else "SOR"


class GstSlab(TimeStampedModel):
    """Date-effective apparel GST slab (GST 2.0): a per-piece threshold splits a
    low rate from a high rate. Held as data (Rule 12) — re-verify before go-live."""

    name = models.CharField(max_length=80, default="Apparel")
    hsn_prefix = models.CharField(max_length=8, blank=True, default="")
    threshold_paise = models.BigIntegerField(default=250000)  # ₹2,500 / piece
    rate_below = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    rate_above = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    effective_from = models.DateField()

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self) -> str:
        return f"{self.name} (from {self.effective_from})"
