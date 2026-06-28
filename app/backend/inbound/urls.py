from __future__ import annotations

from django.urls import path

from inbound.views import (
    GrnDetailView,
    GrnListCreateView,
    InvoiceDraftView,
    PendingBookingsView,
)

urlpatterns = [
    path("pending", PendingBookingsView.as_view(), name="inbound-pending"),
    path("invoice-draft", InvoiceDraftView.as_view(), name="inbound-invoice-draft"),
    path("grns", GrnListCreateView.as_view(), name="grn-list"),
    path("grns/<int:pk>", GrnDetailView.as_view(), name="grn-detail"),
]
