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

from core.documents import VoucherSeries
from files.models import StoredFile, UploadTooLarge
from inbound.agents import read_invoice
from inbound.models import Grn, GrnLine
from inbound.serializers import GrnSerializer
from masters.models import Store
from masters.scoping import scope_by_store, visible_store_ids
from vendors.models import Booking, BookingLine
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
        ids = visible_store_ids(request.user)
        if ids is not None:  # store-scoped user → only their store's deliveries
            qs = qs.filter(destination_store_id__in=ids)
        return Response(BookingSerializer(qs.prefetch_related("lines"), many=True).data)


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


def _resolve_receiving_store(data: dict, user: Any) -> tuple[Any, Response | None]:
    """Validate the target store + fail-closed scope check. Returns (store, error)."""
    store_id = data.get("store_id") or data.get("store")
    if not store_id:
        return None, Response({"detail": "store_id is required."}, status=400)
    ids = visible_store_ids(user)
    if ids is not None and int(store_id) not in ids:
        return None, Response({"detail": "You may not receive at this store."}, status=403)
    return Store.objects.get(pk=store_id), None


def _ensure_grn_series(store: Store) -> None:
    """Make sure the gap-free GRN voucher series exists for (FY, store) before post()."""
    VoucherSeries.objects.get_or_create(
        fy=_financial_year(date.today()), store_code=store.code, doc_type="GRN"
    )


def _build_grn(data: dict, store: Any, booking: Any, user: Any) -> Grn:
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
        is_direct=booking is None,
        invoice_number=data.get("invoice_number", ""),
        invoice_file_id=data.get("invoice_file_id"),
        notes=data.get("notes", ""),
        received_by=user,
    )


def _grn_quantities(raw: dict) -> tuple[int, int]:
    return _safe_int(raw.get("received_qty") or raw.get("quantity")), _safe_int(
        raw.get("damaged_qty")
    )


def _booking_line_from_payload(raw: dict, booking: Any) -> BookingLine | None:
    """Resolve the referenced booking line — only ever within *this* GRN's booking,
    so a payload can never link/mutate another booking's line."""
    bl_id = raw.get("booking_line_id") or raw.get("booking_line")
    if not (bl_id and booking):
        return None
    return BookingLine.objects.filter(pk=bl_id, booking=booking).first()


def _line_is_variance(raw: dict, booking_line: BookingLine | None, booking: Any) -> bool:
    return bool(raw.get("is_variance")) or (booking_line is None and booking is not None)


def _add_grn_line(grn: Grn, raw: dict, booking: Any) -> None:
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


def _resolve_booking(data: dict, user: Any) -> tuple[Any, Response | None]:
    """Fetch the optional booking and fail-closed scope-check it (ADR-0003): a
    store-scoped user may only receive against a booking bound to one of their stores."""
    booking_id = data.get("booking_id") or data.get("booking")
    if not booking_id:
        return None, None
    booking = Booking.objects.filter(pk=booking_id).first()
    if booking is None:
        return None, Response({"detail": "Booking not found."}, status=400)
    ids = visible_store_ids(user)
    if ids is not None and booking.destination_store_id not in ids:
        return None, Response({"detail": "You may not receive against this booking."}, status=403)
    return booking, None


class GrnListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = GrnSerializer

    def get_queryset(self) -> Any:
        qs = Grn.objects.select_related("store", "booking", "vendor").prefetch_related("lines")
        return scope_by_store(qs, self.request.user, "store_id")

    @transaction.atomic
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.data
        store, err = _resolve_receiving_store(data, request.user)
        if err is not None:
            return err

        booking, err = _resolve_booking(data, request.user)
        if err is not None:
            return err

        grn = _build_grn(data, store, booking, request.user)
        for raw in data.get("lines", []):
            _add_grn_line(grn, raw, booking)
        _ensure_grn_series(store)
        grn.post()  # mint the gap-free GRN number + freeze (SUBMITTED)
        if booking:
            booking.recompute_status()
        return Response(GrnSerializer(grn).data, status=status.HTTP_201_CREATED)


class GrnDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = GrnSerializer

    def get_queryset(self) -> Any:
        qs = Grn.objects.select_related("store", "booking", "vendor").prefetch_related("lines")
        return scope_by_store(qs, self.request.user, "store_id")
