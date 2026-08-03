"""Routes for the rulebook (mounted at `/api/offers/`)."""

from __future__ import annotations

from django.urls import path

from offers.eoss_views import (
    EossConfigView,
    EossRecommendationDecisionView,
    EossRecommendationListView,
)
from offers.views import OfferDetailView, OfferListCreateView

urlpatterns = [
    path("", OfferListCreateView.as_view(), name="offer-list"),
    path("<int:pk>", OfferDetailView.as_view(), name="offer-detail"),
    path("eoss/recommendations", EossRecommendationListView.as_view(), name="eoss-reco-list"),
    path(
        "eoss/recommendations/<int:pk>/decide",
        EossRecommendationDecisionView.as_view(),
        name="eoss-reco-decide",
    ),
    path("eoss/config", EossConfigView.as_view(), name="eoss-config"),
]
