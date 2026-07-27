"""PT Mapper API — upload a brand file, map it deterministically, review the
unmapped queue, resolve a value (which grows the lookup tables), and export KDPS
rows. The mapping engine has no AI; the only AI is the *authored* (from-GRN)
path's invoice prefill, which is reviewable and never final (Rule 8).
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any

import openpyxl
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.actor_policies import user_may_act
from core.documents import DocStatus
from files.models import StoredFile, UploadTooLarge
from inbound.models import Grn
from masters.models import CategoryMargin, GstSlab, Store
from masters.scoping import scope_by_store
from ptmapper import learning
from ptmapper.authoring import build_pt_from_grn, enrich_from_invoice
from ptmapper.engine import (
    norm,
    parse_date,
)
from ptmapper.learning import LEARNABLE_DIMS
from ptmapper.models import (
    ControlledValue,
    CorrectionEvent,
    ItemTaxonomy,
    Lookup,
    LookupProposal,
    PtFile,
    PtRow,
    ReviewItem,
    TaxonomyRule,
)
from ptmapper.pricing import Slab, price_from_rate
from ptmapper.processing import _recompute_derived, process_file
from ptmapper.profiles import CONTROLLED as CONTROLLED_COLS
from ptmapper.profiles import KDPS_COLUMNS
from ptmapper.serializers import (
    LookupProposalSerializer,
    PtFileDetailSerializer,
    PtFileListSerializer,
    ReviewItemSerializer,
)
from stockledger.posting import (
    PtPostingError,
    post_pt_inward,
    reverse_pt_inward,
)
from vendors.models import Booking

SINGLE_DIMS = {"color", "size", "brand", "season", "fit"}
KDPS_COLUMN_SET = set(KDPS_COLUMNS)

# Hand-editable columns that are vocabulary-controlled: the 9 Master-Sheet columns
# plus the two tax columns (validated against the Master 'gst' dimension).
GST_COLUMNS = {"INPUT TAX", "OUTPUT TAX"}


def _column_dimension(col: str) -> str | None:
    if col in CONTROLLED_COLS:
        return CONTROLLED_COLS[col]
    if col in GST_COLUMNS:
        return "gst"
    return None


def _gst_str(v: Any) -> str:
    """'5.0' / 5.0 → '5', so a numeric tax cell compares against the Master '5'."""
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s


def _valid_values() -> dict[str, set[str]]:
    valid: dict[str, set[str]] = {}
    for cv in ControlledValue.objects.all():
        valid.setdefault(cv.dimension, set()).add(cv.value)
    return valid


def _cell_error(col: str, val: Any, valid: dict[str, set[str]]) -> str:
    """'' when the value is allowed in this column; else a human reason. Blank is
    always allowed (clearing a cell keeps it in the blank-count workflow)."""
    dim = _column_dimension(col)
    if dim is None:
        return ""  # uncontrolled column (BARCODE, QTY, MRP…) — free entry
    s = _gst_str(val) if dim == "gst" else str(val).strip()
    if not s or s in valid.get(dim, set()):
        return ""
    return f"'{s}' is not an allowed Master-Sheet {dim} value."


def _parse_context(data: Any) -> tuple[dict, Response | None]:
    """Optional operator context on upload/re-run: brand (a Master brand, matched
    case-insensitively to its canonical spelling) + invoice date."""
    ctx: dict[str, str] = {}
    brand = str(data.get("brand") or "").strip()
    if brand:
        master = ControlledValue.objects.filter(dimension="brand", value__iexact=brand).first()
        if not master:
            return {}, Response({"detail": f"'{brand}' is not a Master-Sheet brand."}, status=400)
        ctx["brand"] = master.value
    inv_date = str(data.get("invoice_date") or "").strip()
    if inv_date:
        d = parse_date(inv_date)
        if not d:
            return {}, Response(
                {"detail": "invoice_date must be a valid date (YYYY-MM-DD)."}, status=400
            )
        ctx["invoice_date"] = d.isoformat()
    return ctx, None


PT_INWARD_ACTION = "ptmapper.post_and_reverse_pt"
MAPPING_STEWARDSHIP_ACTION = "ptmapper.mapping_stewardship"


def _forbidden(detail: str) -> Response:
    return Response({"detail": detail}, status=status.HTTP_403_FORBIDDEN)


class PtFileListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> Any:
        # Fail-closed store scoping by the linked GRN's store, mirroring /inbound/grns.
        # An unrestricted user (scope=all) is unaffected; a scoped user never sees
        # another store's PT (a NULL-grn legacy upload has no store → out of scope).
        return scope_by_store(PtFile.objects.all(), self.request.user, "grn__store_id")

    def get_serializer_class(self):
        return PtFileListSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "A file is required."}, status=400)
        context, err = _parse_context(request.data)
        if err is not None:
            return err
        grn_pk = None
        grn_id = request.data.get("grn")
        if grn_id not in (None, ""):
            try:
                grn_pk = int(grn_id)
            except (TypeError, ValueError):
                return Response({"detail": "grn must be a GRN id."}, status=400)
        # Optional link to the received arrival (D3): a brand PT is mapped *for* a
        # specific invoice/GRN. This is a reference link only — no posting — so the
        # warehouse-only restriction that guards the from-grn authoring path does NOT
        # apply (branded goods legitimately land at stores). But the GRN must be in the
        # caller's store scope (fail-closed, Codex #2) and the link + one-live-PT check +
        # create must be atomic under a GRN row lock so two concurrent uploads can't both
        # slip past the check (Codex #3) — mirroring the from-grn path.
        try:
            with transaction.atomic():
                grn = None
                if grn_pk is not None:
                    grn = (
                        scope_by_store(
                            Grn.objects.select_for_update(of=("self",)), request.user, "store_id"
                        )
                        .filter(pk=grn_pk)
                        .first()
                    )
                    if not grn:
                        return Response({"detail": "GRN not found."}, status=404)
                    live = grn.pt_files.exclude(docstatus=DocStatus.CANCELLED).first()
                    if live:
                        return Response(
                            {
                                "detail": f"This GRN already has a PT in progress "
                                f"({live.stage_label}).",
                                "pt_file_id": live.id,
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                stored = StoredFile.from_upload(upload, StoredFile.Kind.PT_FILE, request.user)
                pt = PtFile.objects.create(
                    stored_file=stored,
                    original_filename=stored.filename,
                    grn=grn,
                    meta={"context": context} if context else {},
                    created_by=request.user
                    if getattr(request.user, "is_authenticated", False)
                    else None,
                )
        except UploadTooLarge as exc:
            return Response({"detail": str(exc)}, status=413)
        process_file(pt)
        return Response(PtFileDetailSerializer(pt).data, status=status.HTTP_201_CREATED)


class PtFileFromGrnView(APIView):
    """Start the non-brand PT for an arrival: seed a DRAFT ``PtFile(source=invoice)``
    from the GRN's counted lines, then best-effort AI-prefill money cells from the
    stored invoice. One live PT per GRN — a second call returns 409 pointing at it
    (a reversed PT frees the slot; you author again, never edit)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, grn_id: int) -> Response:
        if not user_may_act(request.user, MAPPING_STEWARDSHIP_ACTION):
            return _forbidden("Only warehouse/HO mapping stewards can make a PT from a GRN.")
        with transaction.atomic():
            # The row lock serialises concurrent make-PT clicks on one arrival
            # (of=("self",): lock only the GRN row — vendor/invoice_file join NULLable).
            grn = (
                Grn.objects.select_for_update(of=("self",))
                .select_related("vendor", "invoice_file")
                .filter(pk=grn_id)
                .first()
            )
            if not grn:
                return Response({"detail": "GRN not found."}, status=404)
            if grn.docstatus != DocStatus.SUBMITTED:
                return Response({"detail": "Only a posted receipt can become a PT."}, status=409)
            if grn.store.store_type != Store.StoreType.WAREHOUSE:
                # Non-branded authoring is a warehouse activity: goods land at a warehouse,
                # get counted, and a KDPS PT is authored from the count. A store-received
                # arrival is the *branded* path (the Mapper uploads the brand PT), never
                # authored here — the two paths must not cross.
                return Response(
                    {
                        "detail": "Authoring a PT from a receipt is available only at a "
                        "warehouse — store-received arrivals are the branded (Mapper) path."
                    },
                    status=409,
                )
            live = grn.pt_files.exclude(docstatus=DocStatus.CANCELLED).first()
            if live:
                return Response(
                    {
                        "detail": f"This GRN already has a PT in progress ({live.stage_label}).",
                        "pt_file_id": live.id,
                    },
                    status=409,
                )
            pt = build_pt_from_grn(grn, request.user)
        # Outside the transaction: the AI read can take seconds and must never hold
        # the GRN lock or roll back the authored file — failure only annotates it.
        enrich_from_invoice(pt, grn)
        pt.refresh_from_db()
        return Response(PtFileDetailSerializer(pt).data, status=status.HTTP_201_CREATED)


class PtFileDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PtFileDetailSerializer
    queryset = PtFile.objects.prefetch_related("rows")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pt = self.get_object()
        if pt.stage != PtFile.Stage.MAPPING:
            return Response(
                {
                    "detail": "Only files still in mapping can be deleted; "
                    "sent/posted files are immutable (append-only audit)."
                },
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)


class PtFileRerunView(APIView):
    """Re-map a mapping-stage file. By default (D2) hand-edited cells are **preserved**
    — the engine re-runs and the human's manual cells are re-applied on top, so a fresh
    seed/rule fills the remaining blanks without clobbering a manual fix. Passing
    ``{"discard_edits": true}`` is the explicit full wipe (today's behaviour)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.source == PtFile.Source.INVOICE:
            # The stored file behind an authored PT is the invoice photo/PDF, not a
            # brand sheet — re-mapping it would wipe the authored rows for nothing.
            return Response(
                {"detail": "An authored (from-GRN) PT has no brand file to re-map."}, status=409
            )
        if pt.stage != PtFile.Stage.MAPPING:
            return Response({"detail": "Only files still in mapping can be re-run."}, status=409)
        if "brand" in request.data or "invoice_date" in request.data:
            # The re-run form always sends both fields, so the payload replaces the
            # whole stored context (blank fields clear it).
            context, err = _parse_context(request.data)
            if err is not None:
                return err
            meta = {**(pt.meta or {})}
            meta.pop("context", None)
            if context:
                meta["context"] = context
            pt.meta = meta
            pt.save(update_fields=["meta", "updated_at"])
        discard = bool(request.data.get("discard_edits"))
        process_file(pt, preserve_manual=not discard)
        return Response(PtFileDetailSerializer(pt).data)


def _recompute_counts(pt: PtFile) -> None:
    """Re-derive blank/unresolved counts from the (possibly hand-edited) rows."""
    blank_cells = 0
    rows = list(pt.rows.all())
    for r in rows:
        blanks = [c for c, dim in CONTROLLED_COLS.items() if not str(r.data.get(c) or "").strip()]
        r.blanks = blanks
        blank_cells += len(blanks)
    PtRow.objects.bulk_update(rows, ["blanks"])
    pt.blank_cell_count = blank_cells
    pt.row_count = len(rows)
    pt.status = (
        PtFile.Status.READY
        if (rows and pt.unresolved_count == 0 and blank_cells == 0)
        else PtFile.Status.NEEDS_REVIEW
    )


def _cell_changed(old: Any, new: Any) -> bool:
    """True when a hand-edit actually alters the cell (blank/None/number-vs-string
    are compared as trimmed strings, so re-entering the same value is a no-op)."""
    return str("" if old is None else old).strip() != str("" if new is None else new).strip()


def _apply_cell(
    row: PtRow,
    col: str,
    val: Any,
    changed: dict[int, set[str]],
    *,
    events: list[CorrectionEvent],
    actor: Any,
    kind: str,
    pt: PtFile,
) -> None:
    """Apply one hand-edit and, *only when the value truly changes*, append an
    unsaved CorrectionEvent (the learning signal + Rule-10 actor trail). The event
    captures the raw source value and prior provenance so a mined rule keeps its
    provenance even after the PtRow dies on the next re-map."""
    old = row.data.get(col)
    if not _cell_changed(old, val):
        return
    prov_before = str((row.provenance or {}).get(col, ""))
    raw_value = str((row.raw or {}).get(col, ""))
    row.data = {**row.data, col: val}
    row.provenance = {**(row.provenance or {}), col: "manual"}  # a human set it → trusted
    changed.setdefault(row.id, set()).add(col)
    events.append(
        CorrectionEvent(
            pt_file=pt,
            pt_row=row,
            file_name=pt.original_filename[:255],
            line_no=row.line_no,
            brand=str(row.data.get("BRAND") or "")[:160],  # resolved BRAND post-edit
            column=col,
            dimension=_column_dimension(col) or "",
            raw_value=raw_value[:300],
            old_value=str("" if old is None else old)[:300],
            new_value=str("" if val is None else val)[:300],
            provenance_before=prov_before,
            edit_kind=kind,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
        )
    )


def _fill_kind(scope: Any) -> str:
    if scope == "all":
        return CorrectionEvent.EditKind.FILL_ALL
    if isinstance(scope, dict) and "match_raw" in scope:
        return CorrectionEvent.EditKind.FILL_MATCH_RAW
    return CorrectionEvent.EditKind.FILL_BLANK


def _plan_remembers(
    remember: list[dict], by_id: dict[int, PtRow]
) -> tuple[list[tuple[int, str, str, str, str, str]], list[dict]]:
    """Validate each ``{"row_id","column"}`` remember tick against its post-edit row and
    return ``(plan, errors)``. A plan entry is ``(row_id, column, dimension, source_key,
    target, brand)`` — a learnable column with a non-empty raw source and a non-blank
    value; the rule is scoped to the row's resolved BRAND (D4)."""
    plan: list[tuple[int, str, str, str, str, str]] = []
    errors: list[dict] = []
    for spec in remember:
        rid = spec.get("row_id")
        col = spec.get("column", "")
        r = by_id.get(int(rid)) if rid is not None else None
        if r is None:
            errors.append({"detail": f"remember: row {rid} is not in this file."})
            continue
        dim = _column_dimension(col)
        if dim not in LEARNABLE_DIMS:
            errors.append({"column": col, "detail": f"'{col}' isn't a learnable column."})
            continue
        raw_val = str((r.raw or {}).get(col, "")).strip()
        target = str(r.data.get(col) or "").strip()
        if not raw_val:
            errors.append({"column": col, "detail": f"'{col}' has no raw source value to learn."})
            continue
        if not target:
            errors.append({"column": col, "detail": f"'{col}' is blank — nothing to remember."})
            continue
        brand = str(r.data.get("BRAND") or "").strip()
        plan.append((r.id, col, dim, norm(raw_val), target, brand))
    return plan, errors


def _fill_applies(row: PtRow, col: str, scope: Any) -> bool:
    if scope == "all":
        return True
    if scope == "blank":
        return not str(row.data.get(col) or "").strip()
    if isinstance(scope, dict) and "match_raw" in scope:
        return (row.raw or {}).get(col, "") == scope["match_raw"]
    return False


class PtRowsUpdateView(APIView):
    """Warehouse hand-edits the mapped KDPS rows before sending to Patna.

    Body: ``{"rows": [{"id", "data": {col: val}}], "fills": [{"column", "value",
    "scope": "blank" | "all" | {"match_raw": <raw>}}], "remember": [{"row_id",
    "column"}]}`` — all optional. Every edited controlled cell (the 9 Master columns
    + the two tax columns) must hold an allowed Master-Sheet value or be blank;
    anything else is a 400 with per-cell errors and nothing is written. Fills run
    first, then row edits. A ``remember`` entry stages a brand-scoped learning
    proposal from that cell's raw source → its (post-edit) value (D1: it promotes to
    a live rule when the file is sent to Patna, or immediately if it is already sent).
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request: Request, pk: int) -> Response:
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage in (PtFile.Stage.POSTED, PtFile.Stage.REVERSED):
            return Response({"detail": "Posted/reversed files are locked."}, status=409)

        edits = {int(e["id"]): e.get("data", {}) for e in request.data.get("rows", []) if "id" in e}
        fills = request.data.get("fills", [])
        remember = request.data.get("remember", [])

        valid = _valid_values()
        errors: list[dict] = []
        for rid, data in edits.items():
            for col, val in data.items():
                if col not in KDPS_COLUMN_SET:
                    continue
                reason = _cell_error(col, val, valid)
                if reason:
                    errors.append({"row_id": rid, "column": col, "value": val, "detail": reason})
        clean_fills: list[tuple[str, Any, Any]] = []
        for f in fills:
            col = f.get("column", "")
            val = f.get("value", "")
            scope = f.get("scope", "blank")
            if col not in KDPS_COLUMN_SET:
                errors.append({"column": col, "detail": f"Unknown column {col!r}."})
                continue
            reason = _cell_error(col, val, valid)
            if reason:
                errors.append({"column": col, "value": val, "detail": reason})
                continue
            clean_fills.append((col, val, scope))
        if errors:
            return Response(
                {"detail": "Some values are not allowed Master-Sheet values.", "errors": errors},
                status=400,
            )

        remember_ids = {int(s["row_id"]) for s in remember if "row_id" in s}
        if clean_fills:
            rows = list(pt.rows.all())
        else:
            rows = list(pt.rows.filter(id__in=set(edits.keys()) | remember_ids))
        by_id = {r.id: r for r in rows}
        changed: dict[int, set[str]] = {}
        events: list[CorrectionEvent] = []
        actor = request.user

        for col, val, scope in clean_fills:
            kind = _fill_kind(scope)
            for r in rows:
                if _fill_applies(r, col, scope):
                    _apply_cell(r, col, val, changed, events=events, actor=actor, kind=kind, pt=pt)
        for rid, data in edits.items():
            r = by_id.get(rid)
            if r is None:
                continue
            for col, val in data.items():
                if col in KDPS_COLUMN_SET:
                    _apply_cell(
                        r,
                        col,
                        val,
                        changed,
                        events=events,
                        actor=actor,
                        kind=CorrectionEvent.EditKind.CELL,
                        pt=pt,
                    )

        # Plan the remember-proposals off the *post-edit* in-memory rows; a bad remember
        # is a 400 with nothing written (validation runs before any DB write below).
        remember_plan, rem_errors = _plan_remembers(remember, by_id)
        if rem_errors:
            return Response(
                {"detail": "Some cells can't be remembered.", "errors": rem_errors}, status=400
            )

        touched = [by_id[rid] for rid in changed]
        for r in touched:
            _recompute_derived(r, changed[r.id])
        PtRow.objects.bulk_update(touched, ["data", "provenance"])
        remember_cells = {(rid, col) for rid, col, *_ in remember_plan}
        for e in events:
            if (e.pt_row_id, e.column) in remember_cells:
                e.remember = True
        CorrectionEvent.objects.bulk_create(events)  # append-only; rejected PATCH wrote nothing

        already_sent = pt.draft_stage == PtFile.DraftStage.SENT
        for _rid, _col, dim, source_key, target, brand in remember_plan:
            proposal = learning.propose(
                dimension=dim,
                source_key=source_key,
                target_value=target,
                brand=brand,
                origin=LookupProposal.Origin.REMEMBER,
                proposed_by=actor if getattr(actor, "is_authenticated", False) else None,
                evidence={"files": [pt.pk], "brands": [brand] if brand else []},
            )
            if already_sent:  # D1: edits on an already-sent file promote immediately
                learning.approve(proposal, actor)

        pt.manually_edited = True
        _recompute_counts(pt)
        pt.save()
        return Response(PtFileDetailSerializer(pt).data)


def _invoice_send_blocks(pt: PtFile) -> list[dict]:
    """The hard gates before an authored PT may leave the warehouse (invoice source
    only — the brand path is untouched): every row needs a BARCODE (keep-if-present;
    else the warehouse generates it in the counter software and types it — manual for
    now; generation moves in-house with the KDPS-built POS) and a SEASON (the
    canonical-season block, Q39 — the editor already restricts the cell to
    Master-Sheet seasons, this refuses blanks)."""
    problems: list[dict] = []
    for row in pt.rows.all():
        missing = [c for c in ("BARCODE", "SEASON") if not str(row.data.get(c) or "").strip()]
        if missing:
            problems.append({"line_no": row.line_no, "missing": missing})
    return problems


class PtFileSendView(APIView):
    """Warehouse → Patna: hand the mapped draft over for review/posting."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request: Request, pk: int) -> Response:
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage != PtFile.Stage.MAPPING:
            return Response({"detail": "This file is not in the mapping stage."}, status=409)
        if pt.row_count == 0:
            return Response({"detail": "Nothing to send — the file has no rows."}, status=409)
        if pt.source == PtFile.Source.INVOICE:
            problems = _invoice_send_blocks(pt)
            if problems:
                return Response(
                    {
                        "detail": "Every row needs a barcode and a season before this "
                        "authored PT can go to Patna.",
                        "rows": problems,
                    },
                    status=409,
                )
        pt.draft_stage = PtFile.DraftStage.SENT
        pt.sent_at = timezone.now()
        pt.save(update_fields=["draft_stage", "sent_at", "updated_at"])
        # D1: sending to Patna is the trust gate — promote this file's remember-ticks.
        learning.promote_file_remembers(pt, request.user)
        return Response(PtFileDetailSerializer(pt).data)


class PtFileRecallView(APIView):
    """Patna sends a file back to the warehouse for further edits."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage != PtFile.Stage.SENT:
            return Response({"detail": "Only sent files can be returned."}, status=409)
        pt.draft_stage = PtFile.DraftStage.MAPPING
        pt.sent_at = None
        pt.save(update_fields=["draft_stage", "sent_at", "updated_at"])
        return Response(PtFileDetailSerializer(pt).data)


class PtFilePostView(APIView):
    """Patna pushes the reviewed file into the KDPS system: writes the append-only
    stock-ledger inward + (optionally) reconciles a booking, then locks the file."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        if not user_may_act(request.user, PT_INWARD_ACTION):
            return _forbidden("Only Accounts or Owner can post a PT into the system.")
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage != PtFile.Stage.SENT:
            return Response({"detail": "Only files sent to Patna can be posted."}, status=409)
        booking = None
        booking_id = request.data.get("booking_id")
        if booking_id:
            booking = Booking.objects.filter(pk=booking_id).first()
            if not booking:
                return Response({"detail": "Booking not found."}, status=400)
        # The GRN's own booking is the source of truth for the commercial model: a booked
        # SOR/consignment arrival must post against it (Dr INVENTORY / Cr the vendor
        # payable), not fall through to "Direct receipt" because the request omitted it.
        grn_booking = pt.grn.booking if pt.grn_id else None
        if grn_booking is not None:
            if booking is not None and booking.pk != grn_booking.pk:
                return Response(
                    {
                        "detail": "This PT's GRN is booked against a different booking — "
                        "post it against its own booking or send none."
                    },
                    status=409,
                )
            booking = grn_booking
        try:
            result = post_pt_inward(pt, request.user, booking=booking)
        except PtPostingError as exc:
            return Response({"detail": str(exc)}, status=422)
        data = PtFileDetailSerializer(pt).data
        data["post_result"] = result
        return Response(data)


class PtFileReverseView(APIView):
    """Append-only correction: reverse a posted PT inward (negative mirror stock + GL
    rows, vendor-bill reversal) and `cancel()` the file (reversal-as-cancel) — the
    posted fact is frozen forever; you re-upload to re-post."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        if not user_may_act(request.user, PT_INWARD_ACTION):
            return _forbidden("Only Accounts or Owner can reverse a posted PT.")
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage != PtFile.Stage.POSTED:
            return Response({"detail": "Only a posted file can be reversed."}, status=409)
        result = reverse_pt_inward(pt, request.user)
        data = PtFileDetailSerializer(pt).data
        data["reverse_result"] = result
        return Response(data)


def _price_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    # ``Decimal("inf")``/``Decimal("nan")`` parse cleanly but poison every downstream
    # comparison and gross-up — a free-entry "inf" P RATE or margin must read as invalid.
    return d if d.is_finite() else None


def _gst_cell(pct: Decimal) -> int | float:
    """A GST-percent cell: whole values collapse to int (5 not 5.0) so it compares clean
    against the Master '5'/'18', fractional slabs keep their decimal."""
    return int(pct) if pct == int(pct) else float(pct)


class PtFilePriceView(APIView):
    """Price the blank rows of an authored PT deterministically (D2 Q7): for every
    row with a purchase rate but no MRP, derive MRP / taxes / margin via
    ``ptmapper.pricing`` — margin from the ``CategoryMargin`` master (row ITEM,
    falling back to the global default), GST from the date-effective ``GstSlab``.
    ``{"margin_pct": …}`` overrides the margin, validated server-side against each
    priced row's category band; one out-of-band row rejects the whole call.
    Written cells carry provenance ``derived``. Source-gated: never a brand file."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request: Request, pk: int) -> Response:
        if not user_may_act(request.user, MAPPING_STEWARDSHIP_ACTION):
            return _forbidden("Only warehouse/HO mapping stewards can price an authored PT.")
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.source != PtFile.Source.INVOICE:
            return Response(
                {
                    "detail": "Only authored (from-GRN) PTs are priced here — brand files "
                    "carry the brand's own MRP."
                },
                status=409,
            )
        if pt.stage in (PtFile.Stage.POSTED, PtFile.Stage.REVERSED):
            return Response({"detail": "Posted/reversed files are locked."}, status=409)

        slab_row = GstSlab.objects.filter(effective_from__lte=timezone.now().date()).first()
        if slab_row is None:
            return Response({"detail": "No GST slab is effective — seed masters first."}, 422)
        slab = Slab(
            threshold=Decimal(slab_row.threshold_paise) / 100,
            rate_below=Decimal(slab_row.rate_below),
            rate_above=Decimal(slab_row.rate_above),
        )
        margins = {m.item: m for m in CategoryMargin.objects.filter(is_active=True)}
        default_margin = margins.get("")
        if default_margin is None:
            return Response(
                {"detail": "No default category margin is seeded — add one in masters."},
                status=422,
            )

        override = _price_decimal(request.data.get("margin_pct"))
        if request.data.get("margin_pct") not in (None, "") and override is None:
            return Response({"detail": "margin_pct must be a number."}, status=400)

        priced = 0
        skipped: list[dict] = []
        errors: list[dict] = []
        touched: list[PtRow] = []
        for row in pt.rows.all():
            if str(row.data.get("MRP") or "").strip():
                continue  # already priced / brand-known MRP — never overwrite
            rate = _price_decimal(row.data.get("P RATE")) or _price_decimal(row.data.get("BASIC"))
            if rate is None or rate <= 0:
                skipped.append({"line_no": row.line_no, "reason": "no purchase rate"})
                continue
            cat = margins.get(str(row.data.get("ITEM") or "").strip(), default_margin)
            margin_pct = override if override is not None else Decimal(cat.margin_pct)
            if not Decimal(cat.band_min_pct) <= margin_pct <= Decimal(cat.band_max_pct):
                errors.append(
                    {
                        "line_no": row.line_no,
                        "detail": f"margin {margin_pct}% is outside the "
                        f"{cat.item or 'default'} band "
                        f"{cat.band_min_pct}–{cat.band_max_pct}%",
                    }
                )
                continue
            result = price_from_rate(rate, margin_pct, slab)
            # MRP was blank (checked above) so it is always written; the tax/margin cells
            # may already carry an AI-read or human-typed value (INPUT/OUTPUT TAX from the
            # real invoice, a hand-entered MARGIN) — pricing fills only the *blank* ones,
            # never clobbering a value the row already asserts.
            priced_cells = {
                "MRP": int(result.mrp),
                "INPUT TAX": _gst_cell(result.input_tax),
                "OUTPUT TAX": _gst_cell(result.output_tax),
                "MARGIN": float(result.margin_pct),
            }
            data = {**row.data}
            prov = {**(row.provenance or {})}
            for col, val in priced_cells.items():
                if col != "MRP" and str(data.get(col) or "").strip():
                    continue  # keep the invoice/human value on this cell
                data[col] = val
                prov[col] = "derived"
            row.data = data
            row.provenance = prov
            touched.append(row)
            priced += 1
        if errors:
            return Response(
                {"detail": "The margin override falls outside a category band.", "errors": errors},
                status=400,
            )
        if touched:
            PtRow.objects.bulk_update(touched, ["data", "provenance"])
            _recompute_counts(pt)
            pt.save()
        data = PtFileDetailSerializer(pt).data
        data["price_result"] = {"priced": priced, "skipped": skipped}
        return Response(data)


class PtFileExportXlsxView(APIView):
    """Download the mapped rows as a real .xlsx in KDPS column order."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: int) -> Any:
        pt = PtFile.objects.filter(pk=pk).prefetch_related("rows").first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "KDPS PT"
        ws.append(KDPS_COLUMNS)
        for row in pt.rows.all():
            ws.append([row.data.get(c, "") for c in KDPS_COLUMNS])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        base = pt.original_filename.rsplit(".", 1)[0]
        resp = HttpResponse(
            buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="KDPS-PT-{base}.xlsx"'
        return resp


class PtFileExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: int) -> Any:
        pt = PtFile.objects.filter(pk=pk).prefetch_related("rows").first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        resp = HttpResponse(content_type="text/csv")
        base = pt.original_filename.rsplit(".", 1)[0]
        resp["Content-Disposition"] = f'attachment; filename="KDPS-PT-{base}.csv"'
        writer = csv.writer(resp)
        writer.writerow(KDPS_COLUMNS)
        for row in pt.rows.all():
            writer.writerow([row.data.get(c, "") for c in KDPS_COLUMNS])
        return resp


class ReviewListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReviewItemSerializer

    def get_queryset(self) -> Any:
        qs = ReviewItem.objects.all()
        st = self.request.query_params.get("status", "open")
        if st != "all":
            qs = qs.filter(status=st)
        dim = self.request.query_params.get("dimension")
        if dim:
            qs = qs.filter(dimension=dim)
        return qs


class ReviewResolveView(APIView):
    """Resolve one queue item → stage + promote a lookup row (via ``learning``, the one
    write-path) or write a taxonomy rule, then re-map every file still needing review.

    A single-dimension resolution routes through ``learning.propose(origin="review") +
    approve`` — the steward's decision *is* the gate, so it is shadow-checked on the way
    in (a conflict with a human-confirmed cell returns 409 and writes nothing). It
    defaults to **brand scope** when the miss came from exactly one resolved brand (D4);
    ``brand`` in the payload overrides (``""`` = explicit global)."""

    permission_classes = [IsAuthenticated]

    def _scope_brand(self, item: ReviewItem, data: dict) -> tuple[str, Response | None]:
        """Brand to scope this resolution to. Explicit ``brand`` wins (validated Master
        brand, or ``""`` for global); else the item's single resolved brand; else global."""
        if "brand" in data:
            brand = str(data.get("brand") or "").strip()
            known = ControlledValue.objects.filter(dimension="brand", value=brand).exists()
            if brand and not known:
                return "", Response(
                    {"detail": f"'{brand}' is not a Master-Sheet brand."}, status=400
                )
            return brand, None
        brands = [b for b in (item.context or {}).get("brands", []) if b]
        return (brands[0] if len(brands) == 1 else ""), None

    def _resolve_single(self, item: ReviewItem, data: dict, actor: Any) -> Response | None:
        target = (data.get("target_value") or "").strip()
        if not target:
            return Response({"detail": "target_value is required."}, status=400)
        valid = set(
            ControlledValue.objects.filter(dimension=item.dimension).values_list("value", flat=True)
        )
        if target not in valid:
            return Response(
                {"detail": f"'{target}' is not an allowed {item.dimension} value."},
                status=400,
            )
        brand, err = self._scope_brand(item, data)
        if err is not None:
            return err
        proposal = learning.propose(
            dimension=item.dimension,
            source_key=norm(item.raw_value),
            target_value=target,
            brand=brand,
            origin=LookupProposal.Origin.REVIEW,
            proposed_by=actor if getattr(actor, "is_authenticated", False) else None,
            evidence={"brands": brand and [brand] or [], "occurrences": item.occurrences},
        )
        proposal = learning.approve(proposal, actor)
        if proposal.status != LookupProposal.Status.APPROVED:
            return Response(
                {
                    "detail": "This resolution conflicts with a human-confirmed cell/correction.",
                    "validation": proposal.validation,
                },
                status=409,
            )
        item.resolved_value = target
        return None

    def _resolve_taxonomy(self, item: ReviewItem, data: dict) -> Response | None:
        pattern = (data.get("pattern") or item.raw_value).strip()
        grid = {
            "gender": (data.get("gender") or "").strip(),
            "sub_category": (data.get("sub_category") or "").strip(),
            "type": (data.get("type") or "").strip(),
            "item": (data.get("item") or "").strip(),
            "fit": (data.get("fit") or "").strip(),
        }
        if not any(grid.values()):
            return Response({"detail": "Provide at least one taxonomy field."}, status=400)
        for dim_key in ("gender", "sub_category", "type", "item", "fit"):
            val = grid[dim_key]
            if val and not ControlledValue.objects.filter(dimension=dim_key, value=val).exists():
                return Response(
                    {"detail": f"'{val}' is not an allowed {dim_key} value."}, status=400
                )
        TaxonomyRule.objects.update_or_create(
            pattern=pattern,
            defaults={**grid, "priority": len(pattern)},
        )
        item.resolved_value = grid.get("item") or pattern
        return None

    @transaction.atomic
    def post(self, request: Request, pk: int) -> Response:
        if not user_may_act(request.user, MAPPING_STEWARDSHIP_ACTION):
            return _forbidden("Only Warehouse or the HO Data Steward can resolve review items.")
        item = ReviewItem.objects.filter(pk=pk).first()
        if not item:
            return Response({"detail": "Not found."}, status=404)
        data = request.data

        if data.get("action") == "ignore":
            item.status = ReviewItem.Status.IGNORED
            item.save(update_fields=["status", "updated_at"])
            return Response(ReviewItemSerializer(item).data)

        if item.dimension in SINGLE_DIMS:
            # learning.approve() repropagates on success — don't double-map below.
            err = self._resolve_single(item, data, request.user)
        elif item.dimension == "taxonomy":
            err = self._resolve_taxonomy(item, data)
        else:
            return Response({"detail": f"Unknown dimension {item.dimension}."}, status=400)
        if err is not None:
            return err

        item.status = ReviewItem.Status.RESOLVED
        item.save(update_fields=["status", "resolved_value", "updated_at"])
        if item.dimension == "taxonomy":
            learning.repropagate()  # the single-dim path already repropagated via approve()
        return Response(ReviewItemSerializer(item).data)


class LookupProposalListView(generics.ListAPIView):
    """The staged-learning queue. ``?status=`` (default ``proposed``) filters by status;
    ``all`` returns every proposal, newest first."""

    permission_classes = [IsAuthenticated]
    serializer_class = LookupProposalSerializer

    def get_queryset(self) -> Any:
        qs = LookupProposal.objects.all()
        st = self.request.query_params.get("status", "proposed")
        if st != "all":
            qs = qs.filter(status=st)
        return qs


class LookupProposalDecideView(APIView):
    """Approve (promote to a live ``Lookup`` via the one write-path) or reject a staged
    proposal — a mapping-steward action (Rule 8: only a human decision reaches a live
    rule). Approve runs the shadow check; a conflict returns 409 with the detail."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request: Request, pk: int) -> Response:
        if not user_may_act(request.user, MAPPING_STEWARDSHIP_ACTION):
            return _forbidden("Only mapping stewards can decide learning proposals.")
        proposal = LookupProposal.objects.filter(pk=pk).first()
        if not proposal:
            return Response({"detail": "Not found."}, status=404)
        action = request.data.get("action")
        if action == "approve":
            proposal = learning.approve(proposal, request.user)
            if proposal.status != LookupProposal.Status.APPROVED:
                return Response(
                    {
                        "detail": "The shadow check blocked this promotion.",
                        "validation": proposal.validation,
                        "proposal": LookupProposalSerializer(proposal).data,
                    },
                    status=409,
                )
        elif action == "reject":
            proposal = learning.reject(proposal, request.user)
        else:
            return Response({"detail": "action must be 'approve' or 'reject'."}, status=400)
        return Response(LookupProposalSerializer(proposal).data)


class SuggestView(APIView):
    """Deterministic pre-fill suggestions for a raw value (no LLM). Exact ``Lookup``
    hits (brand-scoped first, then global) rank above Master values by trigram
    similarity (``>= 0.25``, top 5). Pure read — it only pre-fills a dropdown; a human
    still picks and only the review/edit write-path commits anything (Rule 8).

    ``GET /ptmapper/suggest?dimension=<dim>&q=<raw>&brand=<brand>``"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        from django.contrib.postgres.search import TrigramSimilarity

        dimension = request.query_params.get("dimension", "")
        q = (request.query_params.get("q") or "").strip()
        brand = (request.query_params.get("brand") or "").strip()
        if not dimension or not q:
            return Response({"dimension": dimension, "q": q, "suggestions": []})

        key = norm(q)
        suggestions: list[dict[str, Any]] = []
        seen: set[str] = set()
        # 1) exact lookup hits, brand-scoped before global (highest confidence)
        for scope in [brand, ""] if brand else [""]:
            hit = Lookup.objects.filter(dimension=dimension, source_key=key, brand=scope).first()
            if hit and hit.target_value not in seen:
                suggestions.append({"value": hit.target_value, "reason": "lookup", "score": 1.0})
                seen.add(hit.target_value)
        # 2) fuzzy Master values by trigram similarity (Master vocabulary only)
        fuzzy = (
            ControlledValue.objects.filter(dimension=dimension)
            .annotate(sim=TrigramSimilarity("value", q))
            .filter(sim__gte=0.25)
            .order_by("-sim")[:5]
        )
        for cv in fuzzy:
            if cv.value not in seen:
                suggestions.append(
                    {"value": cv.value, "reason": "similar", "score": round(cv.sim, 3)}
                )
                seen.add(cv.value)
        return Response({"dimension": dimension, "q": q, "suggestions": suggestions[:5]})


class ControlledValuesView(APIView):
    """The Master-Sheet vocabulary. ``?dimension=<dim>`` → one dimension's values
    (the original form); no param → every dimension + the ITEM → (SUB CATEGORY,
    TYPE) helper map, so the editor loads its dropdowns in one request."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        dim = request.query_params.get("dimension")
        if dim:
            values = list(
                ControlledValue.objects.filter(dimension=dim)
                .order_by("value")
                .values_list("value", flat=True)
            )
            return Response({"dimension": dim, "values": values})
        dimensions: dict[str, list[str]] = {}
        for cv in ControlledValue.objects.order_by("dimension", "value"):
            dimensions.setdefault(cv.dimension, []).append(cv.value)
        item_taxonomy = {
            t.item: {"sub_category": t.sub_category, "type": t.type}
            for t in ItemTaxonomy.objects.all()
        }
        return Response({"dimensions": dimensions, "item_taxonomy": item_taxonomy})
