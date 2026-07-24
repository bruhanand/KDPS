"""Which outbound documents need a second person — and who that person may be.

This is the whole of outbound's knowledge about approvals: a small table of
document kinds (Rule 12 — variation is data, not code) plus two calls, one to
put a fresh draft in the inbox and one to refuse a post that hasn't cleared it.
The rules themselves (maker ≠ checker, reason on reject, one decision) live in
``approvals.services`` and are shared with every other module that wires in.

Wired in this slice: write-offs, V-flips, stock adjustments — the three that
used to stamp their own creator as approver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import models

from approvals.models import Approval
from approvals.services import ApprovalRequired, assert_approved, request_approval
from outbound.models import StockAdjustment, VFlip, WriteOff
from outbound.permissions import OUTBOUND_ADMIN_ROLES


@dataclass(frozen=True)
class ApprovalKind:
    """One wired document family."""

    code: str
    label: str
    approver_roles: tuple[str, ...]
    #: The document's own approver column, stamped from the approval at post time.
    approver_field: str


#: Only these roles may clear an outbound approval — a store-level maker always
#: needs someone at HO/finance level, never a peer.
_ADMIN_ROLES = tuple(sorted(OUTBOUND_ADMIN_ROLES))

KINDS: dict[type[models.Model], ApprovalKind] = {
    WriteOff: ApprovalKind("writeoff", "Write-off", _ADMIN_ROLES, "approved_by"),
    VFlip: ApprovalKind("vflip", "V-flip", _ADMIN_ROLES, "authorized_by"),
    StockAdjustment: ApprovalKind("adjustment", "Stock adjustment", _ADMIN_ROLES, "approved_by"),
}


def approver_field(doc_class: type[models.Model]) -> str:
    """Which column on ``doc_class`` names its approver."""
    kind = KINDS.get(doc_class)
    return kind.approver_field if kind else "approved_by"


def _line_totals(doc: Any) -> tuple[int, int, int]:
    """(line count, pieces, value in paise) over the document's lines.

    Adjustment lines carry a signed ``adj_qty``; the others a plain ``qty``.
    Value is what is at stake, so the magnitude is what counts.
    """
    lines = list(doc.lines.all())
    pieces = 0
    value = 0
    for line in lines:
        qty = abs(line.adj_qty) if hasattr(line, "adj_qty") else line.qty
        pieces += qty
        value += qty * (line.unit_cost_paise or 0)
    return len(lines), pieces, value


def request_document_approval(doc: Any, *, requested_by: Any) -> Approval | None:
    """Put a freshly created draft in the approvals inbox.

    Called at draft-creation time so the document is *born* pending — a maker
    cannot forget to ask, and cannot post in the gap before asking.
    """
    kind = KINDS.get(type(doc))
    if kind is None:
        return None

    line_count, pieces, value = _line_totals(doc)
    title = f"{doc.store.code} · {line_count} line{'' if line_count == 1 else 's'} · {pieces} pcs"

    return request_approval(
        doc,
        kind=kind.code,
        kind_label=kind.label,
        title=title,
        requested_by=requested_by,
        approver_roles=list(kind.approver_roles),
        store=doc.store,
        value_paise=value,
    )


def require_approved(doc: Any) -> Approval | None:
    """Refuse to post a wired document that no second person has approved, and
    stamp the approver onto the document itself.

    Called from the *posting* layer, so every caller — API, shell, management
    command — hits the same wall, and the stamp happens exactly once, on the
    one path that matters. A rejected document never reaches here, so it can
    never be marked as approved by the person who refused it.

    Unwired document types pass through untouched.
    """
    from outbound.posting import OutboundPostingError

    kind = KINDS.get(type(doc))
    if kind is None:
        return None
    try:
        approval = assert_approved(doc)
    except ApprovalRequired as exc:
        raise OutboundPostingError(str(exc)) from exc

    # The document is still a draft here (posting hasn't flipped it), so its own
    # approver column is writable — and after this it is frozen with the rest.
    if getattr(doc, f"{kind.approver_field}_id", None) != approval.decided_by_id:
        setattr(doc, kind.approver_field, approval.decided_by)
        doc.save(update_fields=[kind.approver_field])
    return approval
