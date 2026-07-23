from __future__ import annotations

from django.urls import path

from stockledger.views import (
    InTransitView,
    QuarantineView,
    StockLedgerListView,
    StockLedgerSummaryView,
    StockOnHandView,
)

urlpatterns = [
    path("entries", StockLedgerListView.as_view(), name="stock-entries"),
    path("summary", StockLedgerSummaryView.as_view(), name="stock-summary"),
    path("on-hand", StockOnHandView.as_view(), name="stock-on-hand"),
    path("in-transit", InTransitView.as_view(), name="stock-in-transit"),
    path("quarantine", QuarantineView.as_view(), name="stock-quarantine"),
]
