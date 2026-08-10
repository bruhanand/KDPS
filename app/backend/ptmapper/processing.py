"""PT (re)mapping pipeline — the one function that runs the engine over a stored
brand file and (re)builds its rows + review queue, plus the pure helpers it needs.

Extracted out of ``ptmapper.views`` so the mapping pipeline has no dependency on
the HTTP layer: ``views`` and ``learning`` both import ``process_file`` from here,
and this module imports only ``engine`` / ``models`` / ``profiles`` — a one-way
dependency graph that removes the old ``views`` ⇄ ``learning`` import cycle.
"""

from __future__ import annotations

from typing import Any

from ptmapper.engine import UnsupportedFormat, _margin, _quantity_out, num, run_mapping
from ptmapper.models import PtFile, PtRow, ReviewItem
from ptmapper.profiles import CONTROLLED as CONTROLLED_COLS
from ptmapper.profiles import KDPS_COLUMNS

KDPS_COLUMN_SET = set(KDPS_COLUMNS)


def _recompute_derived(row: PtRow, changed_cols: set[str]) -> None:
    """NAG mirrors QTY; MARGIN re-derives from MRP / P RATE — never hand-entered."""
    new_prov = {**(row.provenance or {})}
    new_data = {**row.data}
    if "QTY" in changed_cols:
        new_data["NAG"] = _quantity_out(num(row.data.get("QTY")))
        new_prov["NAG"] = "derived"
    if changed_cols & {"MRP", "P RATE"}:
        new_data["MARGIN"] = _margin(num(row.data.get("MRP")), num(row.data.get("P RATE")))
        new_prov["MARGIN"] = "derived"
    row.data = new_data
    row.provenance = new_prov


def _sync_review_items(reviews: list[dict[str, Any]]) -> int:
    """Upsert each engine miss into the review queue; return the open count.

    A fresh miss for a raw whose item is already RESOLVED means the earlier
    resolution was brand-scoped (D4) and does not cover this row's brand — the engine
    records a miss only when neither a brand nor a global lookup fired, so the value is
    genuinely still unmapped here. The item is re-opened (its stale ``resolved_value``
    cleared) and re-scoped to the brand(s) that still miss, so it can't be silently
    swallowed for another brand. An IGNORED item stays ignored — a steward's decision
    that a value is noise must survive every re-map."""
    open_count = 0
    for m in reviews:
        # `brands` = the resolved brand(s) this miss came from → a review resolution
        # can default to brand scope when there is exactly one (D4).
        context = {"samples": m["samples"], "brands": m.get("brands", [])}
        obj, created = ReviewItem.objects.get_or_create(
            dimension=m["dimension"],
            raw_value=m["raw"][:300],
            defaults={"occurrences": m["occurrences"], "context": context},
        )
        if not created and obj.status != ReviewItem.Status.IGNORED:
            obj.status = ReviewItem.Status.OPEN
            obj.occurrences = m["occurrences"]
            obj.context = context
            obj.resolved_value = ""
            obj.save(
                update_fields=["status", "occurrences", "context", "resolved_value", "updated_at"]
            )
        if obj.status == ReviewItem.Status.OPEN:
            open_count += 1
    return open_count


def _fail_file(pt: PtFile, error: str, reset_counts: bool = False) -> PtFile:
    pt.status = PtFile.Status.FAILED
    pt.error = error
    if reset_counts:
        pt.row_count = pt.unresolved_count = pt.blank_cell_count = 0
    pt.save()
    return pt


def _snapshot_manual(pt: PtFile) -> dict[int, dict[str, Any]]:
    """{line_no: {col: value}} of every cell a human set (provenance 'manual'), taken
    before the rows are wiped so a re-map can re-apply them (D2: preserve-by-default)."""
    snap: dict[int, dict[str, Any]] = {}
    for r in pt.rows.all():
        prov = r.provenance or {}
        cells = {c: v for c, v in (r.data or {}).items() if prov.get(c) == "manual"}
        if cells:
            snap[r.line_no] = cells
    return snap


def _reapply_manual(
    pt: PtFile, snapshot: dict[int, dict[str, Any]], blank_cells: int
) -> tuple[int, int, int]:
    """Re-stamp the snapshotted manual cells onto the freshly-mapped rows (matched by
    ``line_no``; the engine is deterministic over the same bytes, so line_no is stable).
    Returns ``(blank_cells, applied_count, dropped_count)`` — a cell whose row vanished
    (profile detection changed) is dropped and reported, never silently lost."""
    rebuilt = {r.line_no: r for r in pt.rows.all()}
    touched: list[PtRow] = []
    applied = dropped = 0
    for line_no, cells in snapshot.items():
        r = rebuilt.get(line_no)
        if r is None:
            dropped += len(cells)
            continue
        new_data = {**r.data}
        new_prov = {**(r.provenance or {})}
        new_blanks = list(r.blanks)
        recompute: set[str] = set()
        for c, v in cells.items():
            if c not in KDPS_COLUMN_SET:
                dropped += 1
                continue
            new_data[c] = v
            new_prov[c] = "manual"  # a human set it → stays trusted through the re-map
            recompute.add(c)
            applied += 1
            # Keep blank tracking honest in both directions: a manual value fills a
            # blank; a manual clear of a controlled cell re-opens one — otherwise a
            # deliberately-cleared cell reads as filled when the engine had filled it.
            if c in CONTROLLED_COLS:
                if str(v or "").strip():
                    if c in new_blanks:
                        new_blanks.remove(c)
                        blank_cells -= 1
                elif c not in new_blanks:
                    new_blanks.append(c)
                    blank_cells += 1
        r.data, r.provenance, r.blanks = new_data, new_prov, new_blanks
        _recompute_derived(r, recompute)
        touched.append(r)
    if touched:
        PtRow.objects.bulk_update(touched, ["data", "provenance", "blanks"])
    return blank_cells, applied, dropped


def process_file(pt: PtFile, preserve_manual: bool = True) -> PtFile:
    """Run the engine over the stored bytes and (re)build rows + review items.

    ``preserve_manual`` (default, D2): a human's hand-edited cells are snapshotted and
    re-applied after the rebuild, so a re-map (a learned rule landing, a re-run) fills
    the remaining blanks without ever clobbering a manual cell. Pass ``False`` for the
    explicit full-wipe re-run."""
    if pt.source == PtFile.Source.INVOICE:
        # An authored PT has no brand workbook — its stored file is the invoice photo.
        # Re-mapping it would delete the authored rows and fail the file. Never here.
        return pt
    snapshot = _snapshot_manual(pt) if preserve_manual else {}
    pt.rows.all().delete()
    if not pt.stored_file:
        return _fail_file(pt, "The uploaded file is no longer available.")
    content = bytes(pt.stored_file.content)
    context = (pt.meta or {}).get("context") or {}
    try:
        result = run_mapping(
            content, pt.original_filename, pt.stored_file.content_type, context or None
        )
    except UnsupportedFormat as exc:
        return _fail_file(pt, str(exc), reset_counts=True)
    except Exception as exc:  # noqa: BLE001
        return _fail_file(pt, f"Could not read this file: {exc}")

    PtRow.objects.bulk_create(
        [
            PtRow(
                pt_file=pt,
                line_no=r["line_no"],
                data=r["data"],
                blanks=r["blanks"],
                provenance=r.get("provenance", {}),
                raw=r.get("raw", {}),
            )
            for r in result["rows"]
        ]
    )
    blank_cells = result["blank_cells"]
    applied = dropped = 0
    if snapshot:
        blank_cells, applied, dropped = _reapply_manual(pt, snapshot, blank_cells)
    open_count = _sync_review_items(result["reviews"])

    pt.profile_code = result["profile_code"]
    pt.profile_name = result["profile_name"]
    pt.archetype = result["archetype"]
    pt.brand_guess = result["brand_guess"]
    pt.meta = {
        **result["meta"],
        "low_confidence_cells": result.get("low_confidence_cells", 0),
        **({"context": context} if context else {}),
        **({"manual_cells_dropped": dropped} if dropped else {}),
    }
    pt.row_count = len(result["rows"])
    pt.blank_cell_count = blank_cells
    pt.unresolved_count = open_count
    pt.manually_edited = applied > 0  # keeps the flag only while manual cells survive
    pt.status = (
        PtFile.Status.READY
        if (pt.row_count > 0 and open_count == 0)
        else PtFile.Status.NEEDS_REVIEW
    )
    pt.error = ""
    pt.save()
    return pt
