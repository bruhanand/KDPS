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

import csv
import io
from typing import Any

import openpyxl
from django.http import HttpResponse
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.documents import DocStatus
from core.textsearch import search_term, text_filter
from outbound.counting import (
    CountError,
    MovedMidCountError,
    apply_variance,
    open_session,
    open_stocktake,
    record_scans,
    submit_session,
    variance_report,
)
from outbound.maker_checker import ask_again
from outbound.models import (
    CountSession,
    MarkDamaged,
    ReceiptStatus,
    ReturnToVendor,
    StockAdjustment,
    Stocktake,
    StoreTransfer,
    TransferGapClosure,
    TransferPT,
    VFlip,
    WriteOff,
)
from outbound.permissions import (
    CanCloseTransferGap,
    CanExecuteVFlip,
    CanFlipOwnership,
    CanReadTransferPT,
    CanWriteReturnToBrand,
    CanWriteStockCount,
    CanWriteTransfer,
    enforce_store_scope,
)
from outbound.posting import (
    OutboundPostingError,
    amend_gap_closure,
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
    ApplyVarianceInputSerializer,
    CountScanInputSerializer,
    CountSessionCreateSerializer,
    CountSessionReadSerializer,
    GapClosureInputSerializer,
    GapClosureReadSerializer,
    MarkDamagedInputSerializer,
    MarkDamagedReadSerializer,
    ReturnToVendorReadSerializer,
    ReturnToVendorWriteSerializer,
    StockAdjustmentReadSerializer,
    StockAdjustmentWriteSerializer,
    StocktakeCreateSerializer,
    StocktakeReadSerializer,
    StoreTransferReadSerializer,
    StoreTransferWriteSerializer,
    TransferPTSerializer,
    TransferReceiveInputSerializer,
    TransferScanInputSerializer,
    VFlipReadSerializer,
    VFlipWriteSerializer,
    WriteOffReadSerializer,
    WriteOffWriteSerializer,
)
from outbound.transfer_pt import KDPS_COLUMNS


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


#: What a typed term looks through on the Transfers screen — the voucher number,
#: and either end of the movement by code or by name (a store person says
#: "Deoghar", the document says "DEO").
TRANSFER_SEARCH_FIELDS = (
    "doc_number",
    "source_store__code",
    "source_store__name",
    "destination_store__code",
    "destination_store__name",
)


class TransferListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanWriteTransfer()]
        return [IsAuthenticated()]

    def get_queryset(self):
        # NOTE: this list is not store-scoped on read — only transfer *writes*
        # are (`enforce_store_scope`). The search below therefore narrows the
        # whole network's transfers rather than the caller's own. Search does not
        # widen anything (it is a filter on the same base set a store person can
        # already scroll), but the gate itself is missing: issue #141, which also
        # covers the detail endpoint below and the rest of outbound, and carries
        # the open question a fix has to answer first (a brand-scoped caller has
        # no store to gate on, and a transfer carries no brand).
        qs = StoreTransfer.objects.select_related(
            "source_store", "destination_store", "created_by"
        ).prefetch_related("lines")
        ttype = self.request.query_params.get("type")
        if ttype:
            qs = qs.filter(transfer_type=ttype)
        qs = _filter_docstatus(qs, self.request)
        return text_filter(qs, search_term(self.request), TRANSFER_SEARCH_FIELDS)

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
    — each list of ``{"barcode", "qty"}``. Everything that turned up moves
    in-transit → destination, broken pieces included, and a damage document is
    raised for those: quarantined on the spot if the receiver holds the
    confirming rung, otherwise flagged and left in stock (#138). Extras (not on
    the transfer) are accepted in with a flag; a short receive leaves the
    remainder in-transit and opens a gap. The notes reach the server and are
    stored.
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
# The transfer's PT — read, download, print (#72)
# ---------------------------------------------------------------------------


class TransferPTBaseView(APIView):
    """Everything the three PT endpoints share: find it, or say there is none.

    Read-only by construction. The PT is regenerated from the scanned lines or
    it does not change (#72), so there is no PUT, PATCH or POST on any of these;
    anything but GET is a 405.

    Gated on the transfer section's lowest rung, because the file is priced and
    people forward it. That is a *transfer* right and nothing else: no inbound-PT
    right is consulted here, so the rulings on who may make (#119) or inward
    (#124) a brand's PT cannot reach this document. Making a transfer's own
    packing list is part of transferring.
    """

    permission_classes = [CanReadTransferPT]

    #: File extension for the download views; the JSON view has none.
    extension = ""

    def get(self, request, pk):
        pt = (
            TransferPT.objects.select_related(
                "transfer__source_store", "transfer__destination_store"
            )
            .filter(transfer_id=pk)
            .first()
        )
        # A draft has scanned nothing, so it has no carton and no document —
        # that is a 404, not an empty file.
        if pt is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        return self.render(pt)

    def render(self, pt):  # pragma: no cover - overridden by every subclass
        raise NotImplementedError

    def rows_in_column_order(self, pt) -> list[list]:
        """The stored rows as plain lists, in the KDPS column order — the shape
        both file formats write."""
        return [[row.get(column, "") for column in KDPS_COLUMNS] for row in pt.rows]

    def as_attachment(self, resp, pt):
        """Name the download after the voucher, with the slashes a voucher series
        uses flattened out of the filename: ``KDPS-PT-PT-A-STO-26-27-0001.csv``."""
        stem = (pt.transfer.doc_number or f"transfer-{pt.transfer_id}").replace("/", "-")
        resp["Content-Disposition"] = f'attachment; filename="KDPS-PT-{stem}.{self.extension}"'
        return resp


class TransferPTView(TransferPTBaseView):
    """GET: the transfer's PT, whole — the shape the print screen renders."""

    def render(self, pt):
        return Response(TransferPTSerializer(pt).data)


class TransferPTCsvView(TransferPTBaseView):
    """GET: the PT as CSV, in KDPS column order."""

    extension = "csv"

    def render(self, pt):
        resp = HttpResponse(content_type="text/csv")
        writer = csv.writer(resp)
        writer.writerow(KDPS_COLUMNS)
        writer.writerows(self.rows_in_column_order(pt))
        return self.as_attachment(resp, pt)


class TransferPTXlsxView(TransferPTBaseView):
    """GET: the PT as a real .xlsx — the file a brand or a store opens."""

    extension = "xlsx"

    def render(self, pt):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "KDPS PT"
        ws.append(KDPS_COLUMNS)
        for row in self.rows_in_column_order(pt):
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        resp = HttpResponse(
            buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return self.as_attachment(resp, pt)


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
    #: Reading a closure is open like outbound's other reads; correcting one is a
    #: write, and carries the same senior gate as raising and posting it.
    permission_classes = [IsAuthenticated]
    serializer_class = GapClosureReadSerializer

    def get_permissions(self):
        return [CanCloseTransferGap()] if self.request.method == "PATCH" else [IsAuthenticated()]

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

    def patch(self, request, *args, **kwargs):
        """Correct a draft closure — a new reason, a new note, lines re-read.

        The way back from a rejection or a stale draft, so one wrong reason code
        cannot strand the pieces in transit for good.
        """
        closure = self.get_object()
        enforce_store_scope(request.user, closure.store_id)

        ser = GapClosureInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            amend_gap_closure(
                closure,
                reason=ser.validated_data["reason"],
                note=ser.validated_data["note"],
                user=request.user,
            )
        except OutboundPostingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(GapClosureReadSerializer(_gap_closure_for_read(closure.pk)).data)


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

        # No draft check here: ``post_gap_closure`` makes it, and a second copy
        # would only be a second place for the two to disagree.
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
# Mark damaged (global action → a flag, and on confirmation → quarantine)
# ---------------------------------------------------------------------------


class MarkDamagedView(generics.ListCreateAPIView):
    """GET: list mark-damaged documents — ``?docstatus=0`` for the reports still
    waiting on someone. POST: the global mark-damaged action — create a DMG
    document from scanned pieces.

    Whether that document *posts* depends on who is asking (#138). A store
    person is reporting damage: it stays a draft in the approvals inbox and the
    pieces stay sellable until a warehouse or HO person confirms it. Someone who
    holds the confirming rung reports and confirms in the one call, so the pieces
    move from free-to-sell into quarantine here. ``flag_status`` on the response
    says which happened.

    Any outbound writer (including store-level roles) may mark damaged from any
    stock view — damage is caught everywhere. store_staff is read-only.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanWriteReturnToBrand()]
        return [IsAuthenticated()]

    def get_queryset(self):
        from masters.scoping import scope_by_store

        qs = MarkDamaged.objects.select_related(
            "store", "created_by", "confirmed_by"
        ).prefetch_related(
            "lines", "approvals__made_by", "approvals__requested_by", "approvals__decided_by"
        )
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

    permission_classes = [CanExecuteVFlip]

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


# ---------------------------------------------------------------------------
# Stock counting — blind sessions, the merged variance, its correction (#76)
# ---------------------------------------------------------------------------


def _stocktakes(user: Any) -> Any:
    """Counts this user may see — scoped at the queryset, fail-closed (ADR-0003).

    Scope belongs here rather than on each view because a count carries per-line
    cost and value: a store-scoped person reading another store's variance would
    read that location's book cost, which is the one thing #76's "value is shown
    to the person counting **their own** location" rule withholds. Out of scope
    is therefore indistinguishable from not existing.
    """
    from masters.scoping import scope_by_store

    qs = Stocktake.objects.select_related("store", "opened_by", "adjustment").prefetch_related(
        "sessions__lines", "sessions__counted_by"
    )
    return scope_by_store(qs, user, "store_id")


def _load_stocktake(pk: int, user: Any) -> Stocktake:
    return _stocktakes(user).get(pk=pk)


class StocktakeListCreateView(APIView):
    """GET: counts at the stores this user can see. POST: open a new one."""

    def get_permissions(self):
        return [CanWriteStockCount()] if self.request.method == "POST" else [IsAuthenticated()]

    def get(self, request):
        return Response(StocktakeReadSerializer(_stocktakes(request.user), many=True).data)

    def post(self, request):
        ser = StocktakeCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        store = ser.validated_data["store"]
        enforce_store_scope(request.user, store.id)
        stocktake = open_stocktake(store, user=request.user, note=ser.validated_data["note"])
        return Response(
            StocktakeReadSerializer(_load_stocktake(stocktake.pk, request.user)).data,
            status=status.HTTP_201_CREATED,
        )


class StocktakeDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            return Response(StocktakeReadSerializer(_load_stocktake(pk, request.user)).data)
        except Stocktake.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)


class CountSessionCreateView(APIView):
    """POST: add one counter's scoped pass to an open count."""

    permission_classes = [CanWriteStockCount]

    def post(self, request, pk):
        try:
            stocktake = Stocktake.objects.select_related("store").get(pk=pk)
        except Stocktake.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        enforce_store_scope(request.user, stocktake.store_id)

        ser = CountSessionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            session = open_session(
                stocktake,
                scope=ser.validated_data["scope"],
                scope_value=ser.validated_data["scope_value"],
                user=request.user,
            )
        except CountError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CountSessionReadSerializer(session).data, status=status.HTTP_201_CREATED)


class CountLookupView(APIView):
    """GET ?store=&barcode= — what a scanned piece *is*, during a blind count.

    Deliberately not ``ScanLookupView``: that one answers with the location's
    available quantity, which is the very number a blind count may not show, and
    it 404s on a piece the books hold none of — which in a count is not a wrong
    piece at all but the surplus the count exists to find. So this returns dims
    only, and finds the piece in the SKU master when the location holds none.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from outbound.counting import identity_dims

        store_id = request.query_params.get("store")
        barcode = (request.query_params.get("barcode") or "").strip()
        if not store_id or not barcode:
            return Response(
                {"error": "Pass store= and barcode="}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            enforce_store_scope(request.user, int(store_id))
        except ValueError:
            return Response({"error": "store must be an id"}, status=status.HTTP_400_BAD_REQUEST)

        dims = identity_dims(int(store_id), barcode)
        if not any(dims.values()):
            return Response(
                {"error": f"{barcode} is not a piece this system knows."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"barcode": barcode, **dims})


class CountSessionScanView(APIView):
    """POST: record scanned pieces on an open session.

    The response is the session as it stands — counted pieces only. No book
    quantity exists to return yet, which is what makes the count blind (#76).
    """

    permission_classes = [CanWriteStockCount]

    def post(self, request, pk):
        session = _load_session(pk)
        if session is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        enforce_store_scope(request.user, session.stocktake.store_id)

        ser = CountScanInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            record_scans(session, ser.scans_by_barcode())
        except CountError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CountSessionReadSerializer(_load_session(pk)).data)


class CountSessionSubmitView(APIView):
    """POST: close a session and take its book snapshot."""

    permission_classes = [CanWriteStockCount]

    def post(self, request, pk):
        session = _load_session(pk)
        if session is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        enforce_store_scope(request.user, session.stocktake.store_id)

        try:
            submit_session(session)
        except CountError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CountSessionReadSerializer(_load_session(pk)).data)


def _load_session(pk: int) -> CountSession | None:
    return (
        CountSession.objects.select_related("stocktake__store", "counted_by")
        .prefetch_related("lines")
        .filter(pk=pk)
        .first()
    )


class StocktakeVarianceView(APIView):
    """GET: book against counted for the whole count, in pieces and in value.

    Value is not masked. Whoever counted is counting their own location's stock
    and can already read the PT that carries the rate, so withholding the number
    only stops them sizing their own problem (#76).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            stocktake = _load_stocktake(pk, request.user)
        except Stocktake.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        lines = [v.as_dict() for v in variance_report(stocktake)]
        return Response(
            {
                "stocktake": pk,
                "store_code": stocktake.store.code,
                "status": stocktake.status,
                "lines": lines,
                "net_pieces": sum(v["adj_qty"] for v in lines),
                "net_variance_paise": sum(v["variance_paise"] for v in lines),
                "unpriced": [v["sku_code"] for v in lines if not v["cost_known"] and v["adj_qty"]],
            }
        )


class StocktakeApplyView(APIView):
    """POST: apply the variance as one stock adjustment.

    409 when stock moved between the count and now, naming the lines: the person
    deciding confirms those barcodes and posts again. Never a blind overwrite.
    """

    permission_classes = [CanWriteStockCount]

    def post(self, request, pk):
        try:
            stocktake = _load_stocktake(pk, request.user)
        except Stocktake.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        enforce_store_scope(request.user, stocktake.store_id)

        ser = ApplyVarianceInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            adjustment = apply_variance(
                stocktake,
                user=request.user,
                confirm_skus=frozenset(ser.validated_data["confirm"]),
            )
        except MovedMidCountError as e:
            return Response(
                {"error": str(e), "moved": [v.as_dict() for v in e.lines]},
                status=status.HTTP_409_CONFLICT,
            )
        except (CountError, OutboundPostingError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            StockAdjustmentReadSerializer(adjustment).data, status=status.HTTP_201_CREATED
        )
