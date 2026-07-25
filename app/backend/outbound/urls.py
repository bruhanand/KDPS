from __future__ import annotations

from django.urls import path

from outbound.models import StockAdjustment, TransferGapClosure, VFlip, WriteOff
from outbound.permissions import IsOutboundAdmin, IsOutboundWriter
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
    GapClosureDetailView,
    GapClosureSubmitView,
    MarkDamagedView,
    RequestApprovalView,
    RTVDetailView,
    RTVListCreateView,
    RTVSubmitView,
    ScanLookupView,
    TransferDetailView,
    TransferDispatchView,
    TransferGapClosureCreateView,
    TransferGapListView,
    TransferListCreateView,
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
            permission_classes=[IsOutboundAdmin],
        ),
        name="gap-closure-request-approval",
    ),
    path("scan-lookup", ScanLookupView.as_view(), name="scan-lookup"),
    # Mark damaged (global action → quarantine)
    path("mark-damaged", MarkDamagedView.as_view(), name="mark-damaged"),
    # Returns to Vendor (RTV)
    path("rtvs", RTVListCreateView.as_view(), name="rtv-list"),
    path("rtvs/<int:pk>", RTVDetailView.as_view(), name="rtv-detail"),
    path("rtvs/<int:pk>/submit", RTVSubmitView.as_view(), name="rtv-submit"),
    # Stock Adjustments
    path("adjustments", AdjustmentListCreateView.as_view(), name="adjustment-list"),
    path("adjustments/<int:pk>", AdjustmentDetailView.as_view(), name="adjustment-detail"),
    path("adjustments/<int:pk>/submit", AdjustmentSubmitView.as_view(), name="adjustment-submit"),
    path(
        "adjustments/<int:pk>/request-approval",
        RequestApprovalView.as_view(
            model=StockAdjustment,
            read_serializer=StockAdjustmentReadSerializer,
            permission_classes=[IsOutboundWriter],
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
            permission_classes=[IsOutboundAdmin],
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
            permission_classes=[IsOutboundAdmin],
        ),
        name="vflip-request-approval",
    ),
]
