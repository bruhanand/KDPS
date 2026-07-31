"""Routes for the counter (mounted at `/api/sell/`).

`doc_number` is matched with `<path:...>` because the Tally join key carries
slashes - `26-27/DEO/SAL/74` is one identifier, not four segments.
"""

from __future__ import annotations

from django.urls import path

from sell.views import (
    DatasetView,
    HeldBillsView,
    IrnQueueItemView,
    IrnQueueView,
    RegisterHandoverView,
    RegisterView,
    SaleDetailView,
    SaleListCreateView,
)

urlpatterns = [
    path("dataset", DatasetView.as_view(), name="sell-dataset"),
    path("register/handover", RegisterHandoverView.as_view(), name="sell-register-handover"),
    path("register", RegisterView.as_view(), name="sell-register"),
    path("held-bills", HeldBillsView.as_view(), name="sell-held-bills"),
    path("irn-queue", IrnQueueView.as_view(), name="sell-irn-queue"),
    path("irn-queue/<int:pk>", IrnQueueItemView.as_view(), name="sell-irn-queue-item"),
    path("sales", SaleListCreateView.as_view(), name="sale-list"),
    path("sales/<path:doc_number>", SaleDetailView.as_view(), name="sale-detail"),
]
