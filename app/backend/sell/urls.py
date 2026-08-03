"""Routes for the counter (mounted at `/api/sell/`).

`doc_number` is matched with `<path:...>` because the Tally join key carries
slashes - `26-27/DEO/SAL/74` is one identifier, not four segments.
"""

from __future__ import annotations

from django.urls import path

from sell.discount_views import DiscountReportView
from sell.views import (
    DatasetView,
    HeldBillsView,
    IrnQueueItemView,
    IrnQueueView,
    RegisterHandoverView,
    RegisterView,
    SaleDetailView,
    SaleListCreateView,
    SellPolicyView,
    StoreFlagsView,
    StoreFlagView,
)

urlpatterns = [
    path("policy", SellPolicyView.as_view(), name="sell-policy"),
    path("dataset", DatasetView.as_view(), name="sell-dataset"),
    path("register/handover", RegisterHandoverView.as_view(), name="sell-register-handover"),
    path("register", RegisterView.as_view(), name="sell-register"),
    path("held-bills", HeldBillsView.as_view(), name="sell-held-bills"),
    path("flags", StoreFlagsView.as_view(), name="sell-flags"),
    path("flags/<int:pk>", StoreFlagView.as_view(), name="sell-flag"),
    path("irn-queue", IrnQueueView.as_view(), name="sell-irn-queue"),
    path("irn-queue/<int:pk>", IrnQueueItemView.as_view(), name="sell-irn-queue-item"),
    # What the chain gave away, and what it forgot to give (D11 §5, §8). Read
    # off bills, so it lives here; gated on `offers_price`, because that is the
    # screen it answers.
    path("discounts", DiscountReportView.as_view(), name="discount-report"),
    path("sales", SaleListCreateView.as_view(), name="sale-list"),
    path("sales/<path:doc_number>", SaleDetailView.as_view(), name="sale-detail"),
]
