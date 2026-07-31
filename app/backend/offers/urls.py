"""Routes for the rulebook (mounted at `/api/offers/`)."""

from __future__ import annotations

from django.urls import path

from offers.views import OfferDetailView, OfferListCreateView

urlpatterns = [
    path("", OfferListCreateView.as_view(), name="offer-list"),
    path("<int:pk>", OfferDetailView.as_view(), name="offer-detail"),
]
