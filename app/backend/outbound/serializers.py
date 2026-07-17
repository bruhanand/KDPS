"""Outbound serializers — DRF read/write shapes for outbound documents."""

from __future__ import annotations

from rest_framework import serializers

from outbound.models import (
    ReturnToVendor,
    ReturnToVendorLine,
    StockAdjustment,
    StockAdjustmentLine,
    StoreTransfer,
    StoreTransferLine,
    TransferReceipt,
    VFlip,
    VFlipLine,
    WriteOff,
    WriteOffLine,
)

# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------


class StoreTransferLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreTransferLine
        fields = [
            "id",
            "sku_code",
            "design",
            "color",
            "size",
            "brand",
            "season",
            "item",
            "hsn",
            "qty_dispatched",
            "qty_received",
            "unit_cost_paise",
        ]
        read_only_fields = ["id", "qty_received"]


class TransferReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransferReceipt
        fields = ["id", "received_by", "receipt_date", "receipt_status", "shortfall_notes"]
        read_only_fields = ["id", "receipt_date"]


class StoreTransferReadSerializer(serializers.ModelSerializer):
    lines = StoreTransferLineSerializer(many=True, read_only=True)
    receipt = TransferReceiptSerializer(read_only=True)
    source_store_code = serializers.CharField(source="source_store.code", read_only=True)
    source_store_name = serializers.CharField(source="source_store.name", read_only=True)
    destination_store_code = serializers.CharField(source="destination_store.code", read_only=True)
    destination_store_name = serializers.CharField(source="destination_store.name", read_only=True)

    class Meta:
        model = StoreTransfer
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "transfer_type",
            "is_cross_state",
            "source_store",
            "source_store_code",
            "source_store_name",
            "destination_store",
            "destination_store_code",
            "destination_store_name",
            "reason",
            "transport_mode",
            "transport_ref",
            "dispatcher_name",
            "expected_arrival_note",
            "eway_bill_number",
            "dispatch_date",
            "dispatched_by",
            "created_by",
            "created_at",
            "updated_at",
            "lines",
            "receipt",
        ]


class StoreTransferWriteSerializer(serializers.ModelSerializer):
    lines = StoreTransferLineSerializer(many=True)

    class Meta:
        model = StoreTransfer
        fields = [
            "source_store",
            "destination_store",
            "transfer_type",
            "reason",
            "transport_mode",
            "transport_ref",
            "dispatcher_name",
            "expected_arrival_note",
            "eway_bill_number",
            "lines",
        ]

    def validate(self, data):
        src = data.get("source_store")
        dst = data.get("destination_store")
        if src and dst and src == dst:
            raise serializers.ValidationError("Source and destination must differ.")
        if not data.get("lines"):
            raise serializers.ValidationError("At least one line is required.")
        return data

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        user = self.context.get("request", None)
        if user:
            user = user.user
        validated_data["created_by"] = user
        transfer = StoreTransfer.objects.create(**validated_data)
        for ld in lines_data:
            StoreTransferLine.objects.create(transfer=transfer, **ld)
        return transfer


class TransferReceiptInputSerializer(serializers.Serializer):
    """For the receipt action: maps line_id -> qty_received."""

    received_quantities = serializers.DictField(
        child=serializers.IntegerField(min_value=0),
        help_text="Mapping of line_id (int) to qty_received (int).",
        required=False,
    )


# ---------------------------------------------------------------------------
# RTV
# ---------------------------------------------------------------------------


class ReturnToVendorLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnToVendorLine
        fields = [
            "id",
            "sku_code",
            "design",
            "color",
            "size",
            "brand",
            "season",
            "item",
            "hsn",
            "qty",
            "unit_cost_paise",
        ]
        read_only_fields = ["id"]


class ReturnToVendorReadSerializer(serializers.ModelSerializer):
    lines = ReturnToVendorLineSerializer(many=True, read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = ReturnToVendor
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "store",
            "store_code",
            "store_name",
            "vendor",
            "brand",
            "return_type",
            "logistics_route",
            "season",
            "return_window_date",
            "credit_note_received",
            "credit_note_date",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
            "lines",
        ]


class ReturnToVendorWriteSerializer(serializers.ModelSerializer):
    lines = ReturnToVendorLineSerializer(many=True)

    class Meta:
        model = ReturnToVendor
        fields = [
            "store",
            "vendor",
            "brand",
            "return_type",
            "logistics_route",
            "season",
            "return_window_date",
            "notes",
            "lines",
        ]

    def validate(self, data):
        if not data.get("lines"):
            raise serializers.ValidationError("At least one line is required.")
        return data

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        user = self.context.get("request", None)
        if user:
            user = user.user
        validated_data["created_by"] = user
        rtv = ReturnToVendor.objects.create(**validated_data)
        for ld in lines_data:
            ReturnToVendorLine.objects.create(rtv=rtv, **ld)
        return rtv


# ---------------------------------------------------------------------------
# Stock Adjustment
# ---------------------------------------------------------------------------


class StockAdjustmentLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockAdjustmentLine
        fields = [
            "id",
            "sku_code",
            "design",
            "color",
            "size",
            "brand",
            "season",
            "item",
            "hsn",
            "book_qty",
            "counted_qty",
            "adj_qty",
            "unit_cost_paise",
        ]
        read_only_fields = ["id"]


class StockAdjustmentReadSerializer(serializers.ModelSerializer):
    lines = StockAdjustmentLineSerializer(many=True, read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = StockAdjustment
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "store",
            "store_code",
            "store_name",
            "reason",
            "approved_by",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
            "lines",
        ]


class StockAdjustmentWriteSerializer(serializers.ModelSerializer):
    lines = StockAdjustmentLineSerializer(many=True)

    class Meta:
        model = StockAdjustment
        fields = ["store", "reason", "approved_by", "notes", "lines"]

    def validate(self, data):
        if not data.get("lines"):
            raise serializers.ValidationError("At least one line is required.")
        return data

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        user = self.context.get("request", None)
        if user:
            user = user.user
        validated_data["created_by"] = user
        adj = StockAdjustment.objects.create(**validated_data)
        for ld in lines_data:
            StockAdjustmentLine.objects.create(adjustment=adj, **ld)
        return adj


# ---------------------------------------------------------------------------
# Write-off
# ---------------------------------------------------------------------------


class WriteOffLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = WriteOffLine
        fields = [
            "id",
            "sku_code",
            "design",
            "color",
            "size",
            "brand",
            "season",
            "item",
            "hsn",
            "qty",
            "unit_cost_paise",
        ]
        read_only_fields = ["id"]


class WriteOffReadSerializer(serializers.ModelSerializer):
    lines = WriteOffLineSerializer(many=True, read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = WriteOff
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "store",
            "store_code",
            "store_name",
            "reason",
            "approved_by",
            "created_by",
            "created_at",
            "updated_at",
            "lines",
        ]


class WriteOffWriteSerializer(serializers.ModelSerializer):
    lines = WriteOffLineSerializer(many=True)

    class Meta:
        model = WriteOff
        fields = ["store", "reason", "approved_by", "lines"]

    def validate(self, data):
        if not data.get("lines"):
            raise serializers.ValidationError("At least one line is required.")
        return data

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        user = self.context.get("request", None)
        if user:
            user = user.user
        validated_data["created_by"] = user
        wo = WriteOff.objects.create(**validated_data)
        for ld in lines_data:
            WriteOffLine.objects.create(writeoff=wo, **ld)
        return wo


# ---------------------------------------------------------------------------
# V-flip
# ---------------------------------------------------------------------------


class VFlipLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = VFlipLine
        fields = [
            "id",
            "sku_code",
            "design",
            "color",
            "size",
            "brand",
            "season",
            "item",
            "hsn",
            "qty",
            "unit_cost_paise",
        ]
        read_only_fields = ["id"]


class VFlipReadSerializer(serializers.ModelSerializer):
    lines = VFlipLineSerializer(many=True, read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    original_brand_name = serializers.CharField(source="original_brand.name", read_only=True)

    class Meta:
        model = VFlip
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "store",
            "store_code",
            "store_name",
            "original_brand",
            "original_brand_name",
            "season",
            "authorized_by",
            "created_by",
            "created_at",
            "updated_at",
            "lines",
        ]


class VFlipWriteSerializer(serializers.ModelSerializer):
    lines = VFlipLineSerializer(many=True)

    class Meta:
        model = VFlip
        fields = ["store", "original_brand", "season", "authorized_by", "lines"]

    def validate(self, data):
        if not data.get("lines"):
            raise serializers.ValidationError("At least one line is required.")
        return data

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        user = self.context.get("request", None)
        if user:
            user = user.user
        validated_data["created_by"] = user
        vflip = VFlip.objects.create(**validated_data)
        for ld in lines_data:
            VFlipLine.objects.create(vflip=vflip, **ld)
        return vflip
