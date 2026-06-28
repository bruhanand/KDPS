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
from masters.serializers import (
    BrandSerializer,
    GstinSerializer,
    LegalEntitySerializer,
    SeasonSerializer,
    StoreSerializer,
)


def scoped_stores(user: Any) -> Any:
    """Stores the actor may see (fail-closed for narrower scopes, ADR-0003).

    Reads `scope_type` / `entity_id` / `stores` off the user by duck-typing so
    `masters` never imports `accounts` (keeps the module seam, ADR-0002).
    """
    qs = Store.objects.filter(is_active=True).select_related("gstin")
    if getattr(user, "is_superuser", False):
        return qs
    scope = getattr(user, "scope_type", "all")
    if scope == "all":
        return qs
    if scope == "entity" and getattr(user, "entity_id", None):
        return qs.filter(gstin__legal_entity_id=user.entity_id)
    return qs.filter(pk__in=user.stores.values_list("pk", flat=True))


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
