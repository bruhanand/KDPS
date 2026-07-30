"""Master-data API: scoped reads for the foundation switcher + steward-gated
create/edit (the D8 stewardship slice). Reads stay open to any authenticated
user; writes require a master-data steward (owner / IT admin / data steward).
One read is deliberately *un*scoped - `LocationListView`, whose docstring says
why - and it pays for that by carrying identity fields and nothing else.
Records are deactivated (`is_active`), never hard-deleted - masters are referenced
by append-only ledger rows.

One master here is not a steward's: `StoreTargetView`, the store x month sales
target (#171). Choosing what a store must sell is a Money act, so it answers to
the Money section rather than to the stewardship rule above, and its docstring
carries the argument.
"""

from __future__ import annotations

from typing import Any

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import require_section
from accounts.sections import CAP_MANAGE, CAP_VIEW
from core.fiscal import financial_year_months
from core.textsearch import search_term, text_filter
from masters.models import Brand, Gstin, LegalEntity, Season, Sku, Store, StoreTarget

# Re-exported: the gate moved to `masters.permissions` so the vendor master —
# which lives in `vendors` because it carries bookings — is gated by the same
# rule. Imported here so `from masters.views import IsMasterSteward` still reads.
from masters.permissions import IsMasterSteward
from masters.scoping import scope_by_entitlement, scoped_stores
from masters.serializers import (
    BrandSerializer,
    GstinSerializer,
    LegalEntitySerializer,
    LocationSerializer,
    SeasonSerializer,
    StoreSerializer,
    StoreTargetSerializer,
    StoreTargetWriteSerializer,
)

#: Master data lists (#106) — every one of them searches by name / code.
STORE_SEARCH_FIELDS = ("code", "name")
BRAND_SEARCH_FIELDS = ("code", "name")
SEASON_SEARCH_FIELDS = ("code", "name")
#: `Gstin` carries no name/code pair — the number itself, its state, and the
#: legal entity it's registered under are the nearest equivalent.
GSTIN_SEARCH_FIELDS = ("gstin", "state_name", "legal_entity__name", "legal_entity__code")

# --- Stores --------------------------------------------------------------


class StoreListView(generics.ListCreateAPIView):
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]

    def get_queryset(self) -> Any:
        qs = scoped_stores(self.request.user)
        return text_filter(qs, search_term(self.request), STORE_SEARCH_FIELDS)


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

    def get_queryset(self) -> Any:
        qs = Brand.objects.filter(is_active=True)
        return text_filter(qs, search_term(self.request), BRAND_SEARCH_FIELDS)


class BrandDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = BrandSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Brand.objects.all()


# --- Seasons -------------------------------------------------------------


class SeasonListView(generics.ListCreateAPIView):
    serializer_class = SeasonSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]

    def get_queryset(self) -> Any:
        qs = Season.objects.all()
        return text_filter(qs, search_term(self.request), SEASON_SEARCH_FIELDS)


class SeasonDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = SeasonSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]
    queryset = Season.objects.all()


# --- GSTINs --------------------------------------------------------------


class GstinListView(generics.ListCreateAPIView):
    serializer_class = GstinSerializer
    permission_classes = [IsAuthenticated, IsMasterSteward]

    def get_queryset(self) -> Any:
        qs = Gstin.objects.select_related("legal_entity").filter(is_active=True)
        return text_filter(qs, search_term(self.request), GSTIN_SEARCH_FIELDS)


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


# --- Store targets -------------------------------------------------------


#: Setting a store's monthly number is a Money act, not a Setup one (#171). The
#: matrix puts the cell at `money: manage` and the D10 grill made *which* role
#: holds it admin-editable data (Rule 12), so this reads the same
#: `Role.section_access` the sidebar reads and nothing here names a role.
#: Reading stays at `view`, the rung a store person holds ("Expenses only"), so a
#: store may see the number it is judged against without being able to move it.
CanReadOrSetStoreTarget = require_section("money", CAP_VIEW, write_minimum=CAP_MANAGE)


def _refuse(code: str, message: str, status: int) -> Response:
    """The D10 contract's refusal body: a sentence for the person, a code for the
    caller. Deliberately not DRF's `{"detail": ...}` - the till replays writes
    from a durable queue and has to tell "retry forever" from "this bill needs a
    human", which it does on the code, never on the prose.

    Private to this module while it is the only endpoint using it; the shape is
    the contract's, so it moves to a shared home when the second one lands rather
    than being copied.
    """
    return Response({"error": message, "code": code}, status=status)


def _first_message(errors: Any) -> str:
    """The first sentence out of a DRF error tree, flattened.

    A refusal body carries one message, and a serializer's is keyed by field. The
    first one is the one the person needs: these forms are three fields wide, and
    a screen that fixes the named field re-submits and hears about the next.
    """
    if isinstance(errors, dict):
        for value in errors.values():
            found = _first_message(value)
            if found:
                return found
        return ""
    if isinstance(errors, list):
        for item in errors:
            found = _first_message(item)
            if found:
                return found
        return ""
    return str(errors).strip()


class StoreTargetView(APIView):
    """`GET | PUT /api/masters/store-targets` - the store x month target grid.

    A master, so a PUT *is* the whole write: `(store, month)` is unique and
    setting a target again corrects it. There is no delete, because a store's
    month always has a number even when that number is nought.

    Both verbs gate on **entitlement**, not on the top-bar switcher, and that is
    the one thing about this view worth reading twice.

    The grid's rows come from the store master (`scoped_stores`, which says in its
    own docstring that it is "deliberately *not* narrowed by the active unit").
    Its cells come from here. Gate the two differently and they disagree: an
    Operations Head with Deoghar picked in the top bar would get all fifty store
    rows with only Deoghar's numbers in them, every other cell reading as "no
    target set" for a target that exists, and the year's total quietly collapsing
    to one store. A screen that hides committed money behind a header nobody
    thought they were filtering with is worse than one that refuses.

    So this endpoint follows the master it is keyed on rather than the reading
    convention for documents: one financial year of targets is a single HO
    decision, and you do not look at one store's column of it at a time. Scope is
    still the boundary - a store-scoped caller sees their own store and no other,
    which is the acceptance criterion - the switcher simply gets no vote. Callers
    who want one store ask for it by name with `?store=`.
    """

    permission_classes = [IsAuthenticated, CanReadOrSetStoreTarget]

    def get(self, request: Request) -> Response:
        rows = scope_by_entitlement(
            StoreTarget.objects.select_related("store"), request.user, "store_id"
        )
        code = (request.query_params.get("store") or "").strip()
        if code:
            # Narrows *within* scope: the filter is applied after the gate, so
            # naming another store's code answers with nothing rather than with
            # that store's target.
            rows = rows.filter(store__code__iexact=code)
        fy = (request.query_params.get("fy") or "").strip()
        if fy:
            try:
                months = financial_year_months(fy)
            except ValueError as exc:
                return _refuse("VALIDATION", str(exc), 400)
            rows = rows.filter(month__in=months)
        return Response(StoreTargetSerializer(rows, many=True).data)

    def put(self, request: Request) -> Response:
        form = StoreTargetWriteSerializer(data=request.data)
        if not form.is_valid():
            return _refuse("VALIDATION", _first_message(form.errors), 400)
        code = form.validated_data["store"]
        store = Store.objects.filter(code__iexact=code, is_active=True).first()
        if store is None:
            # A closed store is not a store to plan against, so it answers the
            # same as one that never existed. The contract says only "store must
            # exist"; refusing the closed ones too is deliberate.
            return _refuse("NOT_FOUND", f"No active store with code '{code}'.", 404)
        # Beyond the contract's own steps, deliberately: `money: manage` says what
        # a person may do, never where. Without this, one rung would set targets
        # for stores the admin never entitled them to.
        entitled = scope_by_entitlement(Store.objects.filter(pk=store.pk), request.user, "id")
        if not entitled.exists():
            return _refuse("SCOPE_DENIED", f"{store.code} is not one of your locations.", 403)
        target, _ = StoreTarget.objects.update_or_create(
            store=store,
            month=form.validated_data["month"],
            defaults={
                "target_paise": form.validated_data["target_paise"],
                "set_by": request.user,
            },
        )
        return Response(StoreTargetSerializer(target).data)


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
