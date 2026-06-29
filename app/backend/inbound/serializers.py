from __future__ import annotations

from rest_framework import serializers

from inbound.models import Grn, GrnLine


class GrnLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrnLine
        fields = [
            "id",
            "booking_line",
            "style_code",
            "size",
            "color",
            "barcode",
            "received_qty",
            "damaged_qty",
            "is_variance",
            "remark",
        ]


class GrnSerializer(serializers.ModelSerializer):
    lines = GrnLineSerializer(many=True, read_only=True)
    number = serializers.CharField(source="doc_number", read_only=True, allow_null=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    booking_number = serializers.CharField(source="booking.number", read_only=True, default=None)
    vendor_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    received_total = serializers.SerializerMethodField()

    class Meta:
        model = Grn
        fields = [
            "id",
            "number",
            "booking",
            "booking_number",
            "vendor",
            "vendor_name",
            "store",
            "store_code",
            "store_name",
            "received_at",
            "status",
            "status_label",
            "is_direct",
            "invoice_number",
            "invoice_file",
            "notes",
            "lines",
            "received_total",
            "created_at",
        ]

    def get_vendor_name(self, obj: Grn) -> str:
        return obj.vendor.name if obj.vendor else obj.vendor_name_raw

    def get_received_total(self, obj: Grn) -> int:
        return sum(line.received_qty for line in obj.lines.all())
