"""Vendor master + Booking API.

Booking capture is a two-step, human-in-the-loop flow:
  POST /api/bookings/draft   → Gemini reads the uploaded receiving doc, returns a
                               DRAFT (nothing saved). The handler edits it.
  POST /api/bookings/        → saves the confirmed booking + lines (status Booked).
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
from core.textsearch import search_term, text_filter
from files.models import StoredFile
from masters.models import Brand, Season, Store
from vendors.agents import read_booking_receipt
from vendors.models import Booking, BookingLine, Vendor
from vendors.serializers import (
    BookingCreateSerializer,
    BookingSerializer,
    VendorSerializer,
)


def _rupees_to_paise(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _financial_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _allocate_booking_number(season: Season) -> str:
    """Gap-free, collision-free booking number per (FY, season) — replaces the racy
    `count()+1` (which double-allocates under concurrent booking creation)."""
    fy = _financial_year(date.today())
    scope = season.code[:16]
    VoucherSeries.objects.get_or_create(fy=fy, store_code=scope, doc_type="BK")
    _, number = VoucherSeries.allocate(fy=fy, store_code=scope, doc_type="BK")
    return number


class VendorListCreateView(generics.ListCreateAPIView):
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated]
    queryset = Vendor.objects.prefetch_related("brands").filter(is_active=True)


class BookingDraftView(APIView):
    """Read an uploaded receiving doc into a draft booking (not saved)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "A file is required."}, status=400)
        stored = StoredFile.from_upload(upload, StoredFile.Kind.BOOKING_RECEIPT, request.user)
        try:
            result = read_booking_receipt(bytes(stored.content), stored.content_type)
        except Exception as exc:  # noqa: BLE001 - surface a clean message to the UI
            return Response(
                {
                    "detail": "Could not read the document. Please upload a clearer "
                    f"photo or the Excel/PDF. ({exc})",
                    "source_file_id": stored.id,
                },
                status=422,
            )
        # normalise lines for the UI
        for line in result.get("lines", []):
            line["mrp_paise"] = _rupees_to_paise(line.get("mrp"))
        result["source_file_id"] = stored.id
        return Response(result)


#: What a typed term looks through on the Bookings screen — the four things a
#: person half-remembers about an order: its number, who it was placed with,
#: whose goods they are, and which season it belongs to.
BOOKING_SEARCH_FIELDS = (
    "number",
    "vendor__name",
    "brand__name",
    "season__code",
    "season__name",
)


class BookingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BookingSerializer

    def get_queryset(self) -> Any:
        qs = Booking.objects.select_related(
            "vendor", "brand", "season", "destination_store"
        ).prefetch_related("lines", "lines__store")
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("brand"):
            qs = qs.filter(brand_id=params["brand"])
        if params.get("season"):
            qs = qs.filter(season_id=params["season"])
        # The screen's own search box (#102), applied last so it can only narrow
        # what the filters above already allow.
        return text_filter(qs, search_term(self.request), BOOKING_SEARCH_FIELDS)

    @transaction.atomic
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        ser = BookingCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        brand: Brand = data["brand"]
        season: Season = data["season"]
        vendor: Vendor = data["vendor"]

        dest_id = data.get("destination_store")
        number = _allocate_booking_number(season)
        booking = Booking.objects.create(
            number=number,
            vendor=vendor,
            brand=brand,
            season=season,
            destination_store_id=dest_id,
            status=Booking.Status.BOOKED,
            vendor_ref=data.get("vendor_ref", ""),
            notes=data.get("notes", ""),
            ownership=brand.ownership,
            return_terms=brand.return_terms,
            source_file_id=data.get("source_file_id"),
            created_by=request.user,
        )
        est = 0
        # A booking can span several stores: each line may name its own destination
        # store; a line with none inherits the booking's default (destination_store).
        # Validate requested per-line stores once (fail-safe: unknown id → default).
        requested = {_safe_int(r.get("store")) for r in data["lines"] if _safe_int(r.get("store"))}
        valid_store_ids = (
            set(Store.objects.filter(pk__in=requested).values_list("id", flat=True))
            if requested
            else set()
        )
        for raw in data["lines"]:
            qty = int(raw.get("booked_qty") or raw.get("quantity") or 0)
            mrp = raw.get("mrp_paise")
            if mrp is None:
                mrp = _rupees_to_paise(raw.get("mrp"))
            line_store = _safe_int(raw.get("store"))
            line_store_id = line_store if line_store in valid_store_ids else None
            BookingLine.objects.create(
                booking=booking,
                store_id=line_store_id,
                style_code=str(raw.get("style_code", "")).strip(),
                size=str(raw.get("size") or "").strip(),
                description=str(raw.get("description") or "").strip(),
                booked_qty=qty,
                mrp_paise=mrp,
            )
            if mrp:
                est += mrp * qty
        if est:
            booking.estimated_value_paise = est
            booking.save(update_fields=["estimated_value_paise", "updated_at"])
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)


class BookingDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BookingSerializer
    queryset = Booking.objects.select_related(
        "vendor", "brand", "season", "destination_store"
    ).prefetch_related("lines", "lines__store")
