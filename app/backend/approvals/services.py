"""Approval services — the one write-path for maker-checker (#70).

Every approval in the system is requested, decided and checked through these
four functions. Nothing else writes an ``Approval`` row, so the rules below hold
system-wide by construction rather than by each module remembering them:

* a document is never approved by the person who made it;
* a reject always carries a reason;
* a decision is made once — a decided approval is closed;
* a wired document does not post until its approval says approved;
* how big a document must be before a checker is asked, and who that checker
  may be, is read from a policy row — data the business can retune (Rule 12).
"""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from approvals.models import CLEARED_STATUSES, Approval, ApprovalPolicy, ApprovalStatus
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


class AlreadyPendingError(ApprovalError):
    """Asked again while a request for the same document is still waiting."""


def display_name(user: Any) -> str:
    """How a person is named on screen — full name, else username. The one
    spelling, shared by the inbox and by every document's maker/checker line."""
    if user is None:
        return ""
    return getattr(user, "full_name", "") or getattr(user, "username", "") or ""


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def policy_for(kind: str, *, defaults: dict[str, Any]) -> ApprovalPolicy:
    """The live thresholds for a document family.

    Materialised from the owning module's defaults the first time that kind is
    used, so every wired family shows up in the admin ready to be retuned —
    thresholds are business data, not a constant someone has to redeploy.
    """
    policy, _ = ApprovalPolicy.objects.get_or_create(kind=kind, defaults=defaults)
    return policy


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


def _create(
    subject: models.Model,
    *,
    status: str,
    kind: str,
    kind_label: str,
    title: str,
    made_by: Any,
    requested_by: Any,
    approver_roles: list[str],
    store: Any = None,
    value_paise: int = 0,
    reason: str = "",
) -> Approval:
    return Approval.objects.create(
        kind=kind,
        kind_label=kind_label,
        title=title,
        content_type=ContentType.objects.get_for_model(subject),
        object_id=subject.pk,
        store=store,
        value_paise=value_paise,
        approver_roles=list(approver_roles),
        made_by=made_by,
        requested_by=requested_by,
        status=status,
        reason=reason,
    )


def request_approval(
    subject: models.Model,
    *,
    kind: str,
    kind_label: str,
    title: str,
    made_by: Any,
    requested_by: Any,
    approver_roles: list[str],
    store: Any = None,
    value_paise: int = 0,
) -> Approval:
    """Put ``subject`` in the approvals inbox, waiting for someone else.

    Called by the module that owns the document, at draft-creation time, so the
    maker can never "forget" to seek approval — the document is born pending.
    Also the way back from a rejection: the document is fixed and asked again,
    which raises a *new* request beside the rejected one. ``made_by`` is the
    document's creator either way, so re-asking cannot move the maker aside.
    """
    try:
        with transaction.atomic():
            return _create(
                subject,
                status=ApprovalStatus.PENDING,
                kind=kind,
                kind_label=kind_label,
                title=title,
                made_by=made_by,
                requested_by=requested_by,
                approver_roles=approver_roles,
                store=store,
                value_paise=value_paise,
            )
    except IntegrityError as exc:
        # The partial unique index is the one that actually binds — two people
        # clicking "ask again" at the same moment race past any prior read.
        if "uq_approval_subject_pending" not in str(exc):
            raise
        raise AlreadyPendingError("This document is already waiting for approval.") from exc


def record_no_approval_needed(
    subject: models.Model,
    *,
    kind: str,
    kind_label: str,
    title: str,
    made_by: Any,
    requested_by: Any,
    store: Any = None,
    value_paise: int = 0,
    reason: str,
) -> Approval:
    """Record that ``subject`` fell within its policy tolerance.

    The document may post with nobody else's say-so, but "nobody was asked" is
    itself a fact worth keeping: the row carries who made it and which rule let
    it through, so a small adjustment is auditable exactly like a large one.
    """
    return _create(
        subject,
        status=ApprovalStatus.NOT_REQUIRED,
        kind=kind,
        kind_label=kind_label,
        title=title,
        made_by=made_by,
        requested_by=requested_by,
        approver_roles=[],
        store=store,
        value_paise=value_paise,
        reason=reason,
    )


def approvals_for(subject: models.Model) -> Any:
    """Every approval ever raised against ``subject``, newest first."""
    return Approval.objects.filter(
        content_type=ContentType.objects.get_for_model(subject), object_id=subject.pk
    ).select_related("made_by", "requested_by", "decided_by")


def approval_for(subject: models.Model) -> Approval | None:
    """The *live* approval against ``subject`` — the newest one, since a
    rejected request stays on the record after the maker asks again. None if
    the type isn't wired, or nothing has been asked yet."""
    return approvals_for(subject).first()


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
    # type that uses this record: the maker is never the checker. Both the
    # person who made the document and the person who asked this time are
    # barred — after a rejection those can be two different people, and letting
    # a colleague re-raise a document so its author can approve it would be
    # maker-checker with extra steps.
    actor_id = getattr(actor, "id", None)
    if locked.made_by_id == actor_id:
        raise SelfApprovalError("You cannot approve a document you created.")
    if locked.requested_by_id == actor_id:
        raise SelfApprovalError("You cannot approve a request you raised.")

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

    Fail-closed on three axes: pending only, never one's own — neither made nor
    asked by this user, since a self-approval can never succeed and so is never
    offered — role-matched, store-scoped. An approval with no store is
    network-level: only unrestricted users see it.
    """
    qs = (
        Approval.objects.filter(status=ApprovalStatus.PENDING)
        .exclude(requested_by=user)
        .exclude(made_by=user)
        .select_related("store", "made_by", "requested_by", "decided_by")
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
        raise ApprovalRequired(
            f"Approval was rejected: {approval.reason} — fix the draft and ask again."
        )
    if approval.status not in CLEARED_STATUSES:
        raise ApprovalRequired("Waiting for approval by a second person.")
    return approval
