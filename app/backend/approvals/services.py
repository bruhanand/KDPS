"""Approval services — the one write-path for maker-checker (#70).

Every approval in the system is requested, decided and checked through these
four functions. Nothing else writes an ``Approval`` row, so the rules below hold
system-wide by construction rather than by each module remembering them:

* a document is never approved by the person who made it;
* a reject always carries a reason;
* a decision is made once — a decided approval is closed;
* a wired document does not post until its approval says approved.
"""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils import timezone

from approvals.models import Approval, ApprovalStatus
from masters.scoping import scope_by_store


class ApprovalError(Exception):
    """Base for every maker-checker violation."""


class ApprovalRightsError(ApprovalError):
    """This user may not decide this one — a rights failure (403, not 400)."""


class SelfApprovalError(ApprovalRightsError):
    """The maker tried to be the checker."""


class NotAnApproverError(ApprovalRightsError):
    """The user's role is not among the approvers for this document."""


class ApprovalRequired(ApprovalError):
    """A wired document tried to post without a live approval."""


def display_name(user: Any) -> str:
    """How a person is named on screen — full name, else username. The one
    spelling, shared by the inbox and by every document's maker/checker line."""
    if user is None:
        return ""
    return getattr(user, "full_name", "") or getattr(user, "username", "") or ""


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


def request_approval(
    subject: models.Model,
    *,
    kind: str,
    kind_label: str,
    title: str,
    requested_by: Any,
    approver_roles: list[str],
    store: Any = None,
    value_paise: int = 0,
) -> Approval:
    """Put ``subject`` in the approvals inbox, waiting for someone else.

    Called by the module that owns the document, at draft-creation time, so the
    maker can never "forget" to seek approval — the document is born pending.
    """
    return Approval.objects.create(
        kind=kind,
        kind_label=kind_label,
        title=title,
        content_type=ContentType.objects.get_for_model(subject),
        object_id=subject.pk,
        store=store,
        value_paise=value_paise,
        approver_roles=list(approver_roles),
        requested_by=requested_by,
    )


def approval_for(subject: models.Model) -> Approval | None:
    """The approval against ``subject``, or None if the type isn't wired."""
    return Approval.objects.filter(
        content_type=ContentType.objects.get_for_model(subject), object_id=subject.pk
    ).first()


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------


@transaction.atomic
def decide(approval: Approval, *, actor: Any, action: str, reason: str = "") -> Approval:
    """Approve or reject, as ``actor``. The single enforcement point.

    Re-reads the row ``FOR UPDATE`` so two seniors clicking at the same moment
    cannot both decide it — the second gets the "already decided" error.
    """
    if action not in ("approve", "reject"):
        raise ApprovalError("action must be 'approve' or 'reject'.")

    locked = Approval.objects.select_for_update().get(pk=approval.pk)

    if locked.status != ApprovalStatus.PENDING:
        raise ApprovalError(f"This request was already {locked.status}.")

    # The rule the warehouse team asked for, in one place, for every document
    # type that uses this record: the maker is never the checker.
    if locked.requested_by_id == getattr(actor, "id", None):
        raise SelfApprovalError("You cannot approve a document you created.")

    if not can_decide(locked, actor):
        raise NotAnApproverError("Your role cannot decide this approval.")

    reason = (reason or "").strip()
    if action == "reject" and not reason:
        raise ApprovalError("A reason is required when rejecting.")

    locked.status = ApprovalStatus.APPROVED if action == "approve" else ApprovalStatus.REJECTED
    locked.decided_by = actor
    locked.decided_at = timezone.now()
    locked.reason = reason
    locked.save(update_fields=["status", "decided_by", "decided_at", "reason", "updated_at"])
    return locked


def can_decide(approval: Approval, user: Any) -> bool:
    """May ``user`` decide this one? Role gate only — the self-approval and
    store-scope gates are applied by ``decide`` and the inbox queryset."""
    if getattr(user, "is_superuser", False):
        return True
    role_code = getattr(getattr(user, "role", None), "code", "")
    return bool(role_code) and role_code in (approval.approver_roles or [])


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def inbox_for(user: Any) -> Any:
    """Everything waiting for ``user``'s decision, across every document type.

    Fail-closed on three axes: pending only, never one's own (a self-approval
    can never succeed, so it is never offered), role-matched, store-scoped.
    An approval with no store is network-level: only unrestricted users see it.
    """
    qs = (
        Approval.objects.filter(status=ApprovalStatus.PENDING)
        .exclude(requested_by=user)
        .select_related("store", "requested_by", "decided_by")
    )
    qs = scope_by_store(qs, user, "store_id")
    if not getattr(user, "is_superuser", False):
        role_code = getattr(getattr(user, "role", None), "code", "")
        if not role_code:
            return qs.none()
        qs = qs.filter(approver_roles__contains=[role_code])
    return qs


# ---------------------------------------------------------------------------
# Post-time gate
# ---------------------------------------------------------------------------


def assert_approved(subject: models.Model) -> Approval:
    """Raise unless ``subject`` carries an approval decided by a second person.

    Called from the *posting* layer, not the view, so no caller — API, shell,
    management command — can post a wired document past its checker.
    """
    approval = approval_for(subject)
    if approval is None:
        raise ApprovalRequired("This document has no approval request; it cannot post.")
    if approval.status == ApprovalStatus.REJECTED:
        raise ApprovalRequired(f"Approval was rejected: {approval.reason}")
    if approval.status != ApprovalStatus.APPROVED:
        raise ApprovalRequired("Waiting for approval by a second person.")
    return approval
