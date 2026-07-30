"""The store-facing read-only aggregator (D10 §2).

No models, no writes. See `storefront/dashboard.py` for what the payload is made
of and why three of the contract's action-queue keys are not in it yet.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import require_section
from accounts.sections import CAP_VIEW
from core.refusals import refusal_body
from storefront.dashboard import build, resolve_store


class DashboardView(APIView):
    """`GET /api/store/dashboard` - one store's Home.

    Gated on `home: view`, the section every role holds, because the dashboard is
    a window onto work the person can already reach: each card is a count of rows
    some other gate has already decided they may see, and the two blocks that are
    not - the money tiles and the manager row - carry their own answer (the tiles
    are nought until the POS lands; the manager row is `sell >= approve`).

    Refuses with `SCOPE_DENIED` and nothing else. A store with no transfers, no
    approvals and no target is not an error - it is a quiet morning, and it
    renders as noughts.
    """

    permission_classes = [IsAuthenticated, require_section("home", CAP_VIEW)]

    def get(self, request: Request) -> Response:
        pick = resolve_store(request.user, (request.query_params.get("store") or "").strip())
        if pick.store is None:
            # Three refusals wear one code, so the sentence has to tell them
            # apart. It comes back from the resolver rather than being worked out
            # again here: only the branch that ruled a store out knows which of
            # the three happened.
            return Response(refusal_body("SCOPE_DENIED", pick.refusal), status=403)
        return Response(build(request.user, pick.store))
