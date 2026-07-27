from __future__ import annotations

from django.urls import path

from masters.views import (
    BrandDetailView,
    BrandListView,
    GstinDetailView,
    GstinListView,
    LegalEntityListView,
    LocationListView,
    SeasonDetailView,
    SeasonListView,
    SkuLookupView,
    StoreDetailView,
    StoreListView,
    SummaryView,
)

urlpatterns = [
    path("skus/lookup", SkuLookupView.as_view(), name="sku-lookup"),
    path("stores", StoreListView.as_view(), name="store-list"),
    path("stores/<int:pk>", StoreDetailView.as_view(), name="store-detail"),
    path("locations", LocationListView.as_view(), name="location-list"),
    path("brands", BrandListView.as_view(), name="brand-list"),
    path("brands/<int:pk>", BrandDetailView.as_view(), name="brand-detail"),
    path("seasons", SeasonListView.as_view(), name="season-list"),
    path("seasons/<int:pk>", SeasonDetailView.as_view(), name="season-detail"),
    path("gstins", GstinListView.as_view(), name="gstin-list"),
    path("gstins/<int:pk>", GstinDetailView.as_view(), name="gstin-detail"),
    path("entities", LegalEntityListView.as_view(), name="entity-list"),
    path("summary", SummaryView.as_view(), name="masters-summary"),
]
