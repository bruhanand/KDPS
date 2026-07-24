"""Approvals API — one inbox for the whole system (#70).

Three endpoints, no per-document-type variants:

    GET  /api/approvals/inbox        everything waiting for *me*
    GET  /api/approvals              the audit view (mine + my stores'), filterable
    POST /api/approvals/<pk>/decide  approve / reject (reason required on reject)
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from approvals.models import Approval
from approvals.serializers import ApprovalDecisionSerializer, ApprovalReadSerializer
from approvals.services import (
    ApprovalError,
    SelfApprovalError,
    decide,
    inbox_for,
)


class ApprovalInboxView(generics.ListAPIView[Approval]):
    """The one "waiting for you" screen. Never lists the caller's own requests —
    a self-approval can't succeed, so it is never offered."""

    permission_classes = [IsAuthenticated]
    serializer_class = ApprovalReadSerializer
    pagination_class = None

    def get_queryset(self) -> Any:
        return inbox_for(self.request.user)


class ApprovalListView(generics.ListAPIView[Approval]):
    """History across every document type, store-scoped (ADR-0003). Includes the
    caller's own requests — the maker must be able to watch their own decision."""

    permission_classes = [IsAuthenticated]
    serializer_class = ApprovalReadSerializer
    pagination_class = None

    def get_queryset(self) -> Any:
        from masters.scoping import scope_by_store

        qs = Approval.objects.select_related("store", "requested_by", "decided_by")
        qs = scope_by_store(qs, self.request.user, "store_id")
        st = self.request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs


class ApprovalDecideView(APIView):
    """POST: approve or reject one approval as the signed-in user."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        from masters.scoping import scope_by_store

        # Scope first: an out-of-scope approval must look like it doesn't exist.
        visible = scope_by_store(Approval.objects.all(), request.user, "store_id")
        try:
            approval = visible.get(pk=pk)
        except Approval.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        ser = ApprovalDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            # One transaction: a decided approval and the stamp it leaves on the
            # document land together or not at all.
            with transaction.atomic():
                approval = decide(
                    approval,
                    actor=request.user,
                    action=ser.validated_data["action"],
                    reason=ser.validated_data.get("reason", ""),
                )
                _stamp_subject(approval)
        except SelfApprovalError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ApprovalError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ApprovalReadSerializer(approval).data)


def _stamp_subject(approval: Approval) -> None:
    """Write the decider onto the document's own approver column, when it has
    one, so the document reads truthfully on its own page and in Tally exports.

    Duck-typed on purpose: ``approvals`` must not import any business app. A
    subject with no approver column simply isn't stamped — its approval record
    is still the record of truth.
    """
    subject = approval.subject
    if subject is None:
        return
    for field in ("approved_by", "authorized_by"):
        if any(f.name == field for f in subject._meta.fields):
            setattr(subject, field, approval.decided_by)
            subject.save(update_fields=[field])
            return
