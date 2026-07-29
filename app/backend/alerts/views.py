"""Alerts API — the one feed Home's Alerts surface reads (#77).

    GET /api/alerts    everything open, scoped to *me*

No decide endpoint: an alert is not approved or rejected, it is just read —
the job that raised it is also the job that resolves it once it stops being
true (``alerts.checks``).
"""

from __future__ import annotations

from typing import Any

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import require_section
from accounts.sections import CAP_VIEW
from masters.scoping import scope_by_store_or_brand

from .models import Alert, AlertStatus
from .serializers import AlertReadSerializer


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
