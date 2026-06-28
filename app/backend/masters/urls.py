from __future__ import annotations

from django.urls import path

from masters.views import (
    BrandListView,
    GstinListView,
    LegalEntityListView,
    SeasonListView,
    StoreListView,
    SummaryView,
)

urlpatterns = [
    path("stores", StoreListView.as_view(), name="store-list"),
    path("brands", BrandListView.as_view(), name="brand-list"),
    path("seasons", SeasonListView.as_view(), name="season-list"),
    path("gstins", GstinListView.as_view(), name="gstin-list"),
    path("entities", LegalEntityListView.as_view(), name="entity-list"),
    path("summary", SummaryView.as_view(), name="masters-summary"),
]
