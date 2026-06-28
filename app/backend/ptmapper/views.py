"""PT Mapper API — upload a brand file, map it deterministically, review the
unmapped queue, resolve a value (which grows the lookup tables), and export KDPS
rows. No AI anywhere in this module.
"""

from __future__ import annotations

import csv
import io
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

from files.models import StoredFile
from ptmapper.engine import UnsupportedFormat, norm, run_mapping
from ptmapper.models import (
    ControlledValue,
    Lookup,
    PtFile,
    PtRow,
    ReviewItem,
    TaxonomyRule,
)
from ptmapper.profiles import CONTROLLED as CONTROLLED_COLS
from ptmapper.profiles import KDPS_COLUMNS
from ptmapper.serializers import (
    PtFileDetailSerializer,
    PtFileListSerializer,
    ReviewItemSerializer,
)
from stockledger.posting import post_pt_inward, reverse_pt_inward
from vendors.models import Booking

SINGLE_DIMS = {"color", "size", "brand", "season"}
KDPS_COLUMN_SET = set(KDPS_COLUMNS)


def _sync_review_items(reviews: list[dict]) -> int:
    """Upsert each engine miss into the review queue; return the open count."""
    open_count = 0
    for m in reviews:
        obj, created = ReviewItem.objects.get_or_create(
            dimension=m["dimension"], raw_value=m["raw"][:300],
            defaults={"occurrences": m["occurrences"], "context": {"samples": m["samples"]}},
        )
        if not created and obj.status == ReviewItem.Status.OPEN:
            obj.occurrences = m["occurrences"]
            obj.context = {"samples": m["samples"]}
            obj.save(update_fields=["occurrences", "context", "updated_at"])
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


def process_file(pt: PtFile) -> PtFile:
    """Run the engine over the stored bytes and (re)build rows + review items."""
    pt.rows.all().delete()
    if not pt.stored_file:
        return _fail_file(pt, "The uploaded file is no longer available.")
    content = bytes(pt.stored_file.content)
    try:
        result = run_mapping(content, pt.original_filename, pt.stored_file.content_type)
    except UnsupportedFormat as exc:
        return _fail_file(pt, str(exc), reset_counts=True)
    except Exception as exc:  # noqa: BLE001
        return _fail_file(pt, f"Could not read this file: {exc}")

    PtRow.objects.bulk_create([
        PtRow(pt_file=pt, line_no=r["line_no"], data=r["data"], blanks=r["blanks"])
        for r in result["rows"]
    ])
    open_count = _sync_review_items(result["reviews"])

    pt.profile_code = result["profile_code"]
    pt.profile_name = result["profile_name"]
    pt.archetype = result["archetype"]
    pt.brand_guess = result["brand_guess"]
    pt.meta = result["meta"]
    pt.row_count = len(result["rows"])
    pt.blank_cell_count = result["blank_cells"]
    pt.unresolved_count = open_count
    pt.status = (
        PtFile.Status.READY
        if (pt.row_count > 0 and open_count == 0)
        else PtFile.Status.NEEDS_REVIEW
    )
    pt.error = ""
    pt.save()
    return pt


class PtFileListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> Any:
        return PtFile.objects.all()

    def get_serializer_class(self):
        return PtFileListSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "A file is required."}, status=400)
        stored = StoredFile.from_upload(upload, StoredFile.Kind.PT_FILE, request.user)
        pt = PtFile.objects.create(
            stored_file=stored,
            original_filename=stored.filename,
            created_by=request.user if getattr(request.user, "is_authenticated", False) else None,
        )
        process_file(pt)
        return Response(PtFileDetailSerializer(pt).data, status=status.HTTP_201_CREATED)


class PtFileDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PtFileDetailSerializer
    queryset = PtFile.objects.prefetch_related("rows")


class PtFileRerunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage != PtFile.Stage.MAPPING:
            return Response(
                {"detail": "Only files still in mapping can be re-run."}, status=409
            )
        pt.manually_edited = False
        process_file(pt)
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


class PtRowsUpdateView(APIView):
    """Warehouse hand-edits the mapped KDPS rows before sending to Patna."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request: Request, pk: int) -> Response:
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage == PtFile.Stage.POSTED:
            return Response({"detail": "Posted files are locked."}, status=409)
        edits = {int(e["id"]): e.get("data", {}) for e in request.data.get("rows", []) if "id" in e}
        rows = list(pt.rows.filter(id__in=edits.keys()))
        for r in rows:
            new_data = {**r.data}
            for col, val in edits[r.id].items():
                if col in KDPS_COLUMN_SET:
                    new_data[col] = val
            r.data = new_data
        PtRow.objects.bulk_update(rows, ["data"])
        pt.manually_edited = True
        _recompute_counts(pt)
        pt.save()
        return Response(PtFileDetailSerializer(pt).data)


class PtFileSendView(APIView):
    """Warehouse → Patna: hand the mapped draft over for review/posting."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage != PtFile.Stage.MAPPING:
            return Response({"detail": "This file is not in the mapping stage."}, status=409)
        if pt.row_count == 0:
            return Response({"detail": "Nothing to send — the file has no rows."}, status=409)
        pt.stage = PtFile.Stage.SENT
        pt.sent_at = timezone.now()
        pt.save(update_fields=["stage", "sent_at", "updated_at"])
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
        pt.stage = PtFile.Stage.MAPPING
        pt.sent_at = None
        pt.save(update_fields=["stage", "sent_at", "updated_at"])
        return Response(PtFileDetailSerializer(pt).data)


class PtFilePostView(APIView):
    """Patna pushes the reviewed file into the KDPS system: writes the append-only
    stock-ledger inward + (optionally) reconciles a booking, then locks the file."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
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
        result = post_pt_inward(pt, request.user, booking=booking)
        data = PtFileDetailSerializer(pt).data
        data["post_result"] = result
        return Response(data)


class PtFileReverseView(APIView):
    """Append-only correction: reverse a posted PT inward (negative mirror rows),
    returning the file to 'sent' so it can be fixed and re-posted."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        pt = PtFile.objects.filter(pk=pk).first()
        if not pt:
            return Response({"detail": "Not found."}, status=404)
        if pt.stage != PtFile.Stage.POSTED or not pt.inward_doc_number:
            return Response({"detail": "Only a posted file can be reversed."}, status=409)
        result = reverse_pt_inward(pt, request.user)
        data = PtFileDetailSerializer(pt).data
        data["reverse_result"] = result
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
    """Resolve one queue item → write a lookup row / taxonomy rule, then re-map
    every file still needing review (the resolution is remembered forever)."""

    permission_classes = [IsAuthenticated]

    def _resolve_single(self, item: ReviewItem, data: dict) -> Response | None:
        target = (data.get("target_value") or "").strip()
        if not target:
            return Response({"detail": "target_value is required."}, status=400)
        valid = set(
            ControlledValue.objects.filter(dimension=item.dimension)
            .values_list("value", flat=True)
        )
        if target not in valid:
            return Response(
                {"detail": f"'{target}' is not an allowed {item.dimension} value."},
                status=400,
            )
        Lookup.objects.update_or_create(
            dimension=item.dimension, source_key=norm(item.raw_value),
            defaults={"target_value": target},
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
            pattern=pattern, defaults={**grid, "priority": len(pattern)},
        )
        item.resolved_value = grid.get("item") or pattern
        return None

    def _repropagate(self) -> None:
        """Re-map every file still in mapping & not hand-edited so the fix
        propagates everywhere without clobbering manual edits / sent files."""
        for pt in PtFile.objects.filter(
            status=PtFile.Status.NEEDS_REVIEW,
            stage=PtFile.Stage.MAPPING,
            manually_edited=False,
        ):
            process_file(pt)

    @transaction.atomic
    def post(self, request: Request, pk: int) -> Response:
        item = ReviewItem.objects.filter(pk=pk).first()
        if not item:
            return Response({"detail": "Not found."}, status=404)
        data = request.data

        if data.get("action") == "ignore":
            item.status = ReviewItem.Status.IGNORED
            item.save(update_fields=["status", "updated_at"])
            return Response(ReviewItemSerializer(item).data)

        if item.dimension in SINGLE_DIMS:
            err = self._resolve_single(item, data)
        elif item.dimension == "taxonomy":
            err = self._resolve_taxonomy(item, data)
        else:
            return Response({"detail": f"Unknown dimension {item.dimension}."}, status=400)
        if err is not None:
            return err

        item.status = ReviewItem.Status.RESOLVED
        item.save(update_fields=["status", "resolved_value", "updated_at"])
        self._repropagate()
        return Response(ReviewItemSerializer(item).data)


class ControlledValuesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        dim = request.query_params.get("dimension")
        if not dim:
            return Response({"detail": "dimension is required."}, status=400)
        values = list(
            ControlledValue.objects.filter(dimension=dim)
            .order_by("value").values_list("value", flat=True)
        )
        return Response({"dimension": dim, "values": values})
