"""Outbound RBAC permission classes + store-scope enforcement.

Role matrix
-----------
Read (list/detail):
    All authenticated users with ``outbound`` nav-group (store-scoped for
    store-level users, full for network roles).

Write (create / submit / dispatch / receive):
    owner, it_admin, ho_ops, accounts, store_manager, warehouse.
    store_manager + warehouse are further limited to their own store scope.

Admin write (V-flip, write-off):
    owner, it_admin, ho_ops, accounts only.  Store-level roles must not
    convert ownership or write off stock — these are finance/HO decisions.

store_staff is READ-ONLY on all outbound surfaces.

Store-scope:
    Store-scoped roles (store_manager, warehouse, store_staff) may only
    write against stores in their ``user.stores`` M2M.  Network roles
    (scope_type='all', superuser) are unrestricted.  ``enforce_store_scope``
    is the single shared gate — every outbound write view calls it.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from masters.scoping import visible_store_ids

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


def enforce_store_scope(user, store_id: int) -> None:
    """Raise 403 if the user's store scope excludes ``store_id``.

    Network roles (visible_store_ids → None) pass unconditionally.
    Store-scoped users must have ``store_id`` in their assigned set.
    """
    allowed = visible_store_ids(user)
    if allowed is None:
        return  # unrestricted
    if store_id not in allowed:
        raise PermissionDenied(
            "You do not have permission to operate on this store."
        )


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
