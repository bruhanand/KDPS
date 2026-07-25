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

from approvals.models import Approval, ApprovalStatus
from approvals.services import (
    AlreadyPendingError,
    ApprovalRequired,
    approval_for,
    assert_approved,
    policy_for,
    record_no_approval_needed,
    request_approval,
)
from core.documents import DocStatus
from outbound.models import StockAdjustment, VFlip, WriteOff
from outbound.permissions import OUTBOUND_ADMIN_ROLES


@dataclass(frozen=True)
class ApprovalKind:
    """One wired document family, and the thresholds it starts life with.

    The four policy numbers are *seed* values: they are written into an
    ``ApprovalPolicy`` row the first time the kind is used, and the business
    tunes them there afterwards. Editing them here changes nothing that is
    already running — which is the point (Rule 12).
    """

    code: str
    label: str
    approver_roles: tuple[str, ...]
    #: The document's own approver column, stamped from the approval at post time.
    approver_field: str
    #: Value at stake at or below which no checker is asked. 0 = always ask.
    tolerance_paise: int = 0
    #: Value up to which the in-charge may approve. 0 = always HO.
    band_paise: int = 0
    #: Who may approve within the band (in-charge + HO).
    band_roles: tuple[str, ...] = ()


#: Only these roles may clear an outbound approval above the band — a store-level
#: maker always needs someone at HO/finance level, never a peer.
_ADMIN_ROLES = tuple(sorted(OUTBOUND_ADMIN_ROLES))

#: Within the band, the store in-charge may clear it too (a *different* one from
#: the maker — the self-approval rule still binds).
_IN_CHARGE_ROLES = tuple(sorted({*_ADMIN_ROLES, "store_manager"}))

#: Stock adjustments alone carry a tolerance: they are the output of counting,
#: where "book vs counted" is never going to agree to the piece, and the design
#: is explicit that a small variance auto-adjusts and is logged rather than
#: queueing behind a second person. Write-offs and V-flips have no tolerance —
#: stock leaving the books, or changing owner, always needs a second person.
_ADJ_TOLERANCE_PAISE = 2_00_000  # ₹2,000 at stake
_ADJ_BAND_PAISE = 25_00_000  # ₹25,000 — above this, HO only

KINDS: dict[type[models.Model], ApprovalKind] = {
    WriteOff: ApprovalKind("writeoff", "Write-off", _ADMIN_ROLES, "approved_by"),
    VFlip: ApprovalKind("vflip", "V-flip", _ADMIN_ROLES, "authorized_by"),
    StockAdjustment: ApprovalKind(
        "adjustment",
        "Stock adjustment",
        _ADMIN_ROLES,
        "approved_by",
        tolerance_paise=_ADJ_TOLERANCE_PAISE,
        band_paise=_ADJ_BAND_PAISE,
        band_roles=_IN_CHARGE_ROLES,
    ),
}


def approver_field(doc_class: type[models.Model]) -> str:
    """Which column on ``doc_class`` names its approver."""
    kind = KINDS.get(doc_class)
    return kind.approver_field if kind else "approved_by"


def _line_totals(doc: Any) -> tuple[int, int, int]:
    """(line count, pieces, value in paise) over the document's lines.

    Adjustment lines carry a signed ``adj_qty``; the others a plain ``qty``.
    Value is what is at stake, so the magnitude is what counts.

    The unit cost is the one **frozen onto the line** when the draft was made,
    which is the same number the posting engine will use — read it rather than
    deriving it again, or the books can move between drafting and approving and
    the approver is shown one figure while the engine posts another (#103).

    A line made outside the API — a shell, a management command, a draft left
    over from before that fix — carries no frozen cost, so the books are read
    for it instead. Either way it never comes from the payload: the value
    decides whether a second person is asked at all, so a maker who could type
    it could type their way out of being checked. A line neither route can
    price contributes nothing, leaving the total at 0 — read everywhere as
    "unknown", and unknown escalates.
    """
    from outbound.posting import book_unit_cost

    lines = list(doc.lines.all())
    pieces = 0
    value = 0
    for line in lines:
        qty = abs(line.adj_qty) if hasattr(line, "adj_qty") else line.qty
        pieces += qty
        frozen = getattr(line, "unit_cost_paise", 0) or 0
        value += qty * (
            frozen or book_unit_cost(doc.store_id, line.sku_code, getattr(line, "season", ""))
        )
    return len(lines), pieces, value


def _inr(paise: int) -> str:
    """Whole rupees with Lakh/Crore grouping — ``200000`` → ``₹2,000``.

    Local on purpose: the shared ₹ formatter is K9's, and this is one frozen
    sentence on an audit row, not a display path. Thresholds are set in whole
    rupees, so the paise are dropped rather than rounded.
    """
    rupees = str(abs(paise) // 100)
    if len(rupees) > 3:
        head, tail = rupees[:-3], rupees[-3:]
        # Indian grouping: every two digits above the last three.
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        rupees = ",".join(filter(None, [head, *groups, tail]))
    return f"₹{rupees}"


def _policy(kind: ApprovalKind) -> Any:
    """The live thresholds for this family, seeded from ``kind`` on first use."""
    return policy_for(
        kind.code,
        defaults={
            "tolerance_paise": kind.tolerance_paise,
            "band_paise": kind.band_paise,
            "band_roles": list(kind.band_roles or kind.approver_roles),
            "escalated_roles": list(kind.approver_roles),
        },
    )


def request_document_approval(doc: Any, *, requested_by: Any) -> Approval | None:
    """Put a freshly created draft in the approvals inbox — or record that it is
    small enough not to need one.

    Called at draft-creation time so the document is *born* with its answer: a
    maker cannot forget to ask, and cannot post in the gap before asking. Also
    the way back from a rejection — the maker fixes the draft and asks again,
    and the rejected request stays on the document's record.
    """
    kind = KINDS.get(type(doc))
    if kind is None:
        return None

    line_count, pieces, value = _line_totals(doc)
    title = f"{doc.store.code} · {line_count} line{'' if line_count == 1 else 's'} · {pieces} pcs"
    policy = _policy(kind)
    common = {
        "kind": kind.code,
        "kind_label": kind.label,
        "title": title,
        # The document's creator, not whoever is asking this time — see
        # ``ask_again``. Falls back to the asker for a document made outside
        # the API (a shell or a management command), which has no creator.
        "made_by": doc.created_by or requested_by,
        "requested_by": requested_by,
        "store": doc.store,
        "value_paise": value,
    }

    if not policy.needs_checker(value):
        return record_no_approval_needed(
            doc,
            reason=f"Within the {_inr(policy.tolerance)} tolerance for "
            f"{kind.label.lower()}s — posted and logged, no second person asked.",
            **common,
        )

    return request_approval(doc, approver_roles=policy.approver_roles_for(value), **common)


def ask_again(doc: Any, *, requested_by: Any) -> Approval:
    """Send a rejected draft back for approval, as ``requested_by``.

    Without this a rejection is a dead end: the kernel FSM has no
    draft → cancelled move, so a refused document could never post and could
    never be closed — the only route would be to abandon it and type the whole
    thing again, losing why it was refused.

    The *asker* is recorded as whoever pressed the button, but the document's
    maker is carried across unchanged, so re-asking can never move the author
    out of the way and let them approve their own document.
    """
    from outbound.posting import OutboundPostingError

    kind = KINDS.get(type(doc))
    if kind is None:
        raise OutboundPostingError("This document type does not need approval.")
    if doc.docstatus != DocStatus.DRAFT:
        raise OutboundPostingError("Only a draft can be sent for approval.")

    live = approval_for(doc)
    if live is None:
        raise OutboundPostingError("This document has no approval request.")
    if live.status == ApprovalStatus.PENDING:
        raise OutboundPostingError("This document is already waiting for approval.")
    if live.status != ApprovalStatus.REJECTED:
        raise OutboundPostingError("This document has already cleared approval.")

    try:
        approval = request_document_approval(doc, requested_by=requested_by)
    except AlreadyPendingError as exc:  # lost a race with another asker
        raise OutboundPostingError(str(exc)) from exc
    assert approval is not None  # kind is wired, checked above
    return approval


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
