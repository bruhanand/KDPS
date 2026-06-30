from __future__ import annotations

from django.urls import path

from finledger.health import BooksHealthView
from finledger.views import (
    CashEntriesView,
    CashMovementView,
    CashReverseView,
    CashSummaryView,
    VendorAgeingView,
    VendorBalancesView,
    VendorBillView,
    VendorEntriesView,
    VendorPaymentView,
    VendorReverseView,
)

urlpatterns = [
    path("vendor/entries", VendorEntriesView.as_view(), name="vendor-entries"),
    path("vendor/balances", VendorBalancesView.as_view(), name="vendor-balances"),
    path("vendor/ageing", VendorAgeingView.as_view(), name="vendor-ageing"),
    path("vendor/bill", VendorBillView.as_view(), name="vendor-bill"),
    path("vendor/payment", VendorPaymentView.as_view(), name="vendor-payment"),
    path("vendor/entries/<int:pk>/reverse", VendorReverseView.as_view(), name="vendor-reverse"),
    path("cash/entries", CashEntriesView.as_view(), name="cash-entries"),
    path("cash/summary", CashSummaryView.as_view(), name="cash-summary"),
    path("cash/movement", CashMovementView.as_view(), name="cash-movement"),
    path("cash/entries/<int:pk>/reverse", CashReverseView.as_view(), name="cash-reverse"),
    path("health", BooksHealthView.as_view(), name="books-health"),
]
