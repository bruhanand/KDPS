"""Read-only stock-ledger API (the ledger is written only by posting services)."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Sum
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.money import paise_to_rupees_str
from masters.scoping import scope_by_store
from stockledger.models import StockLedgerEntry
from stockledger.serializers import StockLedgerEntrySerializer


class StockLedgerPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class StockLedgerListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StockLedgerEntrySerializer
    pagination_class = StockLedgerPagination

    def get_queryset(self) -> Any:
        qs = scope_by_store(
            StockLedgerEntry.objects.select_related("store", "booking", "pt_file"),
            self.request.user,
            "store_id",
        )
        pt = self.request.query_params.get("pt_file")
        if pt:
            qs = qs.filter(pt_file_id=pt)
        doc = self.request.query_params.get("doc_number")
        if doc:
            qs = qs.filter(doc_number=doc)
        return qs


class StockLedgerSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        qs = scope_by_store(StockLedgerEntry.objects.all(), request.user, "store_id")
        agg = qs.aggregate(
            entries=Count("id"),
            net_qty=Sum("qty"),
            net_value=Sum("amount"),
        )
        distinct_skus = qs.values("sku_code").distinct().count()
        distinct_docs = qs.values("doc_number").distinct().count()
        return Response({
            "entries": agg["entries"] or 0,
            "net_qty": agg["net_qty"] or 0,
            "net_value_paise": agg["net_value"] or 0,
            "net_value_rupees": paise_to_rupees_str(agg["net_value"] or 0),
            "distinct_skus": distinct_skus,
            "distinct_documents": distinct_docs,
        })


# Columns surfaced per grouping for the Stock-on-Hand screen.
_GROUP_FIELDS = {
    "sku": ["store__code", "brand", "design", "color", "size", "item", "season", "sku_code"],
    "brand": ["store__code", "brand"],
    "store": ["store__code", "store__name"],
}


class StockOnHandView(APIView):
    """Net stock currently on hand (Σqty > 0) grouped by SKU / brand / store.

    Computed live from the append-only ledger: inward (+) minus reversals (−),
    so a fully-reversed posting simply drops out of the on-hand view.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        group_by = request.query_params.get("group_by", "sku")
        if group_by not in _GROUP_FIELDS:
            group_by = "sku"
        qs = scope_by_store(StockLedgerEntry.objects.all(), request.user, "store_id")
        if store := request.query_params.get("store"):
            qs = qs.filter(store__code=store)
        if brand := request.query_params.get("brand"):
            qs = qs.filter(brand=brand)

        fields = _GROUP_FIELDS[group_by]
        grouped = (
            qs.values(*fields)
            .annotate(
                net_qty=Sum("qty"),
                net_value=Sum("amount"),
                skus=Count("sku_code", distinct=True),
            )
            .filter(net_qty__gt=0)
            .order_by("brand" if group_by != "store" else "store__code", "-net_qty")[:2000]
        )

        rows = []
        total_qty = total_value = 0
        for g in grouped:
            net_value = g["net_value"] or 0
            total_qty += g["net_qty"]
            total_value += net_value
            rows.append({
                "store_code": g.get("store__code", ""),
                "store_name": g.get("store__name", ""),
                "brand": g.get("brand", ""),
                "design": g.get("design", ""),
                "color": g.get("color", ""),
                "size": g.get("size", ""),
                "item": g.get("item", ""),
                "season": g.get("season", ""),
                "sku_code": g.get("sku_code", ""),
                "net_qty": g["net_qty"],
                "skus": g["skus"],
                "net_value_paise": net_value,
                "net_value_rupees": paise_to_rupees_str(net_value),
            })

        return Response({
            "group_by": group_by,
            "summary": {
                "units_on_hand": total_qty,
                "value_paise": total_value,
                "value_rupees": paise_to_rupees_str(total_value),
                "lines": len(rows),
            },
            "rows": rows,
        })
