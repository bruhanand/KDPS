from __future__ import annotations

from django.urls import path

from storefront.views import CashSummaryView, DashboardView

urlpatterns = [
    path("dashboard", DashboardView.as_view(), name="store-dashboard"),
    path("cash-summary", CashSummaryView.as_view(), name="store-cash-summary"),
]
