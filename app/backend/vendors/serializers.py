from __future__ import annotations

from typing import Any

from rest_framework import serializers

from masters.models import Brand, Season
from vendors.models import Booking, BookingLine, Vendor


class VendorSerializer(serializers.ModelSerializer[Vendor]):
    brand_names = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            "id",
            "code",
            "name",
            "city",
            "gstin",
            "state_code",
            "state_name",
            "pan",
            "payment_terms",
            "brands",
            "brand_names",
            "is_active",
        ]

    def get_brand_names(self, obj: Vendor) -> list[str]:
        return [b.name for b in obj.brands.all()]


class BookingLineSerializer(serializers.ModelSerializer[BookingLine]):
    store_name = serializers.CharField(source="store.name", read_only=True, default=None)

    class Meta:
        model = BookingLine
        fields = [
            "id",
            "style_code",
            "size",
            "description",
            "booked_qty",
            "mrp_paise",
            "received_qty",
            "inwarded_qty",
            "store",
            "store_name",
        ]


class BookingSerializer(serializers.ModelSerializer[Booking]):
    lines = BookingLineSerializer(many=True, read_only=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)
    season_code = serializers.CharField(source="season.code", read_only=True)
    destination_store_name = serializers.CharField(
        source="destination_store.name", read_only=True, default=None
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    booked_total = serializers.SerializerMethodField()
    received_total = serializers.SerializerMethodField()
    closed_by_name = serializers.CharField(
        source="closed_by.full_name", read_only=True, default=None
    )
    open_qty = serializers.IntegerField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "number",
            "vendor",
            "vendor_name",
            "brand",
            "brand_name",
            "season",
            "season_name",
            "season_code",
            "destination_store",
            "destination_store_name",
            "status",
            "status_label",
            "vendor_ref",
            "ownership",
            "return_terms",
            "estimated_value_paise",
            "notes",
            "lines",
            "booked_total",
            "received_total",
            "open_qty",
            "close_reason",
            "closed_at",
            "closed_by_name",
            "created_at",
        ]

    def get_booked_total(self, obj: Booking) -> int:
        return sum(line.booked_qty for line in obj.lines.all())

    def get_received_total(self, obj: Booking) -> int:
        return sum(line.received_qty for line in obj.lines.all())


class BookingCreateSerializer(serializers.Serializer[dict[str, Any]]):
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all())
    brand = serializers.PrimaryKeyRelatedField(queryset=Brand.objects.all())
    season = serializers.PrimaryKeyRelatedField(queryset=Season.objects.all())
    destination_store = serializers.IntegerField(required=False, allow_null=True)
    vendor_ref = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    source_file_id = serializers.IntegerField(required=False, allow_null=True)
    lines = serializers.ListField(child=serializers.DictField())
