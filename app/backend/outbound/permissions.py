"""Outbound RBAC permission classes.

Role matrix
-----------
Read (list/detail):
    All authenticated users with ``outbound`` nav-group (store-scoped for
    store-level users, full for network roles).

Write (create / submit / dispatch / receive):
    owner, it_admin, ho_ops, accounts, store_manager, warehouse.
    store_manager + warehouse are further limited to their own store scope
    (enforced by ``scope_by_store`` in the view queryset, not here).

Admin write (V-flip, write-off):
    owner, it_admin, ho_ops, accounts only.  Store-level roles must not
    convert ownership or write off stock — these are finance/HO decisions.

store_staff is READ-ONLY on all outbound surfaces.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

# Roles that may create, submit, dispatch, receive outbound docs.
OUTBOUND_WRITE_ROLES = frozenset({
    "owner", "it_admin", "ho_ops", "accounts",
    "store_manager", "warehouse",
})

# Roles that may perform V-flip (ownership conversion) and write-offs.
OUTBOUND_ADMIN_ROLES = frozenset({
    "owner", "it_admin", "ho_ops", "accounts",
})


def _role_code(user) -> str:
    return getattr(getattr(user, "role", None), "code", "")


class IsOutboundReader(BasePermission):
    """Any authenticated user may read outbound docs (list/detail).

    Store scoping is handled at the queryset level, not here.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsOutboundWriter(BasePermission):
    """Create, submit, dispatch, receive — requires a write-capable role."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        return _role_code(user) in OUTBOUND_WRITE_ROLES


class IsOutboundAdmin(BasePermission):
    """V-flip and write-off — requires an admin-level role."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        return _role_code(user) in OUTBOUND_ADMIN_ROLES
