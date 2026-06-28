"""Read-only master-data API for the foundation: the scoped store list that
feeds the store/GSTIN context switcher, the brand/season/GSTIN registries, and a
small counts summary for the role dashboards. Full CRUD/stewardship screens
arrive with the D8 slice; the Django admin covers editing in the meantime.
"""

from __future__ import annotations

from typing import Any

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from masters.models import Brand, Gstin, LegalEntity, Season, Store
from masters.scoping import scoped_stores
from masters.serializers import (
    BrandSerializer,
    GstinSerializer,
    LegalEntitySerializer,
    SeasonSerializer,
    StoreSerializer,
)


class StoreListView(generics.ListAPIView):
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> Any:
        return scoped_stores(self.request.user)


class BrandListView(generics.ListAPIView):
    serializer_class = BrandSerializer
    permission_classes = [IsAuthenticated]
    queryset = Brand.objects.filter(is_active=True)


class SeasonListView(generics.ListAPIView):
    serializer_class = SeasonSerializer
    permission_classes = [IsAuthenticated]
    queryset = Season.objects.all()


class GstinListView(generics.ListAPIView):
    serializer_class = GstinSerializer
    permission_classes = [IsAuthenticated]
    queryset = Gstin.objects.select_related("legal_entity").filter(is_active=True)


class LegalEntityListView(generics.ListAPIView):
    serializer_class = LegalEntitySerializer
    permission_classes = [IsAuthenticated]
    queryset = LegalEntity.objects.filter(is_active=True)


class SummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        stores = scoped_stores(request.user)
        open_season = Season.objects.filter(status=Season.Status.OPEN).first()
        return Response(
            {
                "entities": LegalEntity.objects.filter(is_active=True).count(),
                "gstins": Gstin.objects.filter(is_active=True).count(),
                "stores": stores.count(),
                "warehouses": stores.filter(
                    store_type=Store.StoreType.WAREHOUSE
                ).count(),
                "brands": Brand.objects.filter(is_active=True).count(),
                "seasons": Season.objects.count(),
                "open_season": open_season.name if open_season else None,
            }
        )
