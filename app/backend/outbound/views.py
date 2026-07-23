"""Outbound API views — list, create, dispatch, receive, submit.

Every endpoint requires authentication. RBAC:
  - Read (GET list/detail): any authenticated user (store scoping via queryset)
  - Write (POST create/submit/dispatch/receive): OUTBOUND_WRITE_ROLES
  - Admin write (V-flip, write-off): OUTBOUND_ADMIN_ROLES
  - store_staff: READ ONLY on all outbound surfaces
  - Store-scoped roles: may only write against their assigned stores
    (enforced via ``enforce_store_scope`` on every write path)
"""

from __future__ import annotations

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.documents import DocStatus
from outbound.models import (
    MarkDamaged,
    ReturnToVendor,
    StockAdjustment,
    StoreTransfer,
    VFlip,
    WriteOff,
)
from outbound.permissions import (
    IsOutboundAdmin,
    IsOutboundReader,
    IsOutboundWriter,
    enforce_store_scope,
)
from outbound.posting import (
    OutboundPostingError,
    mark_damaged,
    post_adjustment,
    post_rtv,
    post_transfer_dispatch,
    post_transfer_receipt,
    post_vflip,
    post_writeoff,
)
from outbound.serializers import (
    MarkDamagedInputSerializer,
    MarkDamagedReadSerializer,
    ReturnToVendorReadSerializer,
    ReturnToVendorWriteSerializer,
    StockAdjustmentReadSerializer,
    StockAdjustmentWriteSerializer,
    StoreTransferReadSerializer,
    StoreTransferWriteSerializer,
    TransferScanInputSerializer,
    VFlipReadSerializer,
    VFlipWriteSerializer,
    WriteOffReadSerializer,
    WriteOffWriteSerializer,
)

# ---------------------------------------------------------------------------
# Transfer views
# ---------------------------------------------------------------------------


class TransferListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsOutboundWriter()]
        return [IsOutboundReader()]

    def get_queryset(self):
        qs = StoreTransfer.objects.select_related(
            "source_store", "destination_store", "created_by"
        ).prefetch_related("lines")
        ttype = self.request.query_params.get("type")
        if ttype:
            qs = qs.filter(transfer_type=ttype)
        ds = self.request.query_params.get("docstatus")
        if ds is not None:
            qs = qs.filter(docstatus=int(ds))
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StoreTransferWriteSerializer
        return StoreTransferReadSerializer

    def create(self, request, *args, **kwargs):
        ser = StoreTransferWriteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        enforce_store_scope(request.user, ser.validated_data["source_store"].id)
        instance = ser.save()
        return Response(
            StoreTransferReadSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class TransferDetailView(generics.RetrieveAPIView):
    permission_classes = [IsOutboundReader]
    serializer_class = StoreTransferReadSerializer

    def get_queryset(self):
        return StoreTransfer.objects.select_related(
            "source_store", "destination_store", "created_by"
        ).prefetch_related("lines")


class TransferDispatchView(APIView):
    """POST: Dispatch a draft transfer from scanned lines only (#68).

    Payload: ``{"scans": [{"barcode": ..., "qty": ...}, ...]}`` — the scanned
    quantities are the only quantities; typed dispatch is gone. Stock moves
    source → in-transit bucket under this transfer.
    """

    permission_classes = [IsOutboundWriter]

    def post(self, request, pk):
        try:
            transfer = (
                StoreTransfer.objects.select_related("source_store", "destination_store")
                .prefetch_related("lines")
                .get(pk=pk)
            )
        except StoreTransfer.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        enforce_store_scope(request.user, transfer.source_store_id)

        if transfer.docstatus != DocStatus.DRAFT:
            return Response(
                {"error": "Only drafts can be dispatched"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = TransferScanInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            post_transfer_dispatch(transfer, ser.scans_by_barcode(), user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        transfer.refresh_from_db()
        return Response(StoreTransferReadSerializer(transfer).data)


class TransferReceiveView(APIView):
    """POST: Receive a dispatched transfer from scanned lines only (#68).

    Payload: ``{"scans": [{"barcode": ..., "qty": ...}, ...]}``. Each scanned
    piece moves in-transit → destination; a short receive leaves the remainder
    in-transit and flags the receipt.
    """

    permission_classes = [IsOutboundWriter]

    def post(self, request, pk):
        try:
            transfer = (
                StoreTransfer.objects.select_related("source_store", "destination_store")
                .prefetch_related("lines")
                .get(pk=pk)
            )
        except StoreTransfer.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        enforce_store_scope(request.user, transfer.destination_store_id)

        if transfer.docstatus != DocStatus.SUBMITTED:
            return Response(
                {"error": "Only dispatched transfers can be received"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = TransferScanInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            post_transfer_receipt(transfer, ser.scans_by_barcode(), user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        transfer.refresh_from_db()
        return Response(StoreTransferReadSerializer(transfer).data)


class ScanLookupView(APIView):
    """GET ?store=&barcode= — per-scan validation for the scan screen.

    Returns the piece's identity + available qty at the location (for the
    right-piece beep and scan-to-build), 404 when the location holds no such
    stock (the wrong-piece beep).
    """

    permission_classes = [IsOutboundReader]

    def get(self, request):
        from masters.scoping import scope_by_store
        from stockledger.models import StockOnHand, merch_dims

        store_id = request.query_params.get("store")
        barcode = (request.query_params.get("barcode") or "").strip()
        if not store_id or not barcode:
            return Response(
                {"error": "Pass store= and barcode="}, status=status.HTTP_400_BAD_REQUEST
            )

        # Fail-closed (ADR-0003): a store-scoped user can only probe stock at
        # their own stores — an out-of-scope store looks identical to no stock.
        visible = scope_by_store(StockOnHand.objects.all(), request.user, "store_id")
        try:
            on_hand = visible.get(store_id=int(store_id), sku_code=barcode)
        except (StockOnHand.DoesNotExist, ValueError):
            return Response(
                {"error": f"No stock for {barcode} at this location"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "barcode": on_hand.sku_code,
                **merch_dims(on_hand),
                "available_qty": on_hand.net_qty,
            }
        )


# ---------------------------------------------------------------------------
# Mark damaged (global action → quarantine)
# ---------------------------------------------------------------------------


class MarkDamagedView(generics.ListCreateAPIView):
    """GET: list mark-damaged documents. POST: the global mark-damaged action —
    create a DMG document from scanned pieces and post it in one call, moving
    each piece from free-to-sell into quarantine at the store.

    Any outbound writer (including store-level roles) may mark damaged from any
    stock view — damage is caught everywhere. store_staff is read-only.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsOutboundWriter()]
        return [IsOutboundReader()]

    def get_queryset(self):
        from masters.scoping import scope_by_store

        qs = MarkDamaged.objects.select_related("store", "created_by").prefetch_related("lines")
        ds = self.request.query_params.get("docstatus")
        if ds is not None:
            qs = qs.filter(docstatus=int(ds))
        return scope_by_store(qs, self.request.user, "store_id")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return MarkDamagedInputSerializer
        return MarkDamagedReadSerializer

    def create(self, request, *args, **kwargs):
        ser = MarkDamagedInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        store = ser.validated_data["store"]
        enforce_store_scope(request.user, store.id)

        try:
            mark = mark_damaged(
                store,
                ser.scans_by_barcode(),
                user=request.user,
                note=ser.validated_data.get("note", ""),
            )
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(MarkDamagedReadSerializer(mark).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# RTV views
# ---------------------------------------------------------------------------


class RTVListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsOutboundWriter()]
        return [IsOutboundReader()]

    def get_queryset(self):
        qs = ReturnToVendor.objects.select_related(
            "store", "vendor", "brand", "created_by"
        ).prefetch_related("lines")
        ds = self.request.query_params.get("docstatus")
        if ds is not None:
            qs = qs.filter(docstatus=int(ds))
        rt = self.request.query_params.get("return_type")
        if rt:
            qs = qs.filter(return_type=rt)
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ReturnToVendorWriteSerializer
        return ReturnToVendorReadSerializer

    def create(self, request, *args, **kwargs):
        ser = ReturnToVendorWriteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        enforce_store_scope(request.user, ser.validated_data["store"].id)
        instance = ser.save()
        return Response(
            ReturnToVendorReadSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class RTVDetailView(generics.RetrieveAPIView):
    permission_classes = [IsOutboundReader]
    serializer_class = ReturnToVendorReadSerializer

    def get_queryset(self):
        return ReturnToVendor.objects.select_related(
            "store", "vendor", "brand", "created_by"
        ).prefetch_related("lines")


class RTVSubmitView(APIView):
    """POST: Submit (post) a draft RTV — stock exits, GL posts."""

    permission_classes = [IsOutboundWriter]

    def post(self, request, pk):
        try:
            rtv = (
                ReturnToVendor.objects.select_related("store", "vendor", "brand")
                .prefetch_related("lines")
                .get(pk=pk)
            )
        except ReturnToVendor.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        enforce_store_scope(request.user, rtv.store_id)

        if rtv.docstatus != DocStatus.DRAFT:
            return Response(
                {"error": "Only drafts can be submitted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            post_rtv(rtv, user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        rtv.refresh_from_db()
        return Response(ReturnToVendorReadSerializer(rtv).data)


# ---------------------------------------------------------------------------
# Stock Adjustment views
# ---------------------------------------------------------------------------


class AdjustmentListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsOutboundWriter()]
        return [IsOutboundReader()]

    def get_queryset(self):
        qs = StockAdjustment.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related("lines")
        ds = self.request.query_params.get("docstatus")
        if ds is not None:
            qs = qs.filter(docstatus=int(ds))
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StockAdjustmentWriteSerializer
        return StockAdjustmentReadSerializer

    def create(self, request, *args, **kwargs):
        ser = StockAdjustmentWriteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        enforce_store_scope(request.user, ser.validated_data["store"].id)
        instance = ser.save()
        return Response(
            StockAdjustmentReadSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class AdjustmentDetailView(generics.RetrieveAPIView):
    permission_classes = [IsOutboundReader]
    serializer_class = StockAdjustmentReadSerializer

    def get_queryset(self):
        return StockAdjustment.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related("lines")


class AdjustmentSubmitView(APIView):
    """POST: Submit (post) a draft stock adjustment."""

    permission_classes = [IsOutboundWriter]

    def post(self, request, pk):
        try:
            adj = (
                StockAdjustment.objects.select_related("store").prefetch_related("lines").get(pk=pk)
            )
        except StockAdjustment.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        enforce_store_scope(request.user, adj.store_id)

        if adj.docstatus != DocStatus.DRAFT:
            return Response(
                {"error": "Only drafts can be submitted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            post_adjustment(adj, user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        adj.refresh_from_db()
        return Response(StockAdjustmentReadSerializer(adj).data)


# ---------------------------------------------------------------------------
# Write-off views  (admin-only write)
# ---------------------------------------------------------------------------


class WriteOffListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsOutboundAdmin()]
        return [IsOutboundReader()]

    def get_queryset(self):
        qs = WriteOff.objects.select_related("store", "approved_by", "created_by").prefetch_related(
            "lines"
        )
        ds = self.request.query_params.get("docstatus")
        if ds is not None:
            qs = qs.filter(docstatus=int(ds))
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return WriteOffWriteSerializer
        return WriteOffReadSerializer

    def create(self, request, *args, **kwargs):
        ser = WriteOffWriteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        enforce_store_scope(request.user, ser.validated_data["store"].id)
        instance = ser.save()
        return Response(
            WriteOffReadSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class WriteOffDetailView(generics.RetrieveAPIView):
    permission_classes = [IsOutboundReader]
    serializer_class = WriteOffReadSerializer

    def get_queryset(self):
        return WriteOff.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related("lines")


class WriteOffSubmitView(APIView):
    """POST: Submit (post) a draft write-off."""

    permission_classes = [IsOutboundAdmin]

    def post(self, request, pk):
        try:
            wo = WriteOff.objects.select_related("store").prefetch_related("lines").get(pk=pk)
        except WriteOff.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        enforce_store_scope(request.user, wo.store_id)

        if wo.docstatus != DocStatus.DRAFT:
            return Response(
                {"error": "Only drafts can be submitted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            post_writeoff(wo, user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        wo.refresh_from_db()
        return Response(WriteOffReadSerializer(wo).data)


# ---------------------------------------------------------------------------
# V-flip views  (admin-only write)
# ---------------------------------------------------------------------------


class VFlipListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsOutboundAdmin()]
        return [IsOutboundReader()]

    def get_queryset(self):
        qs = VFlip.objects.select_related(
            "store", "original_brand", "authorized_by", "created_by"
        ).prefetch_related("lines")
        ds = self.request.query_params.get("docstatus")
        if ds is not None:
            qs = qs.filter(docstatus=int(ds))
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return VFlipWriteSerializer
        return VFlipReadSerializer

    def create(self, request, *args, **kwargs):
        ser = VFlipWriteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        enforce_store_scope(request.user, ser.validated_data["store"].id)
        instance = ser.save()
        return Response(
            VFlipReadSerializer(instance).data,
            status=status.HTTP_201_CREATED,
        )


class VFlipDetailView(generics.RetrieveAPIView):
    permission_classes = [IsOutboundReader]
    serializer_class = VFlipReadSerializer

    def get_queryset(self):
        return VFlip.objects.select_related(
            "store", "original_brand", "authorized_by", "created_by"
        ).prefetch_related("lines")


class VFlipSubmitView(APIView):
    """POST: Submit (post) a draft V-flip."""

    permission_classes = [IsOutboundAdmin]

    def post(self, request, pk):
        try:
            vflip = (
                VFlip.objects.select_related("store", "original_brand")
                .prefetch_related("lines")
                .get(pk=pk)
            )
        except VFlip.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        enforce_store_scope(request.user, vflip.store_id)

        if vflip.docstatus != DocStatus.DRAFT:
            return Response(
                {"error": "Only drafts can be submitted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            post_vflip(vflip, user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        vflip.refresh_from_db()
        return Response(VFlipReadSerializer(vflip).data)
