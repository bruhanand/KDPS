"""Routes for the counter (mounted at `/api/sell/`).

`doc_number` is matched with `<path:...>` because the Tally join key carries
slashes — `26-27/DEO/SAL/74` is one identifier, not four segments.
"""

from __future__ import annotations

from django.urls import path

from sell.views import SaleDetailView, SaleListCreateView

urlpatterns = [
    path("sales", SaleListCreateView.as_view(), name="sale-list"),
    path("sales/<path:doc_number>", SaleDetailView.as_view(), name="sale-detail"),
]
