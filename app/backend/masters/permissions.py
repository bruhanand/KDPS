"""Who may edit master data (ADR-0003 / Rule 12).

Lifted out of ``masters.views`` so the *vendor* master — which lives in the
``vendors`` app because a vendor carries bookings — can be gated by the same
rule as stores, brands, seasons and GSTINs. Before this, ``/api/vendors``
answered any authenticated caller on POST: a store cashier could mint a supplier
that every future booking, GRN and payable then hangs off.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from accounts.role_lists import declare_role_list

STEWARD_ROLES = declare_role_list(
    "masters.writes",
    ("owner", "it_admin", "data_steward"),
    reason=(
        "The matrix's Setup grants are *scoped* — the warehouse holds "
        "'Products only' and a brand manager 'Edit assigned products', both at "
        "`setup: operate`. One Setup rung cannot carry per-model or per-brand "
        "scope, so widening master-data writes to `setup: operate` would hand "
        "them store, GSTIN, vendor and legal-entity edits. Parked in #104."
    ),
)


class IsMasterSteward(BasePermission):
    """Read-open, write-gated to master-data stewards.

    Reads stay open because every screen that *uses* a master needs to list it —
    the booking form needs vendors, the receive form needs stores. Only the
    edit is a stewardship act.
    """

    message = "Master-data steward role required (owner / IT admin / data steward)."

    def has_permission(self, request: Request, view: Any) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        role = getattr(getattr(user, "role", None), "code", "")
        return bool(user.is_superuser or role in STEWARD_ROLES)
