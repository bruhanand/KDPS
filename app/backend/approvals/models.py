"""The one generic approval record — maker-checker for the whole system (#70).

One table backs *every* approval flow (write-offs, V-flips, stock adjustments,
and later gap closures, stock requests, return-window overrides). A document
does not carry its own bespoke approval columns; it carries an ``Approval``
pointing at it, so a single inbox can list "everything waiting for you" without
knowing what any of those documents are.

Design notes
------------
* **Generic subject** — ``content_type`` + ``object_id`` point at any document.
  At most one approval per subject (this slice: one decision per document).
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
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="approvals_requested",
    )

    # --- checker -----------------------------------------------------------
    status = models.CharField(
        max_length=10, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
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
        help_text="Required on reject; free for approve.",
    )

    class Meta:
        db_table = "approvals_approval"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="approval_status_recent_idx"),
        ]
        constraints = [
            # One decision per document.
            models.UniqueConstraint(
                fields=["content_type", "object_id"], name="uq_approval_subject"
            ),
            # Maker ≠ checker, enforced by the database on every wired document
            # type at once. NULL decided_by (still pending) satisfies it.
            models.CheckConstraint(
                condition=~models.Q(decided_by=models.F("requested_by")),
                name="approval_maker_is_not_checker",
            ),
            # A decision always carries its decider and its timestamp; a pending
            # row carries neither.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=ApprovalStatus.PENDING,
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
