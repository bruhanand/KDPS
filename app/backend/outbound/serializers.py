"""Outbound serializers — DRF read/write shapes for outbound documents."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import serializers

from approvals.serializers import ApprovalReadSerializer
from masters.models import Store
from outbound.maker_checker import request_document_approval
from outbound.models import (
    MarkDamaged,
    MarkDamagedLine,
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
# Maker-checker read shape (#70)
# ---------------------------------------------------------------------------


def _actor_name(user: Any) -> str:
    if user is None:
        return ""
    return getattr(user, "full_name", "") or getattr(user, "username", "") or ""


class ApprovedDocumentSerializer(serializers.ModelSerializer):
    """Base read shape for a document that needs a second person.

    Every such document answers the same three questions on its own page, for
    good: **made by** whom, **approved by** whom, and **when** — plus the live
    approval record (pending / approved / rejected, with the reject reason).
    """

    #: The document's own approver column — V-flip calls it ``authorized_by``.
    approver_field = "approved_by"

    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()

    def get_created_by_name(self, obj: Any) -> str:
        return _actor_name(obj.created_by)

    def get_approved_by_name(self, obj: Any) -> str:
        return _actor_name(getattr(obj, self.approver_field, None))

    def get_approval(self, obj: Any) -> dict[str, Any] | None:
        approval = next(iter(obj.approvals.all()), None)
        return ApprovalReadSerializer(approval).data if approval else None


def _create_with_approval(
    model: Any, line_model: Any, line_field: str, validated_data: Any, request: Any
) -> Any:
    """Create a draft + its lines, then put it in the approvals inbox.

    One transaction: a draft that needs a checker is never left without one.
    """
    lines_data = validated_data.pop("lines")
    user = getattr(request, "user", None)
    validated_data["created_by"] = user
    with transaction.atomic():
        doc = model.objects.create(**validated_data)
        for ld in lines_data:
            line_model.objects.create(**{line_field: doc, **ld})
        request_document_approval(doc, requested_by=user)
    return doc


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------


class StoreTransferLineSerializer(serializers.ModelSerializer):
    """Read shape. Quantities are scan-derived: ``qty_planned`` is the plan,
    ``qty_dispatched``/``qty_received`` are what was scanned, ``qty_in_transit``
    is derived (dispatched − received), never stored."""

    qty_in_transit = serializers.IntegerField(read_only=True)

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
            "qty_planned",
            "qty_dispatched",
            "qty_received",
            "qty_in_transit",
            "unit_cost_paise",
        ]
        read_only_fields = ["id", "qty_dispatched", "qty_received", "unit_cost_paise"]


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
    dispatch_mismatch = serializers.SerializerMethodField()

    def get_dispatch_mismatch(self, obj: StoreTransfer) -> bool:
        """Derived, never stored: a dispatched transfer whose scanned
        quantities differ from its plan (Rule 5 — flagged, not blocked)."""
        from core.documents import DocStatus

        if obj.docstatus == DocStatus.DRAFT:  # nothing scanned yet
            return False
        return any(
            line.qty_planned is not None and line.qty_planned != line.qty_dispatched
            for line in obj.lines.all()
        )

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
            "dispatch_mismatch",
            "lines",
            "receipt",
        ]


class StoreTransferPlanLineSerializer(serializers.ModelSerializer):
    """Write shape for a draft's *plan* line. Only the plan quantity is
    accepted — dispatched/received quantities come from scanning, never typing
    (#68). Dims and cost are enriched from the source stock at dispatch."""

    qty_planned = serializers.IntegerField(min_value=1)

    class Meta:
        model = StoreTransferLine
        fields = ["sku_code", "qty_planned"]


class StoreTransferWriteSerializer(serializers.ModelSerializer):
    """Creates a draft transfer. ``lines`` (the plan) is optional — a
    store→store transfer builds its lines by scanning at dispatch."""

    lines = StoreTransferPlanLineSerializer(many=True, required=False)

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
        return data

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        user = self.context.get("request", None)
        if user:
            user = user.user
        validated_data["created_by"] = user
        transfer = StoreTransfer.objects.create(**validated_data)
        for ld in lines_data:
            StoreTransferLine.objects.create(transfer=transfer, **ld)
        return transfer


class ScanLineSerializer(serializers.Serializer):
    """One scanned (barcode × count) pair from the scan screen."""

    barcode = serializers.CharField(max_length=64)
    qty = serializers.IntegerField(min_value=1)


class TransferScanInputSerializer(serializers.Serializer):
    """For dispatch/receive: the scanned lines are the only quantities."""

    scans = ScanLineSerializer(many=True, allow_empty=False)

    def scans_by_barcode(self) -> dict[str, int]:
        """Aggregate scans into barcode → total qty (a barcode may repeat)."""
        totals: dict[str, int] = {}
        for scan in self.validated_data["scans"]:
            totals[scan["barcode"]] = totals.get(scan["barcode"], 0) + scan["qty"]
        return totals


# ---------------------------------------------------------------------------
# Mark damaged (global action → quarantine)
# ---------------------------------------------------------------------------


class MarkDamagedLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarkDamagedLine
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
        read_only_fields = fields


class MarkDamagedReadSerializer(serializers.ModelSerializer):
    lines = MarkDamagedLineSerializer(many=True, read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = MarkDamaged
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "store",
            "store_code",
            "store_name",
            "note",
            "created_by",
            "created_at",
            "lines",
        ]


class MarkDamagedInputSerializer(serializers.Serializer):
    """The global mark-damaged action: a store + scanned pieces (+ optional
    note). Quantities are scanned, dims/cost enriched from the store's stock —
    never typed."""

    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    scans = ScanLineSerializer(many=True, allow_empty=False)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")

    def scans_by_barcode(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for scan in self.validated_data["scans"]:
            totals[scan["barcode"]] = totals.get(scan["barcode"], 0) + scan["qty"]
        return totals


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


class StockAdjustmentReadSerializer(ApprovedDocumentSerializer):
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
            "approved_by_name",
            "approval",
            "notes",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
            "lines",
        ]


class StockAdjustmentWriteSerializer(serializers.ModelSerializer):
    """``approved_by`` is not accepted: the approver is stamped by whoever
    clears the approvals inbox, and can never be the maker (#70)."""

    lines = StockAdjustmentLineSerializer(many=True)

    class Meta:
        model = StockAdjustment
        fields = ["store", "reason", "notes", "lines"]

    def validate(self, data):
        if not data.get("lines"):
            raise serializers.ValidationError("At least one line is required.")
        return data

    def create(self, validated_data):
        return _create_with_approval(
            StockAdjustment,
            StockAdjustmentLine,
            "adjustment",
            validated_data,
            self.context.get("request"),
        )


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


class WriteOffReadSerializer(ApprovedDocumentSerializer):
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
            "approved_by_name",
            "approval",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
            "lines",
        ]


class WriteOffWriteSerializer(serializers.ModelSerializer):
    """``approved_by`` is not accepted: the approver is stamped by whoever
    clears the approvals inbox, and can never be the maker (#70)."""

    lines = WriteOffLineSerializer(many=True)

    class Meta:
        model = WriteOff
        fields = ["store", "reason", "lines"]

    def validate(self, data):
        if not data.get("lines"):
            raise serializers.ValidationError("At least one line is required.")
        return data

    def create(self, validated_data):
        return _create_with_approval(
            WriteOff, WriteOffLine, "writeoff", validated_data, self.context.get("request")
        )


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


class VFlipReadSerializer(ApprovedDocumentSerializer):
    """V-flip's approver column is ``authorized_by``; it still answers the
    common "approved by whom" question through ``approved_by_name``."""

    approver_field = "authorized_by"

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
            "approved_by_name",
            "approval",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
            "lines",
        ]


class VFlipWriteSerializer(serializers.ModelSerializer):
    """``authorized_by`` is not accepted: the authoriser is stamped by whoever
    clears the approvals inbox, and can never be the maker (#70)."""

    lines = VFlipLineSerializer(many=True)

    class Meta:
        model = VFlip
        fields = ["store", "original_brand", "season", "lines"]

    def validate(self, data):
        if not data.get("lines"):
            raise serializers.ValidationError("At least one line is required.")
        return data

    def create(self, validated_data):
        return _create_with_approval(
            VFlip, VFlipLine, "vflip", validated_data, self.context.get("request")
        )
