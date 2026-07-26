"""Outbound API views — list, create, dispatch, receive, submit.

Every endpoint requires authentication. RBAC:
  - Read (GET list/detail): any authenticated user (store scoping via queryset)
  - Write (POST create/submit/dispatch/receive): the endpoint group's section
    gate — see the table in ``outbound.permissions``, which is the one place
    the mapping lives
  - Store-scoped roles: may only write against their assigned stores
    (enforced via ``enforce_store_scope`` on every write path)
"""

from __future__ import annotations

from typing import Any

from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.documents import DocStatus
from outbound.maker_checker import ask_again
from outbound.models import (
    MarkDamaged,
    ReceiptStatus,
    ReturnToVendor,
    StockAdjustment,
    StoreTransfer,
    TransferGapClosure,
    VFlip,
    WriteOff,
)
from outbound.permissions import (
    CanCloseTransferGap,
    CanFlipOwnership,
    CanWriteReturnToBrand,
    CanWriteStockCount,
    CanWriteTransfer,
    enforce_store_scope,
)
from outbound.posting import (
    OutboundPostingError,
    mark_damaged,
    post_adjustment,
    post_gap_closure,
    post_rtv,
    post_transfer_dispatch,
    post_transfer_receipt,
    post_vflip,
    post_writeoff,
    raise_gap_closure,
)
from outbound.serializers import (
    GapClosureInputSerializer,
    GapClosureReadSerializer,
    MarkDamagedInputSerializer,
    MarkDamagedReadSerializer,
    ReturnToVendorReadSerializer,
    ReturnToVendorWriteSerializer,
    StockAdjustmentReadSerializer,
    StockAdjustmentWriteSerializer,
    StoreTransferReadSerializer,
    StoreTransferWriteSerializer,
    TransferReceiveInputSerializer,
    TransferScanInputSerializer,
    VFlipReadSerializer,
    VFlipWriteSerializer,
    WriteOffReadSerializer,
    WriteOffWriteSerializer,
)


def _filter_docstatus(qs, request):
    """Apply the optional ``?docstatus=`` filter to a list queryset.

    A non-integer value is a client error, not a server one — return a
    controlled 400 instead of letting ``int()`` raise an uncaught 500.
    """
    ds = request.query_params.get("docstatus")
    if ds is None:
        return qs
    try:
        code = int(ds)
    except (TypeError, ValueError):
        raise ValidationError({"docstatus": "must be an integer"}) from None
    return qs.filter(docstatus=code)


# ---------------------------------------------------------------------------
# Transfer views
# ---------------------------------------------------------------------------


class TransferListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanWriteTransfer()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = StoreTransfer.objects.select_related(
            "source_store", "destination_store", "created_by"
        ).prefetch_related("lines")
        ttype = self.request.query_params.get("type")
        if ttype:
            qs = qs.filter(transfer_type=ttype)
        qs = _filter_docstatus(qs, self.request)
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
    permission_classes = [IsAuthenticated]
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

    permission_classes = [CanWriteTransfer]

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
    """POST: Receive a dispatched transfer from scanned lines only (#68, #71).

    Payload: ``{"scans": [...], "damaged": [...], "extras": [...], "notes": ""}``
    — each list of ``{"barcode", "qty"}``. Intact pieces move in-transit →
    destination; damaged ones go in-transit → quarantine; extras (not on the
    transfer) are accepted in with a flag; a short receive leaves the remainder
    in-transit and opens a gap. The notes reach the server and are stored.
    """

    permission_classes = [CanWriteTransfer]

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

        ser = TransferReceiveInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            post_transfer_receipt(
                transfer,
                ser.scans_by_barcode(),
                user=request.user,
                damaged=ser.damaged_by_barcode(),
                extras=ser.extras_by_barcode(),
                notes=ser.validated_data["notes"],
            )
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(StoreTransferReadSerializer(_transfer_for_read(pk)).data)


# ---------------------------------------------------------------------------
# Gaps — transfers where sent ≠ received (#71)
# ---------------------------------------------------------------------------


def _transfer_for_read(pk):
    """Re-read a transfer with everything the read shape joins on.

    Re-read rather than ``refresh_from_db``: the response carries the fresh
    receipt, its exceptions and the gap closure, and a refreshed instance keeps
    the stale prefetch caches from before the post.
    """
    return (
        StoreTransfer.objects.select_related("source_store", "destination_store", "created_by")
        .prefetch_related("lines", "receipt__exceptions", "gap_closure__lines")
        .get(pk=pk)
    )


def _open_gap_transfers():
    """Every transfer where what was sent and what was received do not agree,
    and nobody has yet said why.

    A shortfall receipt is the flag; the absence of a *posted* closure is what
    keeps it on the list. A transfer merely on the road is not a gap — it is
    in transit, which the in-transit view already reports.
    """
    return (
        StoreTransfer.objects.filter(
            docstatus=DocStatus.SUBMITTED,
            receipt__receipt_status=ReceiptStatus.SHORTFALL,
        )
        .exclude(gap_closure__docstatus=DocStatus.SUBMITTED)
        .select_related("source_store", "destination_store", "created_by")
        .prefetch_related("lines", "receipt__exceptions", "gap_closure__lines")
    )


class TransferGapListView(generics.ListAPIView):
    """GET: the gaps list — every open gap, for the warehouse/HO screen.

    Scoped on the *source* store: the sender is answerable for the pieces until
    the receiver scans them in, so a gap is the sender's to explain. That also
    means the receiving store does not find its own gap on this list.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = StoreTransferReadSerializer
    pagination_class = None

    def get_queryset(self):
        from masters.scoping import scope_by_store

        return scope_by_store(_open_gap_transfers(), self.request.user, "source_store_id")


class TransferGapClosureCreateView(APIView):
    """POST: raise the closure for a transfer's gap — reason + optional note.

    Creating it does not close anything: the draft goes straight into the
    approvals inbox, and only a senior's approval lets it post. The lines are
    read off the transfer's in-transit remainder, so the person raising it
    cannot restate how much went missing.
    """

    permission_classes = [CanCloseTransferGap]

    def post(self, request, pk):
        try:
            transfer = _transfer_for_read(pk)
        except StoreTransfer.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        # The gap belongs to the sender, so this is a write against the sender's
        # store; the receiving store's own bar is in ``_refuse_self_closure``.
        enforce_store_scope(request.user, transfer.source_store_id)

        ser = GapClosureInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            closure = raise_gap_closure(
                transfer,
                reason=ser.validated_data["reason"],
                note=ser.validated_data["note"],
                user=request.user,
            )
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            GapClosureReadSerializer(_gap_closure_for_read(closure.pk)).data,
            status=status.HTTP_201_CREATED,
        )


def _gap_closure_for_read(pk):
    return (
        TransferGapClosure.objects.select_related(
            "store",
            "created_by",
            "approved_by",
            "transfer__source_store",
            "transfer__destination_store",
        )
        .prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )
        .get(pk=pk)
    )


class GapClosureDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = GapClosureReadSerializer

    def get_queryset(self):
        return TransferGapClosure.objects.select_related(
            "store",
            "created_by",
            "approved_by",
            "transfer__source_store",
            "transfer__destination_store",
        ).prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )


class GapClosureSubmitView(APIView):
    """POST: post an approved gap closure — the resolving entries land here.

    The rules that matter (approved by a second, senior person; never anybody
    entitled to the receiving store; the bucket still holds what the draft says)
    all live in ``posting.post_gap_closure``, so a shell or a management command
    hits the same wall this endpoint does.
    """

    permission_classes = [CanCloseTransferGap]

    def post(self, request, pk):
        try:
            closure = _gap_closure_for_read(pk)
        except TransferGapClosure.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        enforce_store_scope(request.user, closure.store_id)

        if closure.docstatus != DocStatus.DRAFT:
            return Response(
                {"error": "Only drafts can be submitted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            post_gap_closure(closure, user=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(GapClosureReadSerializer(_gap_closure_for_read(pk)).data)


class ScanLookupView(APIView):
    """GET ?store=&barcode= — per-scan validation for the scan screen.

    Returns the piece's identity + available qty at the location (for the
    right-piece beep and scan-to-build), 404 when the location holds no such
    stock (the wrong-piece beep).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from masters.scoping import scope_by_entitlement
        from stockledger.models import StockOnHand, merch_dims

        store_id = request.query_params.get("store")
        barcode = (request.query_params.get("barcode") or "").strip()
        if not store_id or not barcode:
            return Response(
                {"error": "Pass store= and barcode="}, status=status.HTTP_400_BAD_REQUEST
            )

        # Fail-closed (ADR-0003): a store-scoped user can only probe stock at
        # their own stores — an out-of-scope store looks identical to no stock.
        # Scoped by entitlement, not by the switcher: the scan screen names the
        # store it is standing in, so the top bar must not veto scanning there.
        visible = scope_by_entitlement(StockOnHand.objects.all(), request.user, "store_id")
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
            return [CanWriteReturnToBrand()]
        return [IsAuthenticated()]

    def get_queryset(self):
        from masters.scoping import scope_by_store

        qs = MarkDamaged.objects.select_related("store", "created_by").prefetch_related("lines")
        qs = _filter_docstatus(qs, self.request)
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
            return [CanWriteReturnToBrand()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = ReturnToVendor.objects.select_related(
            "store", "vendor", "brand", "created_by"
        ).prefetch_related("lines")
        qs = _filter_docstatus(qs, self.request)
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
    permission_classes = [IsAuthenticated]
    serializer_class = ReturnToVendorReadSerializer

    def get_queryset(self):
        return ReturnToVendor.objects.select_related(
            "store", "vendor", "brand", "created_by"
        ).prefetch_related("lines")


class RTVSubmitView(APIView):
    """POST: Submit (post) a draft RTV — stock exits, GL posts."""

    permission_classes = [CanWriteReturnToBrand]

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
            return [CanWriteStockCount()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = StockAdjustment.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )
        qs = _filter_docstatus(qs, self.request)
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
    permission_classes = [IsAuthenticated]
    serializer_class = StockAdjustmentReadSerializer

    def get_queryset(self):
        return StockAdjustment.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )


class AdjustmentSubmitView(APIView):
    """POST: Submit (post) a draft stock adjustment."""

    permission_classes = [CanWriteStockCount]

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
            return [CanWriteStockCount()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = WriteOff.objects.select_related("store", "approved_by", "created_by").prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )
        qs = _filter_docstatus(qs, self.request)
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
    permission_classes = [IsAuthenticated]
    serializer_class = WriteOffReadSerializer

    def get_queryset(self):
        return WriteOff.objects.select_related(
            "store", "approved_by", "created_by"
        ).prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )


class WriteOffSubmitView(APIView):
    """POST: Submit (post) a draft write-off."""

    permission_classes = [CanWriteStockCount]

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
            return [CanFlipOwnership()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = VFlip.objects.select_related(
            "store", "original_brand", "authorized_by", "created_by"
        ).prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )
        qs = _filter_docstatus(qs, self.request)
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
    permission_classes = [IsAuthenticated]
    serializer_class = VFlipReadSerializer

    def get_queryset(self):
        return VFlip.objects.select_related(
            "store", "original_brand", "authorized_by", "created_by"
        ).prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )


class VFlipSubmitView(APIView):
    """POST: Submit (post) a draft V-flip."""

    permission_classes = [CanFlipOwnership]

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


# ---------------------------------------------------------------------------
# Ask again after a rejection (#70)
# ---------------------------------------------------------------------------


class RequestApprovalView(APIView):
    """POST: send a rejected draft back for approval.

    One view for all three wired families — the only thing that differs is
    which model to load and who may ask, both supplied by the URL conf. The
    rules (draft only, rejected only, and who stays the maker) live in
    ``maker_checker.ask_again``, not here.
    """

    model: Any = None
    read_serializer: Any = None

    def _load(self, pk):
        return (
            self.model.objects.select_related("store", "created_by")
            .prefetch_related(
                "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
            )
            .get(pk=pk)
        )

    def post(self, request, pk):
        try:
            doc = self._load(pk)
        except self.model.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        enforce_store_scope(request.user, doc.store_id)

        try:
            ask_again(doc, requested_by=request.user)
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Re-read rather than refresh: the fresh approval must come back with
        # its people already joined, or the response N+1s on names.
        doc = self._load(pk)
        return Response(self.read_serializer(doc).data)
