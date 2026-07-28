"""Approvals API — one inbox for the whole system (#70).

Three endpoints, no per-document-type variants:

    GET  /api/approvals/inbox        everything waiting for *me*
    GET  /api/approvals              the audit view (mine + my stores'), filterable
    POST /api/approvals/<pk>/decide  approve / reject (reason required on reject)

Deciding writes the approval and nothing else. The document's own approver
column is stamped by the module that owns it, at post time (ADR-0002: a
module's database is private) — so a *rejected* document is never stamped with
the name of the person who refused it.
"""

from __future__ import annotations

from typing import Any

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from approvals.models import Approval
from approvals.serializers import ApprovalDecisionSerializer, ApprovalReadSerializer
from approvals.services import (
    ApprovalError,
    ApprovalRightsError,
    decide,
    inbox_for,
)
from core.textsearch import search_term, text_filter
from masters.scoping import scope_by_entitlement_or_brand, scope_by_store_or_brand

#: Approvals (#106) — this model has no `doc_number` column of its own; `title`
#: is the requesting module's snapshot one-liner and the nearest stand-in.
#: "Type" is `kind_label` (the human label; `kind` is the machine code the
#: client routes on). "Requester" is `requested_by`.
APPROVAL_SEARCH_FIELDS = (
    "title",
    "kind_label",
    "requested_by__full_name",
    "requested_by__username",
)


class ApprovalInboxView(generics.ListAPIView[Approval]):
    """The one "waiting for you" screen. Never lists the caller's own requests —
    a self-approval can't succeed, so it is never offered."""

    permission_classes = [IsAuthenticated]
    serializer_class = ApprovalReadSerializer
    pagination_class = None

    def get_queryset(self) -> Any:
        qs = inbox_for(self.request.user)
        # The screen's own search box (#102), applied last so it can only
        # narrow what the inbox's own scoping already allows.
        return text_filter(qs, search_term(self.request), APPROVAL_SEARCH_FIELDS)


class ApprovalListView(generics.ListAPIView[Approval]):
    """History across every document type, store-scoped (ADR-0003). Includes the
    caller's own requests — the maker must be able to watch their own decision."""

    permission_classes = [IsAuthenticated]
    serializer_class = ApprovalReadSerializer
    pagination_class = None

    def get_queryset(self) -> Any:
        qs = Approval.objects.select_related("store", "requested_by", "decided_by")
        qs = scope_by_store_or_brand(qs, self.request.user)
        st = self.request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        # The screen's own search box (#102), applied last.
        return text_filter(qs, search_term(self.request), APPROVAL_SEARCH_FIELDS)


class ApprovalDecideView(APIView):
    """POST: approve or reject one approval as the signed-in user."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        # Scope first: an out-of-scope approval must look like it doesn't exist.
        # By entitlement, not by the switcher — deciding is an act, and the unit
        # on screen must not narrow what the caller may act on. Or-brand, because
        # the brand manager the return policy names is bounded by brands and
        # would otherwise be scoped out of every row (#75).
        visible = scope_by_entitlement_or_brand(Approval.objects.all(), request.user)
        try:
            approval = visible.get(pk=pk)
        except Approval.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        ser = ApprovalDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            approval = decide(
                approval,
                actor=request.user,
                action=ser.validated_data["action"],
                reason=ser.validated_data.get("reason", ""),
            )
        except ApprovalRightsError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ApprovalError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ApprovalReadSerializer(approval).data)
