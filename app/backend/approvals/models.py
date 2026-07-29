"""The one generic approval record — maker-checker for the whole system (#70).

One table backs *every* approval flow (write-offs, V-flips, stock adjustments,
and later gap closures, stock requests, return-window overrides). A document
does not carry its own bespoke approval columns; it carries an ``Approval``
pointing at it, so a single inbox can list "everything waiting for you" without
knowing what any of those documents are.

Design notes
------------
* **Generic subject** — ``content_type`` + ``object_id`` point at any document.
  At most one *pending* approval per subject: a rejected request stays on the
  record and the maker may fix the draft and ask again, so a document carries
  the whole "asked → rejected → asked again → approved" history.
* **Snapshots, not joins** — ``kind_label``, ``title``, ``value_paise`` and
  ``approver_roles`` are written by the requesting module at request time
  (Rule 6: snapshot what the decision was taken against; Rule 12: who may
  approve is *data on the row*, not a branch in code). The inbox therefore
  renders without importing a single business model.
* **Maker ≠ checker is a DB constraint, not just a service check** — the kernel
  house style is defence-in-depth: the ORM raises the early, clean error, the
  database is the one that actually binds.
"""

from __future__ import annotations

from typing import ClassVar

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.db import models

from core.base import TimeStampedModel
from core.money import MoneyField


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Waiting for approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    #: Below the policy tolerance — the document posts without a second person,
    #: but the row is still written so *every* wired document has one record
    #: saying who made it and why no checker was asked ("auto-adjust, logged").
    NOT_REQUIRED = "not_required", "No second person needed"


#: The two statuses that let a document post.
CLEARED_STATUSES = (ApprovalStatus.APPROVED, ApprovalStatus.NOT_REQUIRED)


class Approval(TimeStampedModel):
    """One pending-or-decided approval against one document."""

    # --- what is being approved -------------------------------------------
    kind = models.CharField(
        max_length=32,
        help_text="Machine code of the document family, e.g. 'writeoff'. "
        "The client maps it to a route; the server never branches on it.",
    )
    kind_label = models.CharField(max_length=64)
    title = models.CharField(
        max_length=240,
        help_text="Snapshot one-liner shown in the inbox (store, lines, pieces).",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.BigIntegerField()
    subject = GenericForeignKey("content_type", "object_id")

    # --- context used to route & scope the inbox ---------------------------
    store = models.ForeignKey(
        "masters.Store",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approvals",
        help_text="Scopes the inbox for store-scoped users (ADR-0003).",
    )
    brand = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Scopes the inbox for brand-scoped users — a brand manager, "
        "whose boundary is brands and not stores (ADR-0003). Snapshotted as the "
        "brand *name*, like every other brand on a ledger row, so this table "
        "still imports no business model. Blank means the decision is not about "
        "one brand, and a brand-scoped user never sees it (#75).",
    )
    value_paise = MoneyField(
        default=0,
        help_text="Value at stake, snapshotted — the input to value-banded approval.",
    )
    approver_roles = ArrayField(
        models.CharField(max_length=32),
        default=list,
        help_text="Role codes that may decide this one. Data, not code (Rule 12).",
    )

    # --- maker -------------------------------------------------------------
    made_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="approvals_made",
        help_text="Who created the document. Snapshotted once and never "
        "rewritten, so re-asking after a rejection cannot launder the maker "
        "out of the way and let them approve their own document.",
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="approvals_requested",
        help_text="Who asked, this time round. Usually the maker; after a "
        "rejection it may be whoever picked the document back up.",
    )

    # --- checker -----------------------------------------------------------
    status = models.CharField(
        max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )
    decided_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approvals_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(
        blank=True,
        default="",
        help_text="Required on reject; free for approve; the policy note on 'not_required'.",
    )

    class Meta:
        db_table = "approvals_approval"
        # Newest first, and never ambiguous: a document may hold several rows
        # once it has been rejected and asked again, and "the live one" is
        # always the newest — so ties must not be resolved by chance.
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="approval_status_recent_idx"),
        ]
        constraints = [
            # One *pending* request per document — a document is never in two
            # people's inboxes at once — while decided rows accumulate as the
            # document's history.
            models.UniqueConstraint(
                fields=["content_type", "object_id"],
                condition=models.Q(status=ApprovalStatus.PENDING),
                name="uq_approval_subject_pending",
            ),
            # Maker ≠ checker, enforced by the database on every wired document
            # type at once. NULL decided_by (still pending) satisfies both.
            # Two rows, because after a rejection the maker and the asker can be
            # two different people and *neither* may be the checker.
            models.CheckConstraint(
                condition=~models.Q(decided_by=models.F("requested_by")),
                name="approval_asker_is_not_checker",
            ),
            models.CheckConstraint(
                condition=~models.Q(decided_by=models.F("made_by")),
                name="approval_maker_is_not_checker",
            ),
            # A *person's* decision always carries its decider and its
            # timestamp; a row nobody has decided — still pending, or never
            # needed one — carries neither.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=[ApprovalStatus.PENDING, ApprovalStatus.NOT_REQUIRED],
                        decided_by__isnull=True,
                        decided_at__isnull=True,
                    )
                    | models.Q(
                        status__in=[ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
                        decided_by__isnull=False,
                        decided_at__isnull=False,
                    )
                ),
                name="approval_decision_is_complete",
            ),
            # "Reject requires a reason" — the acceptance criterion, in the DB.
            models.CheckConstraint(
                condition=~models.Q(status=ApprovalStatus.REJECTED) | ~models.Q(reason=""),
                name="approval_reject_has_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind_label} #{self.object_id} — {self.status}"


class ApprovalPolicy(TimeStampedModel):
    """How much a document may be worth before a second person is needed, and
    who that person must be — one row per document family.

    From the count design: *"within a configurable tolerance → auto-adjust,
    logged, done. Above tolerance → … a named approver. Approval is
    value-banded: up to a configurable value the in-charge approves; above it,
    HO."* Both numbers and both role lists are **data** so the business can
    retune them in the admin without a release (Rule 12).

    The owning module supplies its own defaults on first use; nothing here
    imports a business model, so this stays the generic maker-checker spine.
    """

    kind = models.CharField(
        max_length=32,
        unique=True,
        help_text="Document family this governs, e.g. 'adjustment'.",
    )
    tolerance_paise = MoneyField(
        default=0,
        help_text="Value at stake at or below which no second person is asked — "
        "the document posts and the decision is logged. 0 disables the "
        "tolerance: every document of this kind needs a checker.",
    )
    band_paise = MoneyField(
        default=0,
        help_text="Up to this value the in-charge roles may approve; above it, "
        "only the escalated roles. 0 sends every one straight to HO.",
    )
    band_roles = ArrayField(
        models.CharField(max_length=32),
        default=list,
        help_text="Role codes that may approve within the band (in-charge + HO).",
    )
    escalated_roles = ArrayField(
        models.CharField(max_length=32),
        default=list,
        help_text="Role codes that may approve above the band (HO only).",
    )

    class Meta:
        db_table = "approvals_policy"
        ordering = ["kind"]
        verbose_name_plural = "approval policies"

    #: What each family is called in the business's own words. A Setup screen
    #: shows the *family*, not its slug — an owner retuning who signs off a
    #: return to brand should not have to read ``return_to_brand``. Kept here
    #: beside the codes rather than in the PWA so one name serves every surface,
    #: and it stays a plain dict so this module still imports nothing (ADR-0002).
    FAMILY_LABELS: ClassVar[dict[str, str]] = {
        "adjustment": "Stock adjustment",
        "damage": "Damage flag",
        "gap_closure": "Transfer gap closure",
        "pt_reverse": "PT reversal",
        "return_to_brand": "Return to brand",
        "stock_request": "Stock request",
        "transfer": "Transfer",
        "vflip": "V-flip",
        "writeoff": "Write-off",
    }

    def __str__(self) -> str:
        return f"{self.kind} policy"

    @property
    def label(self) -> str:
        """The family in the business's words; an unknown code reads as itself."""
        return self.FAMILY_LABELS.get(self.kind, self.kind.replace("_", " ").capitalize())

    # -- the two questions the policy answers --------------------------------

    @property
    def tolerance(self) -> int:
        """The threshold as a plain number — an unset column reads as 'no
        tolerance', which is the strict, fail-closed reading."""
        return self.tolerance_paise or 0

    @property
    def band(self) -> int:
        return self.band_paise or 0

    def needs_checker(self, value_paise: int) -> bool:
        """Is this one big enough to need a second person?

        A value of zero means *unknown*, not *free*: cost is enriched at post
        time on some documents, so a draft can honestly not know what it is
        worth yet. Unknown fails closed — it goes to a checker.
        """
        if self.tolerance <= 0 or value_paise <= 0:
            return True
        return value_paise > self.tolerance

    def approver_roles_for(self, value_paise: int) -> list[str]:
        """Who may clear it — the in-charge band, or HO. Unknown value (0)
        escalates, for the same reason."""
        if 0 < value_paise <= self.band:
            return list(self.band_roles)
        return list(self.escalated_roles)
