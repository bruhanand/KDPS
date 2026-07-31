"""Alerts API — the one feed Home's Alerts surface and the bell read (#77, #226).

    GET  /api/alerts          everything open, scoped to *me*
    GET  /api/alerts/history  everything resolved in a window, same scope
    GET  /api/alerts/seen     where my read cursor stands
    POST /api/alerts/seen     move it to now

No decide endpoint: an alert is not approved or rejected, it is just read —
the job that raised it is also the job that resolves it once it stops being
true (``alerts.checks``). "Read", though, is a fact somebody has to record, and
that is the whole of ``AlertSeen``: the bell's unread badge counts open alerts
newer than the caller's stamp, so without one there is nothing to count from.

All four sit behind the same gate, ``home: view`` — history and the cursor
interpret the very feed they guard, and a second, looser door onto the same rows
is how a store person ends up reading another store's history.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import require_section
from accounts.sections import CAP_VIEW
from core.dates import parse_day, since_refusal
from masters.scoping import scope_by_store_or_brand

from .models import Alert, AlertSeen, AlertStatus
from .serializers import AlertReadSerializer

#: How far History looks back when nobody says — the popup's own default range,
#: named once so the client's "7 days" button and a bare call agree.
DEFAULT_HISTORY_DAYS = 7


class AlertInboxView(generics.ListAPIView[Alert]):
    """Open alerts, scoped exactly like the approvals inbox (ADR-0003): a
    store-scoped user sees their own store's, a brand-scoped user sees their
    own brands', HO sees the network. Gated on the Home section (#77) — the
    same section Approvals lives in."""

    permission_classes = [IsAuthenticated, require_section("home", CAP_VIEW)]
    serializer_class = AlertReadSerializer
    pagination_class = None

    def get_queryset(self) -> Any:
        qs = Alert.objects.filter(status=AlertStatus.OPEN).select_related("store")
        return scope_by_store_or_brand(qs, self.request.user)


class AlertHistoryView(APIView):
    """Resolved alerts, newest first, within a window (#226).

    The other half of the same lifecycle the inbox shows, through the *same*
    scope call — history that answered a wider question than the live feed would
    let a store person read another store's problems a day late, which is the
    same leak with a delay on it.

    An ``APIView`` rather than a ``ListAPIView`` because a bad ``?since=`` is a
    refusal with a code, and a generic list has nowhere to say so.
    """

    permission_classes = [IsAuthenticated, require_section("home", CAP_VIEW)]

    def get(self, request: Request) -> Response:
        asked = (request.query_params.get("since") or "").strip()
        if asked:
            since = parse_day(asked)
            if since is None:
                return Response(since_refusal(asked), status=status.HTTP_400_BAD_REQUEST)
        else:
            since = timezone.localdate() - timedelta(days=DEFAULT_HISTORY_DAYS)
        rows = Alert.objects.filter(
            status=AlertStatus.RESOLVED, resolved_at__date__gte=since
        ).select_related("store")
        rows = scope_by_store_or_brand(rows, request.user).order_by("-resolved_at")
        return Response(AlertReadSerializer(rows, many=True).data)


class AlertSeenView(APIView):
    """The caller's read cursor: GET where it stands, POST to move it to now.

    The stamp is the *server's* clock, never a time sent up: a browser whose
    clock runs fast would otherwise mark alerts read before they were raised,
    and the badge would sit at zero through a real problem.
    """

    permission_classes = [IsAuthenticated, require_section("home", CAP_VIEW)]

    def get(self, request: Request) -> Response:
        row = AlertSeen.objects.filter(user=request.user).first()
        return Response({"seen_at": row.seen_at if row else None})

    def post(self, request: Request) -> Response:
        # Idempotent by design — the tab is opened a dozen times a day, and each
        # opening simply moves the one row forward.
        row, _ = AlertSeen.objects.update_or_create(
            user=request.user, defaults={"seen_at": timezone.now()}
        )
        return Response({"seen_at": row.seen_at})
