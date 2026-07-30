"""The three sale endpoints: take a bill, find a bill, read a bill.

There is no fourth. **No endpoint in this module can change a posted sale** (A7),
and that is not an omission to be corrected later: a bill is a printed fact in a
customer's hand, and the only honest correction is the kernel's reversing
transition. A PUT here would be a way to make the paper and the books disagree.

Everything money-shaped lives in `sell.services.accept`; these views translate
between HTTP and it, and answer refusals in the till's own vocabulary - a
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

from core.refusals import first_message, refusal_body
from masters.scoping import scope_by_store
from sell.models import Sale, SaleLine
from sell.permissions import CanReadOrBill, CanReadSales, CanRunTill
from sell.serializers import SaleReadSerializer, SaleRowSerializer, SaleWriteSerializer
from sell.services.accept import AcceptError, accept_sale
from sell.services.dataset import TillScopeError, build_dataset, resolve_till_store

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
    """`POST` - the till syncing a bill. `GET` - customer search / reprint (E1, E2).

    The POST is idempotent: the till replays from a durable queue, so the same
    `idempotency_uuid` answers **200 with the same bill and no second write**,
    while a first arrival answers 201. The till tells the two apart on the status
    code and stops replaying either way.
    """

    permission_classes = [IsAuthenticated, CanReadOrBill]

    def post(self, request: Request) -> Response:
        form = SaleWriteSerializer(data=request.data)
        if not form.is_valid():
            return Response(refusal_body("VALIDATION", first_message(form.errors)), status=400)
        try:
            result = accept_sale(dict(form.validated_data), request.user)
        except AcceptError as exc:
            return Response(refusal_body(exc.code, exc.message), status=exc.status)
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
            return Response(
                refusal_body(
                    "VALIDATION", "Search by mobile number, customer name or bill number."
                ),
                status=400,
            )
        rows = _sales(request.user)
        if mobile:
            rows = rows.filter(customer_mobile__icontains=mobile)
        if name:
            rows = rows.filter(customer_name__icontains=name)
        if doc:
            # A person reads "74" off the slip as often as the whole key, so both
            # find the bill. The sequence arm is only added when the term really
            # is a number, rather than smuggled in as a value no row can hold.
            match = Q(doc_number__icontains=doc)
            if doc.isdigit():
                match |= Q(till_seq=int(doc))
            rows = rows.filter(match)
        return Response(SaleRowSerializer(rows[:SEARCH_LIMIT], many=True).data)


class DatasetView(APIView):
    """`GET /api/sell/dataset` - everything the counter has to know offline.

    Gated at `sell: operate`, not `view`: this is not a report about selling, it is
    the working copy a till bills from, and it carries the store's manager
    override PIN hashes. Somebody who may read yesterday's bills has no use for it.

    See `sell.services.dataset` for what is in it and why the cursor laps
    backwards.

    `TILL_SCOPE` is the one refusal that carries a code, and the till needs it to:
    it means "this login will never be a till, a human must fix the account", which
    is not something to retry. The capability refusal above it answers with DRF's
    own `{"detail": ...}` at 403 - the same as every sibling `require_section` gate,
    and the same as `/api/stock/availability` recorded when it shipped. Unifying the
    two body shapes is one change across every gate in the project, not this
    endpoint's to make alone.
    """

    permission_classes = [IsAuthenticated, CanRunTill]

    def get(self, request: Request) -> Response:
        try:
            store = resolve_till_store(request.user)
        except TillScopeError as exc:
            return Response(refusal_body("TILL_SCOPE", str(exc)), status=403)
        return Response(build_dataset(store, request.query_params.get("since") or ""))


class SaleDetailView(APIView):
    """`GET /api/sell/sales/{doc_number}` - one bill, read-only, for reprint.

    Out of scope answers 404 rather than 403, the same as every other document
    detail here: a 403 would confirm the bill exists.
    """

    permission_classes = [IsAuthenticated, CanReadSales]

    def get(self, request: Request, doc_number: str) -> Response:
        sale = _sales(request.user).filter(doc_number=doc_number).first()
        if sale is None:
            return Response(
                refusal_body("NOT_FOUND", f"No bill '{doc_number}' at your stores."), status=404
            )
        return Response(SaleReadSerializer(sale).data)
