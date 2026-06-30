"""PT Mapper data model.

The *lookup tables* (controlled vocabulary, single-value maps, taxonomy rules) are
the real product — they are data edited by KDPS staff and grow via the review
queue, never code. The *profiles* (how a brand file's columns map to KDPS) live
in code (`ptmapper/profiles.py`) because they are engine config, not business data.
"""

from __future__ import annotations

from django.db import models

from core.base import TimeStampedModel
from core.documents import DocStatus, Document
from core.fiscal import financial_year


class ControlledValue(TimeStampedModel):
    """KDPS Master Sheet vocabulary — the allowed value of each derived column."""

    class Dimension(models.TextChoices):
        SEASON = "season", "Season"
        BRAND = "brand", "Brand"
        COLOR = "color", "Color"
        GENDER = "gender", "Gender"
        SUB_CATEGORY = "sub_category", "Sub Category"
        TYPE = "type", "Type"
        ITEM = "item", "Item"
        FIT = "fit", "Fit"
        SIZE = "size", "Size"
        GST = "gst", "GST %"

    dimension = models.CharField(max_length=20, choices=Dimension.choices)
    value = models.CharField(max_length=160)

    class Meta:
        unique_together = [("dimension", "value")]
        ordering = ["dimension", "value"]

    def __str__(self) -> str:
        return f"{self.dimension}:{self.value}"


class ItemTaxonomy(TimeStampedModel):
    """ITEM → suggested (SUB CATEGORY, TYPE) — the Master Sheet helper columns."""

    item = models.CharField(max_length=160, unique=True)
    sub_category = models.CharField(max_length=60, blank=True, default="")
    type = models.CharField(max_length=60, blank=True, default="")


class Lookup(TimeStampedModel):
    """Single-value normaliser: a brand's raw value → a KDPS controlled value."""

    dimension = models.CharField(max_length=20)  # color | size | brand | season | gender
    source_key = models.CharField(max_length=240)  # normalised raw (upper, trimmed)
    target_value = models.CharField(max_length=160)

    class Meta:
        unique_together = [("dimension", "source_key")]
        ordering = ["dimension", "source_key"]

    def __str__(self) -> str:
        return f"{self.dimension}:{self.source_key}→{self.target_value}"


class TaxonomyRule(TimeStampedModel):
    """Keyword (substring of the item description) → the 5-axis merchandising grid."""

    pattern = models.CharField(max_length=160)  # matched case-insensitive in description
    gender = models.CharField(max_length=40, blank=True, default="")
    sub_category = models.CharField(max_length=60, blank=True, default="")
    type = models.CharField(max_length=60, blank=True, default="")
    item = models.CharField(max_length=160, blank=True, default="")
    fit = models.CharField(max_length=80, blank=True, default="")
    priority = models.IntegerField(default=100)  # higher wins (default = len(pattern))

    class Meta:
        ordering = ["-priority", "pattern"]

    def __str__(self) -> str:
        return f"{self.pattern} → {self.item or '?'}"


class PtFile(Document):
    """One uploaded brand PT file + the result of mapping it to KDPS format.

    A document (ADR-0004): while a DRAFT it walks the warehouse sub-stages
    `mapping → sent` (freely editable). `post()` (Patna "push into system") mints its
    gap-free `{FY}/RAN-WH/PT/{n}` number — the inward voucher — and freezes it
    (SUBMITTED). "Reverse posting" is a `cancel()` (reversal-as-cancel): the file is
    frozen forever and the stock/GL/payable reversals are appended; you re-upload to
    re-post, never edit a posted fact.
    """

    class Status(models.TextChoices):  # mapping quality (draft-time)
        NEEDS_REVIEW = "needs_review", "Needs review"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    class DraftStage(models.TextChoices):  # the stored pre-post sub-stage
        MAPPING = "mapping", "Mapping (Warehouse)"
        SENT = "sent", "Sent to Patna"

    class Stage:  # the full lifecycle vocabulary the UI/API speak (computed below)
        MAPPING = "mapping"
        SENT = "sent"
        POSTED = "posted"
        REVERSED = "reversed"

    _STAGE_LABELS = {
        "mapping": "Mapping (Warehouse)",
        "sent": "Sent to Patna",
        "posted": "Posted to system",
        "reversed": "Reversed",
    }

    stored_file = models.ForeignKey(
        "files.StoredFile", null=True, blank=True, on_delete=models.SET_NULL
    )
    original_filename = models.CharField(max_length=255)
    brand_guess = models.CharField(max_length=160, blank=True, default="")
    profile_code = models.CharField(max_length=60, blank=True, default="")
    profile_name = models.CharField(max_length=160, blank=True, default="")
    archetype = models.CharField(max_length=4, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEEDS_REVIEW)
    draft_stage = models.CharField(
        max_length=12, choices=DraftStage.choices, default=DraftStage.MAPPING
    )
    manually_edited = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    booking = models.ForeignKey(
        "vendors.Booking",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pt_files",
    )
    row_count = models.IntegerField(default=0)
    blank_cell_count = models.IntegerField(default=0)
    unresolved_count = models.IntegerField(default=0)  # distinct open review items
    meta = models.JSONField(default=dict, blank=True)  # header_row, sheet, detection notes
    error = models.CharField(max_length=400, blank=True, default="")
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta(Document.Meta):
        db_table = "ptmapper_ptfile"
        ordering = ["-created_at"]

    def series_lookup(self) -> tuple[str, str, str]:
        return financial_year(), "RAN-WH", "PT"

    @property
    def stage(self) -> str:
        """The lifecycle stage the UI/API speak, derived from docstatus: a cancelled
        file reads 'reversed', a submitted one 'posted', else the draft sub-stage."""
        if self.docstatus == DocStatus.CANCELLED:
            return self.Stage.REVERSED
        if self.docstatus == DocStatus.SUBMITTED:
            return self.Stage.POSTED
        return self.draft_stage

    @property
    def stage_label(self) -> str:
        return self._STAGE_LABELS.get(self.stage, self.stage)

    def __str__(self) -> str:
        return self.original_filename


class PtRow(TimeStampedModel):
    """One mapped KDPS output row (one SKU = barcode × size)."""

    pt_file = models.ForeignKey(PtFile, on_delete=models.CASCADE, related_name="rows")
    line_no = models.IntegerField(default=0)
    data = models.JSONField(default=dict)  # {SEASON:.., BRAND:.., ...}
    blanks = models.JSONField(default=list)  # KDPS field names left unresolved
    # {field: source} — how each derived cell was filled (direct/alias/rule/inferred/
    # derived/manual). Lets the UI flag low-confidence cells so a wrong auto-mapping is
    # visible to a steward instead of silent. See engine.LOW_CONFIDENCE_SOURCES.
    provenance = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["line_no"]


class ReviewItem(TimeStampedModel):
    """An unresolved (dimension, raw value) the engine could not map — a human
    resolves it once (adds a lookup row) and every file with that value re-maps."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        IGNORED = "ignored", "Ignored"

    dimension = models.CharField(max_length=20)  # color | size | brand | season | taxonomy
    raw_value = models.CharField(max_length=300)
    context = models.JSONField(default=dict, blank=True)  # {brands:[], samples:[], files:[]}
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    resolved_value = models.CharField(max_length=300, blank=True, default="")
    occurrences = models.IntegerField(default=1)

    class Meta:
        unique_together = [("dimension", "raw_value")]
        ordering = ["status", "-occurrences", "dimension", "raw_value"]

    def __str__(self) -> str:
        return f"{self.dimension}:{self.raw_value} [{self.status}]"
