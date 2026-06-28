from __future__ import annotations

from django.urls import path

from stockledger.views import StockLedgerListView, StockLedgerSummaryView, StockOnHandView

urlpatterns = [
    path("entries", StockLedgerListView.as_view(), name="stock-entries"),
    path("summary", StockLedgerSummaryView.as_view(), name="stock-summary"),
    path("on-hand", StockOnHandView.as_view(), name="stock-on-hand"),
]
