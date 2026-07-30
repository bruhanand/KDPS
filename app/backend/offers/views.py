"""The rulebook API: head office writes rules, everybody else reads them.

Three endpoints and a hard asymmetry between them. Reading is wide - a store
manager checks what is running this morning, and the till pulls the same rows
inside its dataset. Writing is head office's alone, and writing over a **live**
rule is not possible at all: the till has already cached it and bills have
already printed under it, so a change ends the running rule and starts a new one
beside it (`PUT` below), which is the same snapshot discipline every posted
document in this system obeys.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import require_section
from accounts.sections import CAP_MANAGE, CAP_VIEW
from core.refusals import first_message, refusal_body
from masters.models import Store
from masters.scoping import active_brand_names, active_store_ids, is_brand_scoped
from offers.models import Offer, OfferQuerySet
from offers.serializers import OfferReadSerializer, OfferWriteSerializer

#: `view` reads the rulebook, `manage` writes it (contract §Step 4). One view
#: carries both because GET and POST share a path.
CanReadOrAuthor = require_section("offers_price", CAP_VIEW, write_minimum=CAP_MANAGE)


def _visible(user: Any) -> OfferQuerySet:
    """The rules this caller may read, narrowed the way their screen is.

    Two axes, and they are asked in the caller's own terms. A store person sees
    rules that name a store they are working in **through the unit switcher**,
    because `store_scope` is a list of codes rather than a foreign key and the
    switcher is what decides which store the screen is about (the #171 lesson:
    one scope model per screen, never two). A brand-scoped person sees their own
    brands' rules, plus the storewide ones - a storewide discount lands on their
    brand's pieces, so it is not somebody else's data being leaked to them.
    """
    rows = (
        OfferQuerySet(Offer)
        .select_related("brand", "approved_by")
        .exclude(status=Offer.Status.ENDED)
    )
    if is_brand_scoped(user):
        names = active_brand_names(user)
        if names is not None:
            rows = rows.filter(Q(brand__name__in=names) | Q(brand__isnull=True))
        return rows

    store_ids = active_store_ids(user)
    if store_ids is None:  # head office: the network's rulebook
        return rows
    codes = list(Store.objects.filter(id__in=store_ids).values_list("code", flat=True))
    if not codes:
        return rows.none()
    reach = Q()
    for code in codes:
        reach |= Q(store_scope__stores__contains=[code])
    return rows.filter(reach)


def _bad_request(errors: Any) -> Response:
    return Response(refusal_body("VALIDATION", first_message(errors)), status=400)


class OfferListCreateView(APIView):
    """`GET` - what is running (and what is coming). `POST` - author a draft."""

    permission_classes = [IsAuthenticated, CanReadOrAuthor]

    def get(self, request: Request) -> Response:
        rows = _visible(request.user)
        if request.query_params.get("live") == "true":
            rows = rows.live_on(timezone.localdate())
        brand = (request.query_params.get("brand") or "").strip()
        if brand:
            rows = rows.filter(Q(brand__code__iexact=brand) | Q(brand__name__iexact=brand))
        store = (request.query_params.get("store") or "").strip().upper()
        if store:
            # Narrows *within* what the caller may already see - it never reaches
            # past the switcher (the amended dashboard rule, contract §Step 1).
            rows = rows.filter(store_scope__stores__contains=[store])
        return Response(OfferReadSerializer(rows.order_by("priority", "id"), many=True).data)

    def post(self, request: Request) -> Response:
        serializer = OfferWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return _bad_request(serializer.errors)
        offer = serializer.save(created_by=request.user, status=Offer.Status.DRAFT)
        return Response(OfferReadSerializer(offer).data, status=201)


class OfferDetailView(APIView):
    """`GET` one rule; `PUT` to change it - or, if it is live, to replace it."""

    permission_classes = [IsAuthenticated, CanReadOrAuthor]

    def get(self, request: Request, pk: int) -> Response:
        offer = _visible(request.user).filter(pk=pk).first()
        if offer is None:
            return Response(refusal_body("NOT_FOUND", f"No offer {pk}."), status=404)
        return Response(OfferReadSerializer(offer).data)

    @transaction.atomic
    def put(self, request: Request, pk: int) -> Response:
        offer = Offer.objects.select_for_update().filter(pk=pk).first()
        if offer is None:
            return Response(refusal_body("NOT_FOUND", f"No offer {pk}."), status=404)

        # A live rule's content is frozen, so an edit to one is authored as a new
        # rule from a whole body; everything else patches the row in front of us.
        replacing = (
            offer.status == Offer.Status.LIVE
            and str(request.data.get("status") or "") != Offer.Status.ENDED
        )
        serializer = (
            OfferWriteSerializer(data=request.data)
            if replacing
            else OfferWriteSerializer(offer, data=request.data, partial=True)
        )
        if not serializer.is_valid():
            return _bad_request(serializer.errors)

        if replacing:
            return self._end_and_replace(offer, serializer, request)
        saved = serializer.save(**_approval_stamp(offer, serializer.validated_data, request))
        return Response(OfferReadSerializer(saved).data)

    def _end_and_replace(
        self, offer: Offer, serializer: OfferWriteSerializer, request: Request
    ) -> Response:
        """Stop the running rule today; start its successor as a fresh draft.

        The old rule ends **today**, not yesterday, and that one day of overlap is
        deliberate. Fifty tills are holding the old rule offline and will keep
        applying it until their own clocks pass its end date; back-dating the end
        would not stop a single one of them, it would only make every bill they
        printed today disagree with the server and raise an `offer_mismatch` on
        each. The placard is still in the window, too. So both rules can be live
        for a day, the engine gives the customer the better of the two, and the
        successor takes over cleanly tomorrow.
        """
        today = timezone.localdate()
        offer.status = Offer.Status.ENDED
        offer.ends_on = max(today, offer.starts_on)
        offer.save(update_fields=["status", "ends_on", "updated_at"])

        successor = serializer.save(
            created_by=request.user,
            status=Offer.Status.DRAFT,
            replaces=offer,
        )
        body = OfferReadSerializer(successor).data
        body["replaced_offer_id"] = offer.id
        return Response(body, status=201)


def _approval_stamp(offer: Offer, data: dict[str, Any], request: Request) -> dict[str, Any]:
    """Who approved it, recorded the moment the status says approved (D5 Q9).

    The name is the point: "a named approver before go-live" is the gate, and a
    row that went live with nobody's name on it is refused by the table itself.
    Whether that name must belong to a *second* person is the half of D5 Q9 that
    was explicitly deferred to the roles work, so it is not decided here.
    """
    if data.get("status") == Offer.Status.APPROVED and offer.approved_by_id is None:
        return {"approved_by": request.user}
    return {}
