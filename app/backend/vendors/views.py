"""Vendor master + Booking API.

Booking capture is a two-step, human-in-the-loop flow:
  POST /api/bookings/draft   → Gemini reads the uploaded receiving doc, returns a
                               DRAFT (nothing saved). The handler edits it.
  POST /api/bookings/        → saves the confirmed booking + lines (status Booked).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from files.models import StoredFile
from masters.models import Brand, Season
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
        stored = StoredFile.from_upload(
            upload, StoredFile.Kind.BOOKING_RECEIPT, request.user
        )
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


class BookingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BookingSerializer

    def get_queryset(self) -> Any:
        qs = Booking.objects.select_related(
            "vendor", "brand", "season", "destination_store"
        ).prefetch_related("lines")
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("brand"):
            qs = qs.filter(brand_id=params["brand"])
        if params.get("season"):
            qs = qs.filter(season_id=params["season"])
        return qs

    @transaction.atomic
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        ser = BookingCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        brand: Brand = data["brand"]
        season: Season = data["season"]
        vendor: Vendor = data["vendor"]

        seq = Booking.objects.filter(season=season).count() + 1
        number = f"BK-{season.code}-{seq:04d}"

        dest_id = data.get("destination_store")
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
        for raw in data["lines"]:
            qty = int(raw.get("booked_qty") or raw.get("quantity") or 0)
            mrp = raw.get("mrp_paise")
            if mrp is None:
                mrp = _rupees_to_paise(raw.get("mrp"))
            BookingLine.objects.create(
                booking=booking,
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
    ).prefetch_related("lines")
