from __future__ import annotations

from django.urls import path

from outbound.views import (
    AdjustmentDetailView,
    AdjustmentListCreateView,
    AdjustmentSubmitView,
    RTVDetailView,
    RTVListCreateView,
    RTVSubmitView,
    TransferDetailView,
    TransferDispatchView,
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
    path("transfers/<int:pk>", TransferDetailView.as_view(), name="transfer-detail"),
    path("transfers/<int:pk>/dispatch", TransferDispatchView.as_view(), name="transfer-dispatch"),
    path("transfers/<int:pk>/receive", TransferReceiveView.as_view(), name="transfer-receive"),
    # Returns to Vendor (RTV)
    path("rtvs", RTVListCreateView.as_view(), name="rtv-list"),
    path("rtvs/<int:pk>", RTVDetailView.as_view(), name="rtv-detail"),
    path("rtvs/<int:pk>/submit", RTVSubmitView.as_view(), name="rtv-submit"),
    # Stock Adjustments
    path("adjustments", AdjustmentListCreateView.as_view(), name="adjustment-list"),
    path("adjustments/<int:pk>", AdjustmentDetailView.as_view(), name="adjustment-detail"),
    path("adjustments/<int:pk>/submit", AdjustmentSubmitView.as_view(), name="adjustment-submit"),
    # Write-offs
    path("writeoffs", WriteOffListCreateView.as_view(), name="writeoff-list"),
    path("writeoffs/<int:pk>", WriteOffDetailView.as_view(), name="writeoff-detail"),
    path("writeoffs/<int:pk>/submit", WriteOffSubmitView.as_view(), name="writeoff-submit"),
    # V-flips
    path("vflips", VFlipListCreateView.as_view(), name="vflip-list"),
    path("vflips/<int:pk>", VFlipDetailView.as_view(), name="vflip-detail"),
    path("vflips/<int:pk>/submit", VFlipSubmitView.as_view(), name="vflip-submit"),
]
