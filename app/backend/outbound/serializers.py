"""Outbound serializers — DRF read/write shapes for outbound documents."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import serializers

from approvals.models import ApprovalStatus
from approvals.serializers import ApprovalReadSerializer
from approvals.services import display_name
from core.documents import DocStatus
from masters.models import Store
from outbound.maker_checker import request_document_approval
from outbound.models import (
    GapReason,
    MarkDamaged,
    MarkDamagedLine,
    ReturnToVendor,
    ReturnToVendorLine,
    StockAdjustment,
    StockAdjustmentLine,
    StoreTransfer,
    StoreTransferLine,
    TransferGapClosure,
    TransferGapClosureLine,
    TransferReceipt,
    TransferReceiptException,
    VFlip,
    VFlipLine,
    WriteOff,
    WriteOffLine,
)

# ---------------------------------------------------------------------------
# Maker-checker read shape (#70)
# ---------------------------------------------------------------------------


class ApprovedDocumentSerializer(serializers.ModelSerializer):
    """Base read shape for a document that needs a second person.

    Every such document answers the same three questions on its own page, for
    good: **made by** whom, **approved by** whom, and **when** — plus the live
    approval record (pending / approved / rejected, with the reject reason).

    The approver is read from the approval, not from the document's own column:
    the column is a denormalised copy stamped at post time (for Tally), so on a
    still-unposted draft only the approval knows the answer.
    """

    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()
    approval_history = serializers.SerializerMethodField()

    def _approval(self, obj: Any) -> Any:
        """The live one. A document that was rejected and asked again holds
        several, newest first — the newest is the one in force."""
        return next(iter(obj.approvals.all()), None)

    def get_created_by_name(self, obj: Any) -> str:
        return display_name(obj.created_by)

    def get_approved_by_name(self, obj: Any) -> str:
        approval = self._approval(obj)
        if approval is None or approval.status != ApprovalStatus.APPROVED:
            return ""
        return display_name(approval.decided_by)

    def get_approval(self, obj: Any) -> dict[str, Any] | None:
        approval = self._approval(obj)
        return ApprovalReadSerializer(approval).data if approval else None

    def get_approval_history(self, obj: Any) -> list[dict[str, Any]]:
        """Everything asked before the live one — the rejections a maker has
        already worked through. Empty for the common case."""
        return [ApprovalReadSerializer(a).data for a in list(obj.approvals.all())[1:]]


def _priced_lines(validated_data: Any) -> list[dict[str, Any]]:
    """Take the lines off a validated create payload, priced from the books (#103).

    A draft is *born* with its cost of record, so the approval band, the posting
    engine and the screen all read the same number — and a line the books cannot
    price never becomes a document at all, rather than posting free stock later.
    The refusal is a 400 on the create call, not a 500: an unpriceable piece is
    something the maker has to fix, and the message says how.

    Takes the whole payload rather than its parts because every caller needs the
    same three (store, lines, the document's season) and the lines must come
    *off* it before the document is created from what is left.
    """
    from outbound.posting import OutboundPostingError, resolve_line_identity

    store = validated_data["store"]
    doc_season = validated_data.get("season", "")
    priced = []
    for ld in validated_data.pop("lines"):
        try:
            identity = resolve_line_identity(
                store.id, ld["sku_code"], ld.get("season") or doc_season
            )
        except OutboundPostingError as exc:
            raise serializers.ValidationError({"lines": [str(exc)]}) from exc
        priced.append({**ld, **identity})
    return priced


def _create_with_approval(
    model: Any, line_model: Any, line_field: str, validated_data: Any, request: Any
) -> Any:
    """Create a draft + its lines, then put it in the approvals inbox.

    One transaction: a draft that needs a checker is never left without one.
    """
    lines_data = _priced_lines(validated_data)
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
    ``qty_dispatched``/``qty_received`` are what was scanned, ``qty_resolved``
    is what a posted gap closure accounted for, and ``qty_in_transit`` is derived
    from the three, never stored."""

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
            "qty_resolved",
            "qty_in_transit",
            "unit_cost_paise",
        ]
        read_only_fields = [
            "id",
            "qty_dispatched",
            "qty_received",
            "qty_resolved",
            "unit_cost_paise",
        ]


class ReceiptExceptionSerializer(serializers.ModelSerializer):
    """One short / extra / damaged outcome, as recorded at receive (#71)."""

    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = TransferReceiptException
        fields = [
            "id",
            "kind",
            "kind_label",
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
            "note",
        ]
        read_only_fields = fields


class TransferReceiptSerializer(serializers.ModelSerializer):
    exceptions = ReceiptExceptionSerializer(many=True, read_only=True)
    received_by_name = serializers.SerializerMethodField()

    def get_received_by_name(self, obj: TransferReceipt) -> str:
        return display_name(obj.received_by)

    class Meta:
        model = TransferReceipt
        fields = [
            "id",
            "received_by",
            "received_by_name",
            "receipt_date",
            "receipt_status",
            "shortfall_notes",
            "exceptions",
        ]
        read_only_fields = ["id", "receipt_date"]


class GapClosureLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransferGapClosureLine
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


class GapClosureReadSerializer(ApprovedDocumentSerializer):
    """A gap closure and everything a reviewer needs to judge it — which
    transfer, which pieces, whose reason, and who signed it off."""

    lines = GapClosureLineSerializer(many=True, read_only=True)
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    transfer_doc_number = serializers.CharField(source="transfer.doc_number", read_only=True)
    source_store_code = serializers.CharField(source="transfer.source_store.code", read_only=True)
    destination_store_code = serializers.CharField(
        source="transfer.destination_store.code", read_only=True
    )

    class Meta:
        model = TransferGapClosure
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "transfer",
            "transfer_doc_number",
            "store",
            "store_code",
            "source_store_code",
            "destination_store_code",
            "reason",
            "reason_label",
            "note",
            "approved_by",
            "approved_by_name",
            "approval",
            "approval_history",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
            "lines",
        ]


class GapClosureInputSerializer(serializers.Serializer):
    """Raising a closure: a reason and (optionally) a sentence. Nothing else —
    the lines are read off the transfer's in-transit remainder, so the person
    closing the gap cannot quietly change how much went missing."""

    reason = serializers.ChoiceField(choices=GapReason.choices)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class StoreTransferReadSerializer(serializers.ModelSerializer):
    lines = StoreTransferLineSerializer(many=True, read_only=True)
    receipt = TransferReceiptSerializer(read_only=True)
    gap_closure = GapClosureReadSerializer(read_only=True)
    source_store_code = serializers.CharField(source="source_store.code", read_only=True)
    source_store_name = serializers.CharField(source="source_store.name", read_only=True)
    destination_store_code = serializers.CharField(source="destination_store.code", read_only=True)
    destination_store_name = serializers.CharField(source="destination_store.name", read_only=True)
    dispatch_mismatch = serializers.SerializerMethodField()
    qty_in_transit = serializers.SerializerMethodField()
    gap_state = serializers.SerializerMethodField()

    def get_dispatch_mismatch(self, obj: StoreTransfer) -> bool:
        """Derived, never stored: a dispatched transfer whose scanned
        quantities differ from its plan (Rule 5 — flagged, not blocked)."""

        if obj.docstatus == DocStatus.DRAFT:  # nothing scanned yet
            return False
        return any(
            line.qty_planned is not None and line.qty_planned != line.qty_dispatched
            for line in obj.lines.all()
        )

    def get_qty_in_transit(self, obj: StoreTransfer) -> int:
        """Pieces still on the road (or missing) under this transfer."""

        if obj.docstatus != DocStatus.SUBMITTED:
            return 0
        return sum(line.qty_in_transit for line in obj.lines.all())

    def get_gap_state(self, obj: StoreTransfer) -> str:
        """Where this transfer stands, derived from its documents — never stored
        (the architecture's rule: a lifecycle is read off the record, not set).

        ``in_transit`` nothing received yet · ``received`` all of it landed ·
        ``gap`` received short, still open · ``closed`` a senior said what became
        of the shortfall.
        """

        if obj.docstatus != DocStatus.SUBMITTED:
            return ""
        receipt = getattr(obj, "receipt", None)
        if receipt is None:
            return "in_transit"
        closure = getattr(obj, "gap_closure", None)
        if closure is not None and closure.docstatus == DocStatus.SUBMITTED:
            return "closed"
        return "gap" if self.get_qty_in_transit(obj) > 0 else "received"

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
            "qty_in_transit",
            "gap_state",
            "lines",
            "receipt",
            "gap_closure",
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


def _totals(scans: list[dict[str, Any]] | None) -> dict[str, int]:
    """Aggregate a scan list into barcode → total qty (a barcode may repeat)."""
    totals: dict[str, int] = {}
    for scan in scans or []:
        totals[scan["barcode"]] = totals.get(scan["barcode"], 0) + scan["qty"]
    return totals


class TransferScanInputSerializer(serializers.Serializer):
    """For dispatch: the scanned lines are the only quantities."""

    scans = ScanLineSerializer(many=True, allow_empty=False)

    def scans_by_barcode(self) -> dict[str, int]:
        return _totals(self.validated_data["scans"])


class TransferReceiveInputSerializer(serializers.Serializer):
    """Receiving, with the three exceptions the carton actually produces (#71).

    ``scans`` are the pieces that arrived intact, ``damaged`` the ones that
    arrived broken (quarantine, never the shop floor), ``extras`` the ones that
    arrived without being sent. ``notes`` is the receiver's sentence about the
    shortfall — the field the old payload dropped.

    Any one bucket may be empty but not all three: a receipt records something
    turning up. Which barcodes belong in which bucket is the server's call, in
    ``posting._validate_receive``.
    """

    scans = ScanLineSerializer(many=True, required=False, default=list)
    damaged = ScanLineSerializer(many=True, required=False, default=list)
    extras = ScanLineSerializer(many=True, required=False, default=list)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate(self, data: Any) -> Any:
        if not (data.get("scans") or data.get("damaged") or data.get("extras")):
            raise serializers.ValidationError(
                "Scan at least one piece — as received, damaged, or an extra."
            )
        return data

    def scans_by_barcode(self) -> dict[str, int]:
        return _totals(self.validated_data["scans"])

    def damaged_by_barcode(self) -> dict[str, int]:
        return _totals(self.validated_data["damaged"])

    def extras_by_barcode(self) -> dict[str, int]:
        return _totals(self.validated_data["extras"])


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


class MarkDamagedReadSerializer(ApprovedDocumentSerializer):
    """A damage report and where it has got to (#138).

    The maker-checker half — who reported it, who confirmed it, the live
    approval and its reason — is the base's, read off one prefetch. ``flag_status``
    is the word only this family needs: the store that reported the damage has
    to see its report is still waiting, and the person who can confirm it needs
    the same row to say what they are being asked.
    """

    lines = MarkDamagedLineSerializer(many=True, read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    confirmed_by_name = serializers.SerializerMethodField()
    flag_status = serializers.SerializerMethodField()

    def get_confirmed_by_name(self, obj: MarkDamaged) -> str:
        return display_name(obj.confirmed_by)

    def get_flag_status(self, obj: MarkDamaged) -> str:
        """Confirmed once it has posted; otherwise whatever the inbox says."""
        if obj.docstatus == DocStatus.SUBMITTED:
            return "confirmed"
        approval = self._approval(obj)
        if approval is not None and approval.status == ApprovalStatus.REJECTED:
            return "rejected"
        return "flagged"

    class Meta:
        model = MarkDamaged
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "flag_status",
            "store",
            "store_code",
            "store_name",
            "note",
            "created_by",
            "created_by_name",
            "confirmed_by",
            "confirmed_by_name",
            "approved_by_name",
            "approval",
            "approval_history",
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
    """``unit_cost_paise`` is read-only: a money posting reads its cost from the
    books, never from the payload (#103) — same rule as a transfer line."""

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
        read_only_fields = ["id", "unit_cost_paise"]


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
        lines_data = _priced_lines(validated_data)
        user = self.context.get("request", None)
        if user:
            user = user.user
        validated_data["created_by"] = user
        with transaction.atomic():
            rtv = ReturnToVendor.objects.create(**validated_data)
            for ld in lines_data:
                ReturnToVendorLine.objects.create(rtv=rtv, **ld)
        return rtv


# ---------------------------------------------------------------------------
# Stock Adjustment
# ---------------------------------------------------------------------------


class StockAdjustmentLineSerializer(serializers.ModelSerializer):
    """``unit_cost_paise`` is read-only: a money posting reads its cost from the
    books, never from the payload (#103) — same rule as a transfer line."""

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
        read_only_fields = ["id", "unit_cost_paise"]


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
            "approval_history",
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
    """``unit_cost_paise`` is read-only: a money posting reads its cost from the
    books, never from the payload (#103) — same rule as a transfer line."""

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
        read_only_fields = ["id", "unit_cost_paise"]


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
            "approval_history",
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
    """``unit_cost_paise`` is read-only: a money posting reads its cost from the
    books, never from the payload (#103) — same rule as a transfer line."""

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
        read_only_fields = ["id", "unit_cost_paise"]


class VFlipReadSerializer(ApprovedDocumentSerializer):
    """V-flip's own approver column is ``authorized_by``; it still answers the
    common "approved by whom" question through ``approved_by_name``."""

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
            "approval_history",
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
