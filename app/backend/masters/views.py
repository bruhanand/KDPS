"""Master-data API: scoped reads for the foundation switcher + steward-gated
create/edit (the D8 stewardship slice). Reads stay open to any authenticated
user; writes require a master-data steward (owner / IT admin / data steward).
One read is deliberately *un*scoped — `LocationListView`, whose docstring says
why — and it pays for that by carrying identity fields and nothing else.
Records are deactivated (`is_active`), never hard-deleted — masters are referenced
by append-only ledger rows.
"""

from __future__ import annotations

from typing import Any

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from masters.models import Brand, Gstin, LegalEntity, Season, Sku, Store

# Re-exported: the gate moved to `masters.permissions` so the vendor master —
# which lives in `vendors` because it carries bookings — is gated by the same
# rule. Imported here so `from masters.views import IsMasterSteward` still reads.
from masters.permissions import IsMasterSteward
from masters.scoping import scoped_stores
from masters.serializers import (
    BrandSerializer,
    GstinSerializer,
    LegalEntitySerializer,
    LocationSerializer,
    SeasonSerializer,
    StoreSerializer,
)

# --- Stores --------------------------------------------------------------


class StoreListView(generics.ListCreateAPIView):
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]

    def get_queryset(self) -> Any:
        return scoped_stores(self.request.user)


class LocationListView(generics.ListAPIView):
    """Every active location in the network, identity fields only — the list of
    places stock may be *sent* to.

    Deliberately unscoped, unlike `StoreListView` above. That one answers "which
    units may I operate on", which is the right question for the *source* of a
    transfer and the wrong one for its *destination*: sending a carton somewhere
    claims no rights at the place it is going. Scoping both alike left every
    store person with an empty destination picker and no way to start a transfer
    at all (#147). What guards a store sending anywhere is the e-way bill the
    screen demands across registrations, plus the Operations Head approval gate
    (PRD #104) — a picker is not a permission and must not become one.
    """

    serializer_class = LocationSerializer
    permission_classes = [IsAuthenticated]
    queryset = Store.objects.filter(is_active=True).select_related("gstin").order_by("code")


class StoreDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Store.objects.select_related("gstin").all()


# --- Brands --------------------------------------------------------------


class BrandListView(generics.ListCreateAPIView):
    serializer_class = BrandSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Brand.objects.filter(is_active=True)


class BrandDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = BrandSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Brand.objects.all()


# --- Seasons -------------------------------------------------------------


class SeasonListView(generics.ListCreateAPIView):
    serializer_class = SeasonSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Season.objects.all()


class SeasonDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = SeasonSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Season.objects.all()


# --- GSTINs --------------------------------------------------------------


class GstinListView(generics.ListCreateAPIView):
    serializer_class = GstinSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Gstin.objects.select_related("legal_entity").filter(is_active=True)


class GstinDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = GstinSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Gstin.objects.select_related("legal_entity").all()


# --- Legal entities ------------------------------------------------------


class LegalEntityListView(generics.ListAPIView):
    serializer_class = LegalEntitySerializer
    permission_classes = [IsAuthenticated]
    queryset = LegalEntity.objects.filter(is_active=True)


class SkuLookupView(APIView):
    """Registry reuse at authoring time (D2 Q16/Q41): has this vendor+style+size been
    seen before? Exact-match filters over the SKU master; the PT editor shows "seen
    before — reusing barcode X" and copies barcode/colour/HSN/MRP from the registry
    instead of minting a duplicate identity. Pure read.

    ``GET /masters/skus/lookup?design=&size=&brand=&barcode=`` — at least one of
    ``design``/``barcode`` is required (never dump the registry)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        params = {
            key: (request.query_params.get(key) or "").strip()
            for key in ("design", "size", "brand", "barcode")
        }
        if not (params["design"] or params["barcode"]):
            return Response({"detail": "Pass design= or barcode= to look up."}, status=400)
        qs = Sku.objects.filter(is_active=True)
        for field in ("design", "size", "brand", "barcode"):
            if params[field]:
                qs = qs.filter(**{f"{field}__iexact": params[field]})
        matches = [
            {
                "barcode": s.barcode,
                "design": s.design,
                "color": s.color,
                "size": s.size,
                "brand": s.brand,
                "item": s.item,
                "hsn": s.hsn,
                "mrp": (s.mrp_paise / 100) if s.mrp_paise is not None else None,
                "first_doc_number": s.first_doc_number,
            }
            for s in qs.order_by("-updated_at")[:10]
        ]
        return Response({"matches": matches, "count": len(matches)})


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
                "warehouses": stores.filter(store_type=Store.StoreType.WAREHOUSE).count(),
                "brands": Brand.objects.filter(is_active=True).count(),
                "seasons": Season.objects.count(),
                "open_season": open_season.name if open_season else None,
            }
        )
