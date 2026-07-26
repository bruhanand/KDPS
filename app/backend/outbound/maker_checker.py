"""Which outbound documents need a second person — and who that person may be.

This is the whole of outbound's knowledge about approvals: a small table of
document kinds (Rule 12 — variation is data, not code) plus two calls, one to
put a fresh draft in the inbox and one to refuse a post that hasn't cleared it.
The rules themselves (maker ≠ checker, reason on reject, one decision) live in
``approvals.services`` and are shared with every other module that wires in.

Wired: write-offs, V-flips, stock adjustments — the three that used to stamp
their own creator as approver — plus transfer gap closures (#71) and damage
flags (#138), which reach the inbox the same way as everything else.

Damage is the one family where the second person is asked for on a *rung*
rather than on a value: a store person may report damage but not move the
stock, so their document waits, while a warehouse or HO person's own document
clears itself (``self_clearing``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import models

from accounts.rbac_matrix import roles_with_capability
from accounts.role_lists import declare_role_list
from accounts.sections import CAP_APPROVE
from approvals.models import Approval, ApprovalStatus
from approvals.services import (
    AlreadyPendingError,
    ApprovalRequired,
    approval_for,
    assert_approved,
    holds_approver_role,
    policy_for,
    record_no_approval_needed,
    request_approval,
)
from core.documents import DocStatus
from outbound.models import MarkDamaged, StockAdjustment, TransferGapClosure, VFlip, WriteOff


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
    #: Whether a maker who already holds this family's approving rung clears
    #: their own document. Not a value tolerance — a rung: the maker *is* the
    #: checker this family would have asked, so asking would be asking
    #: themselves. Who that is stays one list, read from the live policy row
    #: (Rule 12), never frozen a second time here.
    self_clearing: bool = False


#: Who may clear a correction, and who may clear an ownership flip — the roles
#: the matrix puts at ``approve`` or above on that document's own section, read
#: from the sheet rather than hand-listed here (#94). These are *seed* values;
#: the live answer is the ``ApprovalPolicy`` row, which the business retunes.
_COUNT_APPROVERS = roles_with_capability("stock_count", CAP_APPROVE)
_STOCK_APPROVERS = roles_with_capability("stock", CAP_APPROVE)

#: Who may clear a transfer gap: the roles at ``transfer: approve``, read from the
#: same place every other approver list is, rather than the hand-kept admin list
#: #94 deleted (which named ``it_admin`` and ``accounts``, whom the sheet gives
#: only *view* on transfers, and omitted the brand manager it gives *approve*).
#:
#: One caveat worth stating: ``ho_ops`` — the Operations Head the design actually
#: names for this decision — holds its ``approve`` through ``DERIVED_ACCESS``,
#: which ``rbac_matrix`` is explicit is *not* the ratified sheet and may be
#: retuned as data. So the one role the design names is the one whose seat here is
#: least ratified. That is an argument for giving Operations Head a sheet row, not
#: for hand-listing roles again. Seniority is all this expresses; the entitlement
#: rule barring anyone tied to the receiving store is a separate gate in
#: ``posting._refuse_self_closure``.
_GAP_APPROVERS = roles_with_capability("transfer", CAP_APPROVE)

#: Who may confirm a damage flag (#138). The ladder gives the ratified half —
#: the roles the sheet puts at ``return_to_brand: approve`` or above (Owner, and
#: Admin at ``manage``) — and cannot give the other half: the sheet puts the
#: warehouse and the store person on the *same* rung, ``return_to_brand:
#: operate``, and separates them only in the cell's words ("Create & execute" vs
#: "Mark damage only"). Anand's 26 July ruling turns that wording into a real
#: gate, so the warehouse is declared here rather than promoted to ``approve``,
#: which would hand it every other return-to-brand decision as well.
#:
#: ``ho_ops`` — the HO seat the ruling names alongside the warehouse — is
#: deliberately *not* here: the matrix gives it ``return_to_brand: view``, and a
#: viewer must not move stock. The seat that carries HO on this section is the
#: Owner. If the business wants Operations Head confirming damage, the answer is
#: the ``ApprovalPolicy`` row (data, Rule 12) or a sheet row for HO Ops — not a
#: wider list here.
_DAMAGE_CONFIRMERS = tuple(
    sorted(
        {
            *roles_with_capability("return_to_brand", CAP_APPROVE),
            *declare_role_list(
                "outbound.damage_confirmers",
                ("warehouse",),
                reason=(
                    "A store person reports damage; a warehouse or HO person confirms it "
                    "and that confirmation is what posts the piece to quarantine (#138). "
                    "Both hold `return_to_brand: operate` on the ratified sheet — the "
                    "ladder has no rung between 'may report' and 'may post', and widening "
                    "the warehouse to `approve` would also hand it RTV approval."
                ),
            ),
        }
    )
)

#: The one role the band adds on top of the approvers — a declared exception,
#: because the ladder cannot express it.
_BAND_IN_CHARGE = declare_role_list(
    "outbound.adjustment_band_in_charge",
    ("store_manager",),
    reason=(
        "The design lets the store in-charge clear a small counting variance "
        "without going to HO. That is seniority *within* a section — the manager "
        "and the cashier both hold `stock_count: operate`, and the ladder has no "
        "rung between operate and approve to separate them. Widening it to "
        "`stock_count: approve` would hand every counter the band."
    ),
)

#: Within the band, the store in-charge may clear it too (a *different* person
#: from the maker — the self-approval rule still binds).
_IN_CHARGE_ROLES = tuple(sorted({*_COUNT_APPROVERS, *_BAND_IN_CHARGE}))

#: Stock adjustments alone carry a tolerance: they are the output of counting,
#: where "book vs counted" is never going to agree to the piece, and the design
#: is explicit that a small variance auto-adjusts and is logged rather than
#: queueing behind a second person. Write-offs and V-flips have no tolerance —
#: stock leaving the books, or changing owner, always needs a second person.
_ADJ_TOLERANCE_PAISE = 2_00_000  # ₹2,000 at stake
_ADJ_BAND_PAISE = 25_00_000  # ₹25,000 — above this, HO only

KINDS: dict[type[models.Model], ApprovalKind] = {
    WriteOff: ApprovalKind("writeoff", "Write-off", _COUNT_APPROVERS, "approved_by"),
    VFlip: ApprovalKind("vflip", "V-flip", _STOCK_APPROVERS, "authorized_by"),
    StockAdjustment: ApprovalKind(
        "adjustment",
        "Stock adjustment",
        _COUNT_APPROVERS,
        "approved_by",
        tolerance_paise=_ADJ_TOLERANCE_PAISE,
        band_paise=_ADJ_BAND_PAISE,
        band_roles=_IN_CHARGE_ROLES,
    ),
    # No tolerance and no band: a gap closure decides what became of pieces that
    # went missing between two locations, and it is HO/warehouse work whatever it
    # is worth. The rule that the *receiving* store cannot be either party is
    # about entitlement rather than role, so it lives in
    # ``posting._refuse_self_closure`` — this table only says who is senior.
    TransferGapClosure: ApprovalKind("gap_closure", "Gap closure", _GAP_APPROVERS, "approved_by"),
    # No tolerance: a flag is a report about a piece, and how much that piece is
    # worth has nothing to do with whether the store may take it off the shelf
    # on its own say-so. The rung does — hence ``self_clearing``, which lets a
    # warehouse or HO person flag and confirm in the one action.
    MarkDamaged: ApprovalKind(
        "damage", "Damage flag", _DAMAGE_CONFIRMERS, "confirmed_by", self_clearing=True
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
    # A document may add what the store code alone cannot say — a gap closure is
    # meaningless in the inbox without naming the transfer it closes. Optional,
    # so nothing else has to know this hook exists.
    if subject := getattr(doc, "approval_subject", ""):
        title = f"{subject} · {title}"
    policy = _policy(kind)
    # Against the same list the request would have gone to, so retuning the
    # policy row moves both halves together (Rule 12).
    holds_the_rung = kind.self_clearing and holds_approver_role(
        requested_by, policy.approver_roles_for(value)
    )
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

    if holds_the_rung:
        return record_no_approval_needed(
            doc,
            reason=(
                f"Raised by someone who may decide a {kind.label.lower()} themselves — "
                "posted and logged, nobody else asked."
            ),
            **common,
        )

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

    approver = approval.decided_by
    if approver is None and kind.self_clearing and approval.status == ApprovalStatus.NOT_REQUIRED:
        # Nobody else was asked because the asker already held the deciding
        # rung, so the inbox has no decider to read — they are it (#138).
        approver = approval.requested_by

    # The document is still a draft here (posting hasn't flipped it), so its own
    # approver column is writable — and after this it is frozen with the rest.
    if getattr(doc, f"{kind.approver_field}_id", None) != getattr(approver, "pk", None):
        setattr(doc, kind.approver_field, approver)
        doc.save(update_fields=[kind.approver_field])
    return approval
