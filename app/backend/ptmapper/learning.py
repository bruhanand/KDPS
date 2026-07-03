"""The single write-path from a human correction to a live ``Lookup`` rule.

Every promotion of a learned mapping flows through here — a steward's review
resolution, an operator's "remember this" tick (gated on the file reaching Patna),
or the deterministic miner. ``propose()`` stages an open proposal; ``approve()``
shadow-checks it then writes the ONE ``Lookup`` (this module is the *only* runtime
writer of ``Lookup``); ``reject()`` closes it. Rule 8: a miner may only suggest — a
human decision is the sole path to a live rule. Rule 10: every write carries an
actor + timestamp. Rule 5: a shadow conflict flags (auto-reject with detail), never
silently overwrites a human-confirmed fact.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from ptmapper.engine import norm
from ptmapper.models import (
    ControlledValue,
    CorrectionEvent,
    Lookup,
    LookupProposal,
    PtFile,
    PtRow,
)

# Dimensions that resolve through a Lookup row — so a correction on them can be learned.
LEARNABLE_DIMS = {"brand", "color", "size", "season", "fit", "gender"}
# controlled dimension → the single KDPS column it fills (for shadow-checking rows).
DIM_TO_COLUMN = {
    "brand": "BRAND",
    "color": "COLOR",
    "size": "SIZE",
    "season": "SEASON",
    "fit": "FIT",
    "gender": "GENDER",
}


# ---------------------------------------------------------------- propose
def _merge_evidence(existing: dict[str, Any], incoming: dict[str, Any] | None) -> dict[str, Any]:
    """Union the list-valued evidence (event ids, files, brands); keep max occurrences."""
    out: dict[str, Any] = {**(existing or {})}
    for key in ("correction_event_ids", "files", "brands"):
        merged = list(out.get(key, []))
        for v in (incoming or {}).get(key, []):
            if v not in merged:
                merged.append(v)
        if merged:
            out[key] = merged
    if incoming and "occurrences" in incoming:
        out["occurrences"] = max(int(out.get("occurrences", 0)), int(incoming["occurrences"]))
    return out


def propose(
    *,
    dimension: str,
    source_key: str,
    target_value: str,
    brand: str = "",
    origin: str,
    evidence: dict[str, Any] | None = None,
    proposed_by: Any = None,
) -> LookupProposal:
    """Get-or-create the open proposal for ``(dimension, source_key, brand)``. Re-opens a
    prior auto-rejection (the conflict may have cleared) but never touches an approved
    or human-rejected one. Merges evidence. The partial-unique index makes a duplicate
    *open* proposal impossible, so repeat calls (the miner) mint no duplicates."""
    existing = (
        LookupProposal.objects.filter(dimension=dimension, source_key=source_key, brand=brand)
        .exclude(status__in=[LookupProposal.Status.APPROVED, LookupProposal.Status.REJECTED])
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        existing.target_value = target_value or existing.target_value
        existing.status = LookupProposal.Status.PROPOSED
        existing.evidence = _merge_evidence(existing.evidence, evidence)
        if proposed_by is not None and existing.proposed_by_id is None:
            existing.proposed_by = proposed_by
        existing.save()
        return existing
    return LookupProposal.objects.create(
        dimension=dimension,
        source_key=source_key,
        target_value=target_value,
        brand=brand,
        origin=origin,
        status=LookupProposal.Status.PROPOSED,
        evidence=evidence or {},
        proposed_by=proposed_by,
    )


# ---------------------------------------------------------------- shadow validation
def shadow_check(
    dimension: str, source_key: str, target_value: str, brand: str = ""
) -> dict[str, Any]:
    """DB-only guard on a candidate mapping (runs on Render — no sample files needed).

    Rejects when (1) an in-scope ``CorrectionEvent`` maps the same normalised raw to a
    *different* value (the growing golden set contradicts it); (2) a sent/posted
    ``PtRow`` carries this raw with provenance ``manual`` and a different confirmed
    value (a promotion must never flip a human-confirmed cell); (3) the target is not a
    Master value. Returns ``{"ok": bool, "conflicts": [{"kind", "detail"}]}``.
    """
    conflicts: list[dict[str, str]] = []

    # (3) the target must be a Master-Sheet value for this dimension
    if not ControlledValue.objects.filter(dimension=dimension, value=target_value).exists():
        conflicts.append(
            {
                "kind": "not_controlled",
                "detail": f"'{target_value}' is not a Master {dimension} value.",
            }
        )

    # (1) a human correction maps the same raw to something else (in scope: this brand,
    # or every brand when the proposal is global)
    ev = CorrectionEvent.objects.filter(dimension=dimension).exclude(new_value="")
    if brand:
        ev = ev.filter(brand=brand)
    for e in ev.iterator():
        if norm(e.raw_value) == source_key and e.new_value != target_value:
            detail = f"a human mapped {e.raw_value!r} → {e.new_value!r}, not {target_value!r}"
            conflicts.append({"kind": "correction_conflict", "detail": detail})
            break

    # (2) a human-confirmed cell on a file that already left the warehouse must never
    # flip — scoped exactly like (1): a brand-scoped proposal only conflicts with its
    # own brand's rows (a global proposal, which would flip every brand, checks all).
    col = DIM_TO_COLUMN.get(dimension)
    if col:
        for row in PtRow.objects.filter(pt_file__sent_at__isnull=False).iterator():
            if brand and str((row.data or {}).get("BRAND") or "").strip() != brand:
                continue
            if (
                norm(str((row.raw or {}).get(col, ""))) == source_key
                and (row.provenance or {}).get(col) == "manual"
                and str(row.data.get(col) or "") != target_value
            ):
                detail = f"a sent file confirms {col}={row.data.get(col)!r} for this raw"
                conflicts.append({"kind": "manual_cell_conflict", "detail": detail})
                break

    return {"ok": not conflicts, "conflicts": conflicts}


# ---------------------------------------------------------------- decisions
def approve(proposal: LookupProposal, actor: Any) -> LookupProposal:
    """Promote a proposal to a live ``Lookup`` (the only runtime ``Lookup`` write).

    Shadow-checks first; a conflict flips the proposal to ``auto_rejected`` with the
    detail (no write). On success it upserts the brand-scoped ``Lookup``, stamps the
    actor + timestamps, and repropagates to mapping-stage drafts. Idempotent: an
    already-approved proposal is returned untouched.
    """
    if proposal.status == LookupProposal.Status.APPROVED:
        return proposal
    validation = shadow_check(
        proposal.dimension, proposal.source_key, proposal.target_value, proposal.brand
    )
    proposal.validation = validation
    proposal.decided_by = actor
    proposal.decided_at = timezone.now()
    if not validation["ok"]:
        proposal.status = LookupProposal.Status.AUTO_REJECTED
        proposal.save()
        return proposal
    Lookup.objects.update_or_create(
        dimension=proposal.dimension,
        source_key=proposal.source_key,
        brand=proposal.brand,
        defaults={"target_value": proposal.target_value},
    )
    proposal.status = LookupProposal.Status.APPROVED
    proposal.applied_at = timezone.now()
    proposal.save()
    repropagate()
    return proposal


def reject(proposal: LookupProposal, actor: Any) -> LookupProposal:
    """Close a proposal without writing a ``Lookup``. An already-applied (approved)
    proposal is left alone — a live rule is demoted by a separate decision, not here."""
    if proposal.status == LookupProposal.Status.APPROVED:
        return proposal
    proposal.status = LookupProposal.Status.REJECTED
    proposal.decided_by = actor
    proposal.decided_at = timezone.now()
    proposal.save()
    return proposal


def promote_file_remembers(pt: PtFile, actor: Any) -> int:
    """On a file's SENT transition (D1: sending is the trust gate), approve every open
    remember-proposal of that file. The actor of record is each proposal's original
    ticker; ``actor`` (the sender) is only the fallback. Returns the count promoted."""
    proposals = LookupProposal.objects.filter(
        origin=LookupProposal.Origin.REMEMBER,
        status=LookupProposal.Status.PROPOSED,
        evidence__files__contains=[pt.pk],
    )
    n = 0
    for p in proposals:
        approve(p, p.proposed_by or actor)
        n += 1
    return n


# ---------------------------------------------------------------- repropagation
def repropagate() -> None:
    """Re-map **every** mapping-stage *brand* draft so a newly-approved rule fills its
    blanks everywhere. Preserve-manual (D2) makes even a hand-edited draft safe to re-map
    — the learned rule fills the remaining blanks while every manual cell is re-applied on
    top. Sent/posted files are frozen (the FSM freeze stands — never re-mapped). The
    ``learning.approve`` and the review/taxonomy resolution paths all share this one
    function.

    Authored (invoice-source) drafts are **excluded**: their stored file is the invoice
    photo, not a brand workbook, so ``process_file`` would delete the authored rows and
    fail. They are enriched from the invoice once, at creation, and never re-mapped."""
    from ptmapper.views import process_file  # lazy import: break the views→learning cycle

    for pt in PtFile.objects.filter(
        draft_stage=PtFile.DraftStage.MAPPING, source=PtFile.Source.BRAND_FILE
    ):
        process_file(pt, preserve_manual=True)
