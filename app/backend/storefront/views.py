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
from core.refusals import refuse
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
        code = (request.query_params.get("store") or "").strip()
        store = resolve_store(request.user, code)
        if store is None:
            return refuse("SCOPE_DENIED", _why(code), 403)
        return Response(build(request.user, store))


def _why(code: str) -> str:
    """Two different refusals wear one code, so the sentence has to do the work
    of telling them apart: a store you may not see, versus no store named at
    all."""
    if code:
        return f"{code} is not one of your locations."
    return "Pick a store first — this screen is one store's day, not the network's."
