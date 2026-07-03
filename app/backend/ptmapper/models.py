"""PT Mapper data model.

The *lookup tables* (controlled vocabulary, single-value maps, taxonomy rules) are
the real product — they are data edited by KDPS staff and grow via the review
queue, never code. The *profiles* (how a brand file's columns map to KDPS) live
in code (`ptmapper/profiles.py`) because they are engine config, not business data.
"""

from __future__ import annotations

from typing import Any

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
    """Single-value normaliser: a brand's raw value → a KDPS controlled value.

    ``brand`` scopes the rule (D4): a non-empty brand (a Master brand value) applies
    only to rows whose *resolved* BRAND matches; ``brand=""`` is a global rule. The
    resolver prefers a brand-scoped row over a global one, so a Peter England
    fit-code or a Zilu shade can be learned without polluting other brands. Existing
    rows default ``brand=""`` (global) — behaviour is unchanged until a scoped row
    is added beside one.
    """

    dimension = models.CharField(max_length=20)  # color | size | brand | season | gender | fit
    source_key = models.CharField(max_length=240)  # normalised raw (upper, trimmed)
    target_value = models.CharField(max_length=160)
    brand = models.CharField(max_length=160, blank=True, default="")  # "" = global

    class Meta:
        unique_together = [("dimension", "source_key", "brand")]
        ordering = ["dimension", "brand", "source_key"]

    def __str__(self) -> str:
        scope = f"[{self.brand}]" if self.brand else ""
        return f"{self.dimension}{scope}:{self.source_key}→{self.target_value}"


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
    gap-free `{FY}/{store}/PT/{n}` number — the inward voucher, numbered under the
    GRN's receiving location — and freezes it (SUBMITTED). "Reverse posting" is a
    `cancel()` (reversal-as-cancel): the file is
    frozen forever and the stock/GL/payable reversals are appended; you re-upload to
    re-post, never edit a posted fact.
    """

    class Status(models.TextChoices):  # mapping quality (draft-time)
        NEEDS_REVIEW = "needs_review", "Needs review"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        """Where the rows came from. ``brand_file`` = the deterministic mapper over an
        uploaded brand PT (the original path, untouched). ``invoice`` = *authored* from
        a GRN's counted lines (the non-brand path, D2 Q4/Q7/Q8) — same object, same
        editor, same send→post pipeline; only the way rows are born differs."""

        BRAND_FILE = "brand_file", "Brand PT file"
        INVOICE = "invoice", "Authored from GRN / invoice"

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
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.BRAND_FILE)
    # The arrival this PT converts (Q22/Q33 linkage — the GRN is the pragmatic arrival
    # anchor; no separate Shipment). Always set for invoice-sourced PTs; a brand PT can
    # be linked later. String FK: ptmapper must not import inbound at module level.
    grn = models.ForeignKey(
        "inbound.Grn", null=True, blank=True, on_delete=models.SET_NULL, related_name="pt_files"
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
        constraints = [
            *Document.Meta.constraints,
            # One live (non-cancelled) PT per GRN — the DB backstop behind the code's
            # row-locked check, so no code path or bulk script can leave a GRN carrying
            # two competing PTs. NULL grn (legacy grn-less uploads) is exempt (Postgres
            # treats NULLs as distinct in a partial unique index).
            models.UniqueConstraint(
                fields=["grn"],
                condition=~models.Q(docstatus=DocStatus.CANCELLED),
                name="uniq_live_pt_per_grn",
            ),
        ]

    def series_lookup(self) -> tuple[str, str, str]:
        # Per-location, gap-free PT numbering: a PT is numbered under the store its
        # GRN was received at (branded → the selling store, non-branded → the
        # warehouse). Legacy grn-less uploads keep RAN-WH. Must return the SAME key
        # `post_pt_inward` allocates its voucher under, or numbering and posting drift.
        grn = self.grn
        store_code = grn.store.code if grn is not None else "RAN-WH"
        return financial_year(), store_code, "PT"

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
    # {controlled column: raw source value the engine read} — lets a hand-edit be
    # bulk-applied to every row that carried the same raw value (and, later, be
    # learned into a Lookup). See engine._raw_sources.
    raw = models.JSONField(default=dict, blank=True)

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


class CorrectionEvent(models.Model):
    """Append-only log of one human cell-correction — the training signal for the
    self-improving mapper and the Rule-10 actor trail (who fixed what, when).

    Rows outlive the ``PtRow`` they described (rows die on every re-map, so the FKs
    are ``SET_NULL``); ``file_name`` / ``line_no`` / ``brand`` / ``raw_value`` are
    denormalised so a mined proposal keeps its provenance after the row is gone.
    ``brand`` is the row's *resolved* BRAND at edit time — the mining scope key.
    Never updated: ``save()`` refuses a second write (append-only, code-enforced).
    """

    class EditKind(models.TextChoices):
        CELL = "cell", "Cell edit"
        FILL_BLANK = "fill_blank", "Fill blank cells"
        FILL_ALL = "fill_all", "Fill all cells"
        FILL_MATCH_RAW = "fill_match_raw", "Fill cells matching a raw value"

    pt_file = models.ForeignKey(
        PtFile, null=True, blank=True, on_delete=models.SET_NULL, related_name="correction_events"
    )
    pt_row = models.ForeignKey(
        PtRow, null=True, blank=True, on_delete=models.SET_NULL, related_name="correction_events"
    )
    file_name = models.CharField(max_length=255, blank=True, default="")
    line_no = models.IntegerField(default=0)
    brand = models.CharField(max_length=160, blank=True, default="")  # resolved BRAND (scope key)
    column = models.CharField(max_length=40)  # the KDPS column edited
    dimension = models.CharField(max_length=20, blank=True, default="")  # its controlled dimension
    raw_value = models.CharField(max_length=300, blank=True, default="")  # raw the engine read
    old_value = models.CharField(max_length=300, blank=True, default="")
    new_value = models.CharField(max_length=300, blank=True, default="")
    provenance_before = models.CharField(max_length=20, blank=True, default="")
    edit_kind = models.CharField(max_length=16, choices=EditKind.choices, default=EditKind.CELL)
    remember = models.BooleanField(default=False)  # D1: operator asked to learn this
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["dimension", "raw_value"]),
            models.Index(fields=["brand", "dimension"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.column}: {self.old_value!r}→{self.new_value!r}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        # `_state.adding` is True only for a never-persisted instance; anything else
        # is an UPDATE in disguise. A correction is a fact — refuse to rewrite it.
        if not self._state.adding:
            raise ValueError("CorrectionEvent is append-only; it cannot be updated.")
        super().save(*args, **kwargs)


class LookupProposal(TimeStampedModel):
    """A staged ``(dimension, source_key, brand → target_value)`` mapping awaiting a
    human decision — the only gate between a learned suggestion and a live ``Lookup``
    (Rule 8: miners suggest; a human decides). ``origin`` records where it came from
    (a steward's review resolution, an operator's remember-tick, or the deterministic
    miner); ``evidence`` carries the supporting corrections/files; ``validation`` holds
    the last shadow-check. A partial-unique index keeps at most one *open* (proposed)
    proposal per identity, so the miner is idempotent / cron-safe.
    """

    class Origin(models.TextChoices):
        REVIEW = "review", "Review resolution"
        REMEMBER = "remember", "Remember this"
        MINED = "mined", "Deterministic miner"
        LLM = "llm", "LLM miner"  # reserved — deferred slice

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        AUTO_REJECTED = "auto_rejected", "Auto-rejected (shadow conflict)"

    dimension = models.CharField(max_length=20)
    source_key = models.CharField(max_length=240)  # normalised raw
    target_value = models.CharField(max_length=160)
    brand = models.CharField(max_length=160, blank=True, default="")  # "" = global
    origin = models.CharField(max_length=12, choices=Origin.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    evidence = models.JSONField(default=dict, blank=True)  # {correction_event_ids, files, brands}
    validation = models.JSONField(default=dict, blank=True)  # last shadow_check result
    proposed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dimension", "source_key", "brand"],
                condition=models.Q(status="proposed"),
                name="uniq_open_lookup_proposal",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        scope = f"[{self.brand}]" if self.brand else ""
        return f"{self.dimension}{scope}:{self.source_key}→{self.target_value} ({self.status})"
