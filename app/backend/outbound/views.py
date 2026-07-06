"""Outbound API views — list, create, dispatch, receive, submit.

Every endpoint requires authentication. RBAC mirrors the existing patterns
in inbound/finledger: owner, operations, warehouse and finance roles have
write access; store-scoped users see their own store's data.
"""

from __future__ import annotations

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.documents import DocStatus
from outbound.models import (
    ReturnToVendor,
    StockAdjustment,
    StoreTransfer,
    VFlip,
    WriteOff,
)
from outbound.posting import (
    OutboundPostingError,
    post_adjustment,
    post_rtv,
    post_transfer_dispatch,
    post_transfer_receipt,
    post_vflip,
    post_writeoff,
)
from outbound.serializers import (
    ReturnToVendorReadSerializer,
    ReturnToVendorWriteSerializer,
    StockAdjustmentReadSerializer,
    StockAdjustmentWriteSerializer,
    StoreTransferReadSerializer,
    StoreTransferWriteSerializer,
    TransferReceiptInputSerializer,
    VFlipReadSerializer,
    VFlipWriteSerializer,
    WriteOffReadSerializer,
    WriteOffWriteSerializer,
)


# ---------------------------------------------------------------------------
# Transfer views
# ---------------------------------------------------------------------------

class TransferListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = StoreTransfer.objects.select_related(
            "source_store", "destination_store", "created_by"
        ).prefetch_related("lines")
        # Filter by transfer_type if provided
        ttype = self.request.query_params.get("type")
        if ttype:
            qs = qs.filter(transfer_type=ttype)
        # Filter by docstatus
        ds = self.request.query_params.get("docstatus")
        if ds is not None:
            qs = qs.filter(docstatus=int(ds))
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StoreTransferWriteSerializer
        return StoreTransferReadSerializer


class TransferDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StoreTransferReadSerializer

    def get_queryset(self):
        return StoreTransfer.objects.select_related(
            "source_store", "destination_store", "created_by"
        ).prefetch_related("lines")


class TransferDispatchView(APIView):
    """POST: Dispatch a draft transfer (stock exits source)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            transfer = StoreTransfer.objects.select_related(
                "source_store", "destination_store"
            ).prefetch_related("lines").get(pk=pk)
        except StoreTransfer.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        if transfer.docstatus != DocStatus.DRAFT:
            return Response(
                {"error": "Only drafts can be dispatched"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            post_transfer_dispatch(transfer, user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        transfer.refresh_from_db()
        return Response(StoreTransferReadSerializer(transfer).data)


class TransferReceiveView(APIView):
    """POST: Receive a dispatched transfer (stock enters destination)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            transfer = StoreTransfer.objects.select_related(
                "source_store", "destination_store"
            ).prefetch_related("lines").get(pk=pk)
        except StoreTransfer.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        if transfer.docstatus != DocStatus.SUBMITTED:
            return Response(
                {"error": "Only dispatched transfers can be received"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = TransferReceiptInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        received_quantities = {}
        for k, v in ser.validated_data.get("received_quantities", {}).items():
            received_quantities[int(k)] = v

        try:
            post_transfer_receipt(transfer, received_quantities, user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        transfer.refresh_from_db()
        return Response(StoreTransferReadSerializer(transfer).data)


# ---------------------------------------------------------------------------
# RTV views
# ---------------------------------------------------------------------------

class RTVListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

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


class RTVDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReturnToVendorReadSerializer

    def get_queryset(self):
        return ReturnToVendor.objects.select_related(
            "store", "vendor", "brand", "created_by"
        ).prefetch_related("lines")


class RTVSubmitView(APIView):
    """POST: Submit (post) a draft RTV — stock exits, GL posts."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            rtv = ReturnToVendor.objects.select_related(
                "store", "vendor", "brand"
            ).prefetch_related("lines").get(pk=pk)
        except ReturnToVendor.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

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
    permission_classes = [permissions.IsAuthenticated]

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


class AdjustmentDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StockAdjustmentReadSerializer

    def get_queryset(self):
        return StockAdjustment.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related("lines")


class AdjustmentSubmitView(APIView):
    """POST: Submit (post) a draft stock adjustment."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            adj = StockAdjustment.objects.select_related("store").prefetch_related("lines").get(pk=pk)
        except StockAdjustment.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

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
# Write-off views
# ---------------------------------------------------------------------------

class WriteOffListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = WriteOff.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related("lines")
        ds = self.request.query_params.get("docstatus")
        if ds is not None:
            qs = qs.filter(docstatus=int(ds))
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return WriteOffWriteSerializer
        return WriteOffReadSerializer


class WriteOffDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WriteOffReadSerializer

    def get_queryset(self):
        return WriteOff.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related("lines")


class WriteOffSubmitView(APIView):
    """POST: Submit (post) a draft write-off."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            wo = WriteOff.objects.select_related("store").prefetch_related("lines").get(pk=pk)
        except WriteOff.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

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
# V-flip views
# ---------------------------------------------------------------------------

class VFlipListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

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


class VFlipDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = VFlipReadSerializer

    def get_queryset(self):
        return VFlip.objects.select_related(
            "store", "original_brand", "authorized_by", "created_by"
        ).prefetch_related("lines")


class VFlipSubmitView(APIView):
    """POST: Submit (post) a draft V-flip."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            vflip = VFlip.objects.select_related(
                "store", "original_brand"
            ).prefetch_related("lines").get(pk=pk)
        except VFlip.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

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
