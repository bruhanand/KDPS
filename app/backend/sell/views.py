"""The three sale endpoints: take a bill, find a bill, read a bill.

There is no fourth. **No endpoint in this module can change a posted sale** (A7),
and that is not an omission to be corrected later: a bill is a printed fact in a
customer's hand, and the only honest correction is the kernel's reversing
transition. A PUT here would be a way to make the paper and the books disagree.

Everything money-shaped lives in `sell.services.accept`; these views translate
between HTTP and it, and answer refusals in the till's own vocabulary — a
sentence for the person, a code for the queue.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Prefetch, Q, QuerySet
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import first_message, refuse
from masters.scoping import scope_by_store
from sell.models import Sale, SaleLine
from sell.permissions import CanReadOrBill, CanReadSales
from sell.serializers import SaleDetailSerializer, SaleInSerializer, SaleListItemSerializer
from sell.services.accept import AcceptError, accept_sale

#: A search is for finding one customer's bill, not for exporting the day.
SEARCH_LIMIT = 50


def _sales(user: Any) -> QuerySet[Sale]:
    """Bills at the caller's own stores, in the read shape.

    The only way this module reaches `Sale` on a read path, so a screen cannot
    forget the scope: a store person sees their own counter's bills and nobody
    else's.
    """
    return scope_by_store(
        Sale.objects.select_related("store", "created_by").prefetch_related(
            Prefetch("lines", queryset=SaleLine.objects.select_related("salesman")),
            "tenders__credit_note",
            "flags",
            "credit_notes_issued",
        ),
        user,
        "store_id",
    )


class SaleListCreateView(APIView):
    """`POST` — the till syncing a bill. `GET` — customer search / reprint (E1, E2).

    The POST is idempotent: the till replays from a durable queue, so the same
    `idempotency_uuid` answers **200 with the same bill and no second write**,
    while a first arrival answers 201. The till tells the two apart on the status
    code and stops replaying either way.
    """

    permission_classes = [IsAuthenticated, CanReadOrBill]

    def post(self, request: Request) -> Response:
        form = SaleInSerializer(data=request.data)
        if not form.is_valid():
            return refuse("VALIDATION", first_message(form.errors), 400)
        try:
            result = accept_sale(dict(form.validated_data), request.user)
        except AcceptError as exc:
            return refuse(exc.code, exc.message, exc.status)
        body = {
            "doc_number": result.sale.doc_number,
            "id": result.sale.id,
            "flags": result.flags,
        }
        return Response(
            body,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )

    def get(self, request: Request) -> Response:
        mobile = (request.query_params.get("mobile") or "").strip()
        name = (request.query_params.get("name") or "").strip()
        doc = (request.query_params.get("doc") or "").strip()
        if not (mobile or name or doc):
            return refuse(
                "VALIDATION",
                "Search by mobile number, customer name or bill number.",
                400,
            )
        rows = _sales(request.user)
        if mobile:
            rows = rows.filter(customer_mobile__icontains=mobile)
        if name:
            rows = rows.filter(customer_name__icontains=name)
        if doc:
            # A person types "74" as often as the whole key, so both find the bill.
            rows = rows.filter(Q(doc_number__icontains=doc) | Q(till_seq=_as_int(doc)))
        return Response(SaleListItemSerializer(rows[:SEARCH_LIMIT], many=True).data)


def _as_int(text: str) -> int:
    """`text` as a sequence number, or a number no bill can have."""
    try:
        return int(text)
    except ValueError:
        return -1


class SaleDetailView(APIView):
    """`GET /api/sell/sales/{doc_number}` — one bill, read-only, for reprint.

    Out of scope answers 404 rather than 403, the same as every other document
    detail here: a 403 would confirm the bill exists.
    """

    permission_classes = [IsAuthenticated, CanReadSales]

    def get(self, request: Request, doc_number: str) -> Response:
        sale = _sales(request.user).filter(doc_number=doc_number).first()
        if sale is None:
            return refuse("NOT_FOUND", f"No bill '{doc_number}' at your stores.", 404)
        return Response(SaleDetailSerializer(sale).data)
