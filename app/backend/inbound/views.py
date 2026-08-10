"""Receiving API — pending bookings, the invoice-reader agent, and GRN create.

Everything store-scoped is filtered fail-closed (ADR-0003): a store user only
ever sees / writes their own store's receipts.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import require_section
from accounts.sections import CAP_VIEW
from core.documents import DocStatus, VoucherSeries
from core.textsearch import search_term, text_filter
from files.models import StoredFile, UploadTooLarge
from inbound.agents import read_invoice
from inbound.models import Grn, GrnLine
from inbound.serializers import GrnSerializer
from masters.models import Store
from masters.scoping import (
    actionable_store_ids,
    scope_by_store,
    scope_by_store_many,
)
from vendors.models import Booking, BookingLine
from vendors.scoping import scope_bookings
from vendors.serializers import BookingSerializer


def _financial_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class PendingBookingsView(APIView):
    """Bookings still awaiting receipt, scoped to what the user may receive."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        qs = Booking.objects.select_related(
            "vendor", "brand", "season", "destination_store"
        ).filter(status__in=[Booking.Status.BOOKED, Booking.Status.PARTIALLY_RECEIVED])
        # A read, so it follows the unit the person is *acting in* (#88), not
        # their whole entitlement — switch to Deoghar and you see Deoghar's queue.
        # `scope_bookings` is `vendors.scoping`'s (#234): the same any-line-in-
        # scope rule the list, detail and search endpoints answer with, hand-
        # rolled here before it had a shared home.
        qs = scope_bookings(qs, request.user)
        return Response(
            BookingSerializer(qs.prefetch_related("lines", "lines__store"), many=True).data
        )


class InvoiceDraftView(APIView):
    """Read an uploaded invoice into prefilled receive lines (nothing saved)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "A file is required."}, status=400)
        try:
            stored = StoredFile.from_upload(upload, StoredFile.Kind.INVOICE, request.user)
        except UploadTooLarge as exc:
            return Response({"detail": str(exc)}, status=413)
        try:
            result = read_invoice(bytes(stored.content), stored.content_type)
        except Exception as exc:  # noqa: BLE001
            return Response(
                {
                    "detail": f"Could not read the invoice. Upload a clearer copy. ({exc})",
                    "invoice_file_id": stored.id,
                },
                status=422,
            )
        result["invoice_file_id"] = stored.id
        return Response(result)


def _resolve_receiving_store(data: dict[str, Any], user: Any) -> tuple[Any, Response | None]:
    """Validate the target store + fail-closed scope check. Returns (store, error)."""
    store_id = data.get("store_id") or data.get("store")
    if not store_id:
        return None, Response({"detail": "store_id is required."}, status=400)
    ids = actionable_store_ids(user)
    if ids is not None and int(store_id) not in ids:
        return None, Response({"detail": "You may not receive at this store."}, status=403)
    return Store.objects.get(pk=store_id), None


def _ensure_grn_series(store: Store) -> None:
    """Make sure the gap-free GRN voucher series exists for (FY, store) before post()."""
    VoucherSeries.objects.get_or_create(
        fy=_financial_year(date.today()), store_code=store.code, doc_type="GRN"
    )


def _resolve_kind(data: dict[str, Any], store: Store) -> tuple[Any, Response | None]:
    """Validate the branded/non-branded discriminator + its fail-closed location rule:
    non-branded goods are received only at a warehouse (any warehouse — no hardcode)."""
    kind = data.get("kind", Grn.Kind.BRANDED)
    if kind not in Grn.Kind.values:
        return None, Response({"detail": f"Invalid kind '{kind}'."}, status=400)
    if kind == Grn.Kind.NON_BRANDED and store.store_type != Store.StoreType.WAREHOUSE:
        return None, Response(
            {"detail": "Non-branded goods are received only at a warehouse."}, status=400
        )
    return kind, None


def _build_grn(data: dict[str, Any], store: Any, booking: Any, kind: str, user: Any) -> Grn:
    """Create the GRN as a DRAFT (no number yet); `post()` mints it after lines land."""
    received_at = (
        Grn.ReceivedAt.WAREHOUSE
        if store.store_type == Store.StoreType.WAREHOUSE
        else Grn.ReceivedAt.STORE
    )
    return Grn.objects.create(
        booking=booking,
        vendor=booking.vendor if booking else None,
        vendor_name_raw=data.get("vendor_name", "") if not booking else "",
        store=store,
        received_at=received_at,
        kind=kind,
        is_direct=booking is None,
        invoice_number=data.get("invoice_number", ""),
        invoice_file_id=data.get("invoice_file_id"),
        notes=data.get("notes", ""),
        received_by=user,
    )


def _grn_quantities(raw: dict[str, Any]) -> tuple[int, int]:
    return _safe_int(raw.get("received_qty") or raw.get("quantity")), _safe_int(
        raw.get("damaged_qty")
    )


def _booking_line_from_payload(raw: dict[str, Any], booking: Any) -> BookingLine | None:
    """Resolve the referenced booking line — only ever within *this* GRN's booking,
    so a payload can never link/mutate another booking's line."""
    bl_id = raw.get("booking_line_id") or raw.get("booking_line")
    if not (bl_id and booking):
        return None
    return BookingLine.objects.filter(pk=bl_id, booking=booking).first()


def _line_is_variance(raw: dict[str, Any], booking_line: BookingLine | None, booking: Any) -> bool:
    return bool(raw.get("is_variance")) or (booking_line is None and booking is not None)


def _add_grn_line(grn: Grn, raw: dict[str, Any], booking: Any) -> None:
    qty, damaged_qty = _grn_quantities(raw)
    if qty <= 0 and damaged_qty <= 0:
        return  # empty row (no received & no damaged units) — intentionally skipped
    bl = _booking_line_from_payload(raw, booking)
    GrnLine.objects.create(
        grn=grn,
        booking_line=bl,
        style_code=str(raw.get("style_code", "")).strip(),
        size=str(raw.get("size") or "").strip(),
        color=str(raw.get("color") or "").strip(),
        barcode=str(raw.get("barcode") or "").strip(),
        received_qty=qty,
        damaged_qty=damaged_qty,
        is_variance=_line_is_variance(raw, bl, booking),
        remark=str(raw.get("remark") or "").strip(),
    )
    if bl:
        bl.received_qty += qty
        bl.save(update_fields=["received_qty", "updated_at"])


def _resolve_booking(data: dict[str, Any], user: Any) -> tuple[Any, Response | None]:
    """Fetch the optional booking and fail-closed scope-check it (ADR-0003): a
    store-scoped user may only receive against a booking bound to one of their stores."""
    booking_id = data.get("booking_id") or data.get("booking")
    if not booking_id:
        return None, None
    booking = Booking.objects.filter(pk=booking_id).first()
    if booking is None:
        return None, Response({"detail": "Booking not found."}, status=400)
    # A booking that has been short-closed or cancelled is a decision somebody
    # took with a reason on the record. Receiving against it would quietly
    # reverse that decision — the pending list already hides it, and a stale
    # tab or a direct call must get the same answer.
    if not booking.is_open:
        return None, Response(
            {
                "detail": (
                    f"Booking {booking.number} is {booking.get_status_display().lower()}"
                    f"{f' — {booking.close_reason}' if booking.close_reason else ''}. "
                    "Receive it as a direct arrival, or have the booking reopened."
                )
            },
            status=409,
        )
    ids = actionable_store_ids(user)
    if ids is not None and not _booking_touches_stores(booking, ids):
        return None, Response({"detail": "You may not receive against this booking."}, status=403)
    return booking, None


def _booking_touches_stores(booking: Any, ids: list[int]) -> bool:
    """True if any line's effective destination (own store, else the booking default)
    is one of `ids`. A store-scoped user may receive against such a booking (ADR-0003)."""
    id_set = set(ids)
    lines = list(booking.lines.all())
    effective = (
        {(line.store_id or booking.destination_store_id) for line in lines}
        if lines
        else {booking.destination_store_id}
    )
    return bool(effective & id_set)


#: Receive/GRN (#106) — GRN number, who it was received from, whose goods they
#: are. `booking__brand__name`, not `vendor__brands__name` — the latter is a
#: to-many relation and `text_filter` must not span one.
GRN_SEARCH_FIELDS = ("doc_number", "vendor__name", "booking__brand__name")


class GrnListCreateView(generics.ListCreateAPIView[Grn]):
    permission_classes = [IsAuthenticated]
    serializer_class = GrnSerializer

    def get_queryset(self) -> Any:
        qs = Grn.objects.select_related(
            "store", "booking", "booking__brand", "vendor"
        ).prefetch_related("lines", "pt_files")
        qs = scope_by_store(qs, self.request.user, "store_id")
        kind = self.request.query_params.get("kind")
        if kind in Grn.Kind.values:  # honour ?kind=branded|non_branded (else unfiltered)
            qs = qs.filter(kind=kind)
        # The screen's own search box (#102), applied last so it can only
        # narrow what the scope + filters above already allow.
        return text_filter(qs, search_term(self.request), GRN_SEARCH_FIELDS)

    @transaction.atomic
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.data
        store, err = _resolve_receiving_store(data, request.user)
        if err is not None:
            return err

        booking, err = _resolve_booking(data, request.user)
        if err is not None:
            return err

        kind, err = _resolve_kind(data, store)
        if err is not None:
            return err

        grn = _build_grn(data, store, booking, kind, request.user)
        for raw in data.get("lines", []):
            _add_grn_line(grn, raw, booking)
        _ensure_grn_series(store)
        grn.post()  # mint the gap-free GRN number + freeze (SUBMITTED)
        if booking:
            booking.recompute_status()
        return Response(GrnSerializer(grn).data, status=status.HTTP_201_CREATED)


class GrnDetailView(generics.RetrieveAPIView[Grn]):
    permission_classes = [IsAuthenticated]
    serializer_class = GrnSerializer

    def get_queryset(self) -> Any:
        qs = Grn.objects.select_related("store", "booking", "vendor").prefetch_related(
            "lines", "pt_files"
        )
        return scope_by_store(qs, self.request.user, "store_id")


class InboundQueueView(APIView):
    """The inbound work queue (Q9: in-app is the system of record; WhatsApp nudge is
    a later phase). Derived, never stored: an arrival is *awaiting* while it has no
    live PT (a reversed PT re-opens it); a PT in the warehouse/Patna pipeline shows
    as in-progress. GET only.

    Gated on ``receive_goods: view`` rather than a role list (#94), so the queue
    opens for exactly the people the sidebar already shows Receive Goods to — the
    store person included, whose own arrivals are their work. Both halves are then
    narrowed to the unit in the top-bar switcher, the same gate ``GrnListView``
    uses, so a store sees its own queue and nobody else's.
    """

    permission_classes = [IsAuthenticated, require_section("receive_goods", CAP_VIEW)]

    def get(self, request: Request) -> Response:
        from ptmapper.models import PtFile

        awaiting, in_progress = scope_by_store_many(
            request.user,
            # Only non-branded arrivals await an authored PT here; branded arrivals
            # wait for the brand's PT via the Mapper instead (D2 split).
            (
                Grn.objects.filter(docstatus=DocStatus.SUBMITTED, kind=Grn.Kind.NON_BRANDED)
                .exclude(pt_files__docstatus__in=[DocStatus.DRAFT, DocStatus.SUBMITTED])
                .select_related("store", "booking", "vendor")
                .prefetch_related("lines", "pt_files")
                .order_by("created_at"),  # oldest arrival first — it has waited longest
                "store_id",
            ),
            # A PT has no store of its own — it belongs to the arrival it was made
            # from, so it is scoped through the GRN's.
            (
                PtFile.objects.filter(grn__isnull=False, docstatus=DocStatus.DRAFT)
                .select_related("grn")
                .order_by("created_at"),
                "grn__store_id",
            ),
        )
        progress_rows = [
            {
                "id": p.id,
                "original_filename": p.original_filename,
                "source": p.source,
                "stage": p.stage,
                "stage_label": p.stage_label,
                "grn_id": p.grn_id,
                "grn_number": p.grn.doc_number if p.grn else None,
                "row_count": p.row_count,
                "blank_cell_count": p.blank_cell_count,
                "created_at": p.created_at,
            }
            for p in in_progress
        ]
        awaiting_rows = GrnSerializer(awaiting, many=True).data
        return Response(
            {
                "awaiting_pt": awaiting_rows,
                "pt_in_progress": progress_rows,
                "counts": {
                    "awaiting_pt": len(awaiting_rows),
                    "pt_in_progress": len(progress_rows),
                },
            }
        )
