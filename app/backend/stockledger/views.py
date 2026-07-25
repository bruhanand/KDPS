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
from masters.scoping import scope_by_brand, scope_by_store
from stockledger.models import (
    InTransitStock,
    QuarantineStock,
    StockLedgerEntry,
    StockOnHand,
    merch_dims,
)
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
        qs = scope_by_brand(
            scope_by_store(
                StockLedgerEntry.objects.select_related("store", "booking", "pt_file"),
                self.request.user,
                "store_id",
            ),
            self.request.user,
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
        qs = scope_by_brand(
            scope_by_store(StockLedgerEntry.objects.all(), request.user, "store_id"), request.user
        )
        agg = qs.aggregate(
            entries=Count("id"),
            net_qty=Sum("qty"),
            net_value=Sum("amount"),
        )
        distinct_skus = qs.values("sku_code").distinct().count()
        distinct_docs = qs.values("doc_number").distinct().count()
        return Response(
            {
                "entries": agg["entries"] or 0,
                "net_qty": agg["net_qty"] or 0,
                "net_value_paise": agg["net_value"] or 0,
                "net_value_rupees": paise_to_rupees_str(agg["net_value"] or 0),
                "distinct_skus": distinct_skus,
                "distinct_documents": distinct_docs,
            }
        )


class InTransitView(APIView):
    """The in-transit bucket — the third honest stock number (at-warehouse /
    in-transit / at-store). Served from the materialised `InTransitStock`
    projection; rows are keyed to the transfer holding the pieces. The sender
    is answerable until the receiver scans in, so scoping rides on the
    source store."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        qs = scope_by_brand(
            scope_by_store(
                InTransitStock.objects.filter(qty__gt=0).select_related(
                    "source_store", "destination_store"
                ),
                request.user,
                "source_store_id",
            ),
            request.user,
        )
        if doc := request.query_params.get("transfer"):
            qs = qs.filter(transfer_doc_number=doc)

        totals = qs.aggregate(units=Sum("qty"), value=Sum("value_paise"))
        rows = [
            {
                "transfer_doc_number": o.transfer_doc_number,
                "source_store_code": o.source_store.code,
                "destination_store_code": o.destination_store.code,
                "sku_code": o.sku_code,
                **merch_dims(o),
                "qty": o.qty,
                "value_paise": o.value_paise,
                "value_rupees": paise_to_rupees_str(o.value_paise),
                "updated_at": o.updated_at,
            }
            for o in qs.order_by("transfer_doc_number", "sku_code")
        ]
        return Response(
            {
                "summary": {
                    "units_in_transit": totals["units"] or 0,
                    "value_paise": totals["value"] or 0,
                    "value_rupees": paise_to_rupees_str(totals["value"] or 0),
                    "transfers": qs.values("transfer_doc_number").distinct().count(),
                },
                "rows": rows,
            }
        )


class QuarantineView(APIView):
    """The quarantine filter inside inventory (issue #69) — damaged / held stock
    that is NOT free-to-sell. Served from the materialised ``QuarantineStock``
    projection, each row carrying who marked it and when (Rule 10). Scoped by
    store, filterable by brand (the ownership filter) and store."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        qs = scope_by_brand(
            scope_by_store(
                QuarantineStock.objects.filter(qty__gt=0).select_related("store", "marked_by"),
                request.user,
                "store_id",
            ),
            request.user,
        )
        if store := request.query_params.get("store"):
            qs = qs.filter(store__code=store)
        if brand := request.query_params.get("brand"):
            qs = qs.filter(brand=brand)

        totals = qs.aggregate(units=Sum("qty"), value=Sum("value_paise"))
        rows = [
            {
                "store_code": o.store.code,
                "store_name": o.store.name,
                "sku_code": o.sku_code,
                **merch_dims(o),
                "qty": o.qty,
                "value_paise": o.value_paise,
                "value_rupees": paise_to_rupees_str(o.value_paise),
                "marked_by": o.marked_by.username if o.marked_by else None,
                "marked_at": o.marked_at,
            }
            for o in qs.order_by("store__code", "brand", "sku_code")
        ]
        return Response(
            {
                "summary": {
                    "units_quarantined": totals["units"] or 0,
                    "value_paise": totals["value"] or 0,
                    "value_rupees": paise_to_rupees_str(totals["value"] or 0),
                    "lines": len(rows),
                },
                "rows": rows,
            }
        )


class StockOnHandView(APIView):
    """Net stock on hand (Σqty > 0) grouped by SKU / brand / store, served from the
    **materialised** `StockOnHand` projection (maintained inside each post/reverse,
    rebuildable via `manage.py rebuild_stock_on_hand`).

    Large result sets are capped to `MAX_LINES` for payload safety, but the true
    line count and a `truncated` flag are ALWAYS reported — the previous silent
    `[:2000]` drop is gone.
    """

    permission_classes = [IsAuthenticated]
    MAX_LINES = 2000

    def get(self, request: Request) -> Response:
        group_by = request.query_params.get("group_by", "sku")
        if group_by not in ("sku", "brand", "store"):
            group_by = "sku"
        qs = scope_by_brand(
            scope_by_store(
                StockOnHand.objects.filter(net_qty__gt=0).select_related("store"),
                request.user,
                "store_id",
            ),
            request.user,
        )
        if store := request.query_params.get("store"):
            qs = qs.filter(store__code=store)
        if brand := request.query_params.get("brand"):
            qs = qs.filter(brand=brand)
        # Where a global-search item result lands: one barcode, its stock wherever
        # the caller may see it. Filtered in the DB, not the client, so the answer
        # survives the MAX_LINES cap.
        if sku := request.query_params.get("sku"):
            qs = qs.filter(sku_code=sku)

        totals = qs.aggregate(units=Sum("net_qty"), value=Sum("net_value_paise"))
        rows, lines = self._rows(qs, group_by)
        return Response(
            {
                "group_by": group_by,
                "summary": {
                    "units_on_hand": totals["units"] or 0,
                    "value_paise": totals["value"] or 0,
                    "value_rupees": paise_to_rupees_str(totals["value"] or 0),
                    "lines": lines,
                    "displayed": len(rows),
                    "truncated": len(rows) < lines,
                },
                "rows": rows,
            }
        )

    def _rows(self, qs: Any, group_by: str) -> tuple[list[dict], int]:
        if group_by == "sku":
            lines = qs.count()
            page = qs.order_by("brand", "-net_qty")[: self.MAX_LINES]
            rows = [
                {
                    "store_id": o.store_id,
                    "store_code": o.store.code,
                    "store_name": o.store.name,
                    "brand": o.brand,
                    "design": o.design,
                    "color": o.color,
                    "size": o.size,
                    "item": o.item,
                    "season": o.season,
                    "sku_code": o.sku_code,
                    "net_qty": o.net_qty,
                    "skus": 1,
                    "net_value_paise": o.net_value_paise,
                    "net_value_rupees": paise_to_rupees_str(o.net_value_paise),
                }
                for o in page
            ]
            return rows, lines

        fields = ["store__code", "brand"] if group_by == "brand" else ["store__code", "store__name"]
        grouped = (
            qs.values(*fields)
            .annotate(
                g_qty=Sum("net_qty"),
                g_value=Sum("net_value_paise"),
                skus=Count("sku_code", distinct=True),
            )
            .filter(g_qty__gt=0)
            .order_by("brand" if group_by == "brand" else "store__code")
        )
        lines = grouped.count()
        rows = [
            {
                "store_code": g.get("store__code", ""),
                "store_name": g.get("store__name", ""),
                "brand": g.get("brand", ""),
                "design": "",
                "color": "",
                "size": "",
                "item": "",
                "season": "",
                "sku_code": "",
                "net_qty": g["g_qty"],
                "skus": g["skus"],
                "net_value_paise": g["g_value"] or 0,
                "net_value_rupees": paise_to_rupees_str(g["g_value"] or 0),
            }
            for g in grouped[: self.MAX_LINES]
        ]
        return rows, lines
