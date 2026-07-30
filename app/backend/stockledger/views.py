"""Read-only stock-ledger API (the ledger is written only by posting services)."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, Sum
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import require_section
from accounts.sections import CAP_VIEW
from core.money import paise_to_rupees_str
from core.refusals import refusal_body
from core.textsearch import search_term, text_filter
from masters.models import Sku
from masters.scoping import scope_by_store_and_brand
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


#: Movement History (#106) — a document number, the style, or the barcode a
#: person scans. `sku_code` *is* the barcode/SKU identity on this ledger.
MOVEMENT_SEARCH_FIELDS = ("doc_number", "sku_code", "design")


class StockLedgerListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StockLedgerEntrySerializer
    pagination_class = StockLedgerPagination

    def get_queryset(self) -> Any:
        qs = scope_by_store_and_brand(
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
        # The screen's own search box (#102), applied last so it can only
        # narrow what the scope + filters above already allow.
        return text_filter(qs, search_term(self.request), MOVEMENT_SEARCH_FIELDS)


class StockLedgerSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        qs = scope_by_store_and_brand(StockLedgerEntry.objects.all(), request.user, "store_id")
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
        qs = scope_by_store_and_brand(
            InTransitStock.objects.filter(qty__gt=0).select_related(
                "source_store", "destination_store"
            ),
            request.user,
            "source_store_id",
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
        qs = scope_by_store_and_brand(
            QuarantineStock.objects.filter(qty__gt=0).select_related("store", "marked_by"),
            request.user,
            "store_id",
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


#: What a typed term looks through on the stock screen: the barcode a person
#: reads off the tag, the style code, the brand. Deliberately not every column —
#: a search over sizes and colours matches half the catalogue.
ON_HAND_SEARCH_FIELDS = ("sku_code", "design", "brand")


def search_on_hand(qs: Any, term: str) -> Any:
    """Narrow on-hand rows by a typed term or a scanned barcode.

    One box takes both habits, and a whole barcode is not the same question as a
    few letters. A barcode is a non-unique scan-alias (CONTEXT.md, the domain
    language) and stock is a count under it: if the term IS one, the
    person scanned a tag and means that tag — answer with its stock alone, not
    with every barcode that happens to contain those digits. Anything else is
    typing, and matches as plain substring.

    Public: ``outbound``'s cross-location search (#74) narrows the same
    ``StockOnHand`` rows by the same rule, so this is shared rather than
    reimplemented a second time under a different name.
    """
    if not term:
        return qs
    if Sku.objects.filter(barcode__iexact=term).exists():
        return qs.filter(sku_code__iexact=term)
    return text_filter(qs, term, ON_HAND_SEARCH_FIELDS)


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
        qs = scope_by_store_and_brand(
            StockOnHand.objects.filter(net_qty__gt=0).select_related("store"),
            request.user,
            "store_id",
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
        # The screen's own search box (#102). Applied last, on the already-scoped
        # queryset, so a term can only ever narrow — and it composes with the deep
        # link above rather than replacing it.
        qs = search_on_hand(qs, search_term(request))

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


class StockAvailabilityView(APIView):
    """`GET /api/stock/availability?q=&brand=&size=` — where a piece is, in every
    store, size by size (#175, D10 §3).

    The one read in the system that deliberately steps outside `masters.scoping`.
    A customer is standing at the counter asking for a shirt in L that this store
    does not have; answering "we don't stock it" while a sister store has three
    is the loss the system exists to stop. So the boundary is suspended here on
    purpose, registered as ``masters.scope_exceptions.CROSS_STORE_AVAILABILITY``
    with the written reason, and kept narrow by what the answer carries:
    quantities, sizes and store codes. **No cost, value, MRP or margin field is
    built here at all** — not gated per row as
    ``outbound.CrossLocationStockSearchView`` does, but absent by construction, so
    another store's money cannot leak out of this endpoint by a later edit that
    forgot the gate. The exception's ``withholds`` list is asserted against the
    live payload by this endpoint's test.

    It is read-only and it places no hold on anything: the customer is quoted a
    time, never promised a piece. Asking for the stock is a separate act — a
    stock request, which walks its own approval route.

    Grouped design × size × store rather than row per SKU, because that is the
    question being asked out loud: "who has this shirt in L?"
    """

    permission_classes = [require_section("stock", CAP_VIEW)]

    #: Designs, not rows — the cap has to fall where the person's eye does, and a
    #: design with twelve sizes across six stores is still one answer to them.
    MAX_DESIGNS = 200
    #: Two characters match most of the catalogue; a search that returns
    #: everything is the same as no search, only slower.
    MIN_TERM = 3

    def get(self, request: Request) -> Response:
        term = search_term(request)
        if len(term) < self.MIN_TERM:
            return Response(
                refusal_body(
                    "VALIDATION", f"Type at least {self.MIN_TERM} characters, or scan the tag."
                ),
                status=400,
            )

        qs = StockOnHand.objects.filter(net_qty__gt=0, store__is_active=True)
        qs = qs.filter(sku_code__in=self._matching_barcodes(term))
        if brand := (request.query_params.get("brand") or "").strip():
            qs = qs.filter(brand__iexact=brand)
        if size := (request.query_params.get("size") or "").strip():
            qs = qs.filter(size__iexact=size)

        # One past the cap, never the whole match: "is there more?" is answerable
        # with one extra row, and a three-letter term over a 20,000-SKU catalogue
        # must not pull every style name it hit into memory to find that out.
        designs = list(
            qs.order_by("design")
            .values_list("design", flat=True)
            .distinct()[: self.MAX_DESIGNS + 1]
        )
        truncated = len(designs) > self.MAX_DESIGNS
        rows = (
            qs.filter(design__in=designs[: self.MAX_DESIGNS])
            .values("design", "brand", "item", "size", "store__code", "store__name")
            .annotate(qty=Sum("net_qty"))
            .filter(qty__gt=0)
            .order_by("design", "size", "store__code")
        )
        return Response({"results": self._nest(rows), "truncated": truncated})

    def _matching_barcodes(self, term: str) -> Any:
        """The SKUs a typed term or a scanned tag means, as a subquery.

        Three habits, in the order they are meant: a whole barcode is a scan and
        means that tag alone; otherwise the term is the *start* of a style code
        (people read design numbers left to right off the tag), or anywhere
        inside the item name for someone who only knows it as "chinos".

        A queryset rather than a list on purpose — the match runs as one SQL
        subquery, so a three-letter term that hits ten thousand styles never
        travels through Python on its way back into the filter.
        """
        # Not narrowed to active SKUs: stock that exists can be asked for, and a
        # style retired in the master with pieces still on a shelf is exactly the
        # one a store is hunting for.
        if Sku.objects.filter(barcode__iexact=term).exists():
            return Sku.objects.filter(barcode__iexact=term).values("barcode")
        return Sku.objects.filter(Q(design__istartswith=term) | Q(item__icontains=term)).values(
            "barcode"
        )

    @staticmethod
    def _nest(rows: Any) -> list[dict[str, Any]]:
        """Flat design × size × store rows folded into the shape the screen reads.

        The rows arrive ordered by design, size then store code, so one pass
        builds the nesting and the output keeps that order — the answer reads
        the way a person scans it, smallest size first, and does not reshuffle
        between two searches for the same thing.
        """
        results: list[dict[str, Any]] = []
        by_design: dict[str, dict[str, Any]] = {}
        for row in rows:
            design = row["design"]
            entry = by_design.get(design)
            if entry is None:
                entry = {
                    "design": design,
                    "brand": row["brand"],
                    "item": row["item"],
                    "sizes": [],
                }
                by_design[design] = entry
                results.append(entry)
            sizes = entry["sizes"]
            if not sizes or sizes[-1]["size"] != row["size"]:
                sizes.append({"size": row["size"], "stores": []})
            sizes[-1]["stores"].append(
                {
                    "store": row["store__code"],
                    "store_name": row["store__name"],
                    "qty": row["qty"],
                }
            )
        return results
