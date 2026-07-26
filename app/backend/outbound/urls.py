from __future__ import annotations

from django.urls import path

from outbound.models import StockAdjustment, TransferGapClosure, VFlip, WriteOff
from outbound.permissions import CanCloseTransferGap, CanFlipOwnership, CanWriteStockCount
from outbound.serializers import (
    GapClosureReadSerializer,
    StockAdjustmentReadSerializer,
    VFlipReadSerializer,
    WriteOffReadSerializer,
)
from outbound.views import (
    AdjustmentDetailView,
    AdjustmentListCreateView,
    AdjustmentSubmitView,
    CountLookupView,
    CountSessionCreateView,
    CountSessionScanView,
    CountSessionSubmitView,
    GapClosureDetailView,
    GapClosureSubmitView,
    MarkDamagedView,
    RequestApprovalView,
    RTVDetailView,
    RTVListCreateView,
    RTVSubmitView,
    ScanLookupView,
    StocktakeApplyView,
    StocktakeDetailView,
    StocktakeListCreateView,
    StocktakeVarianceView,
    TransferDetailView,
    TransferDispatchView,
    TransferGapClosureCreateView,
    TransferGapListView,
    TransferListCreateView,
    TransferPTCsvView,
    TransferPTView,
    TransferPTXlsxView,
    TransferReceiveView,
    VFlipDetailView,
    VFlipListCreateView,
    VFlipSubmitView,
    WriteOffDetailView,
    WriteOffListCreateView,
    WriteOffSubmitView,
)

urlpatterns = [
    # Store Transfers
    path("transfers", TransferListCreateView.as_view(), name="transfer-list"),
    # Before <int:pk> so "gaps" is read as the gaps list, not a transfer id.
    path("transfers/gaps", TransferGapListView.as_view(), name="transfer-gap-list"),
    path("transfers/<int:pk>", TransferDetailView.as_view(), name="transfer-detail"),
    path("transfers/<int:pk>/dispatch", TransferDispatchView.as_view(), name="transfer-dispatch"),
    path("transfers/<int:pk>/receive", TransferReceiveView.as_view(), name="transfer-receive"),
    # The PT that travels with the carton (#72) — read and download only.
    path("transfers/<int:pk>/pt", TransferPTView.as_view(), name="transfer-pt"),
    path("transfers/<int:pk>/pt.csv", TransferPTCsvView.as_view(), name="transfer-pt-csv"),
    path("transfers/<int:pk>/pt.xlsx", TransferPTXlsxView.as_view(), name="transfer-pt-xlsx"),
    path(
        "transfers/<int:pk>/gap-closure",
        TransferGapClosureCreateView.as_view(),
        name="transfer-gap-closure-create",
    ),
    # Gap closures (senior-gated, reason-coded — #71)
    path("gap-closures/<int:pk>", GapClosureDetailView.as_view(), name="gap-closure-detail"),
    path(
        "gap-closures/<int:pk>/submit",
        GapClosureSubmitView.as_view(),
        name="gap-closure-submit",
    ),
    path(
        "gap-closures/<int:pk>/request-approval",
        RequestApprovalView.as_view(
            model=TransferGapClosure,
            read_serializer=GapClosureReadSerializer,
            permission_classes=[CanCloseTransferGap],
        ),
        name="gap-closure-request-approval",
    ),
    path("scan-lookup", ScanLookupView.as_view(), name="scan-lookup"),
    # Mark damaged (global action → a flag, and on confirmation → quarantine)
    path("mark-damaged", MarkDamagedView.as_view(), name="mark-damaged"),
    # Returns to Vendor (RTV)
    path("rtvs", RTVListCreateView.as_view(), name="rtv-list"),
    path("rtvs/<int:pk>", RTVDetailView.as_view(), name="rtv-detail"),
    path("rtvs/<int:pk>/submit", RTVSubmitView.as_view(), name="rtv-submit"),
    # Stock counting — blind sessions merging into one variance report (#76)
    path("count-lookup", CountLookupView.as_view(), name="count-lookup"),
    path("stocktakes", StocktakeListCreateView.as_view(), name="stocktake-list"),
    path("stocktakes/<int:pk>", StocktakeDetailView.as_view(), name="stocktake-detail"),
    path(
        "stocktakes/<int:pk>/sessions",
        CountSessionCreateView.as_view(),
        name="stocktake-session-create",
    ),
    path(
        "stocktakes/<int:pk>/variance", StocktakeVarianceView.as_view(), name="stocktake-variance"
    ),
    path("stocktakes/<int:pk>/apply", StocktakeApplyView.as_view(), name="stocktake-apply"),
    path("count-sessions/<int:pk>/scan", CountSessionScanView.as_view(), name="count-session-scan"),
    path(
        "count-sessions/<int:pk>/submit",
        CountSessionSubmitView.as_view(),
        name="count-session-submit",
    ),
    # Stock Adjustments
    path("adjustments", AdjustmentListCreateView.as_view(), name="adjustment-list"),
    path("adjustments/<int:pk>", AdjustmentDetailView.as_view(), name="adjustment-detail"),
    path("adjustments/<int:pk>/submit", AdjustmentSubmitView.as_view(), name="adjustment-submit"),
    path(
        "adjustments/<int:pk>/request-approval",
        RequestApprovalView.as_view(
            model=StockAdjustment,
            read_serializer=StockAdjustmentReadSerializer,
            permission_classes=[CanWriteStockCount],
        ),
        name="adjustment-request-approval",
    ),
    # Write-offs
    path("writeoffs", WriteOffListCreateView.as_view(), name="writeoff-list"),
    path("writeoffs/<int:pk>", WriteOffDetailView.as_view(), name="writeoff-detail"),
    path("writeoffs/<int:pk>/submit", WriteOffSubmitView.as_view(), name="writeoff-submit"),
    path(
        "writeoffs/<int:pk>/request-approval",
        RequestApprovalView.as_view(
            model=WriteOff,
            read_serializer=WriteOffReadSerializer,
            permission_classes=[CanWriteStockCount],
        ),
        name="writeoff-request-approval",
    ),
    # V-flips
    path("vflips", VFlipListCreateView.as_view(), name="vflip-list"),
    path("vflips/<int:pk>", VFlipDetailView.as_view(), name="vflip-detail"),
    path("vflips/<int:pk>/submit", VFlipSubmitView.as_view(), name="vflip-submit"),
    path(
        "vflips/<int:pk>/request-approval",
        RequestApprovalView.as_view(
            model=VFlip,
            read_serializer=VFlipReadSerializer,
            permission_classes=[CanFlipOwnership],
        ),
        name="vflip-request-approval",
    ),
]
