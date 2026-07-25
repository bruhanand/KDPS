"""Outbound RBAC — one gate per endpoint group, plus store-scope enforcement.

There is no outbound role list. Every write resolves through the *same* section
capability that shapes the caller's sidebar (``require_section``, issue #85), so
a screen and the API behind it can no longer disagree — and Accounts, which the
matrix gives ``view`` on stock, transfers, counting and returns, can no longer
write in any of them (#94).

The mapping, read straight off the ratified SIDEBAR RBAC matrix:

===========================================  =========================
Endpoint group                               Gate
===========================================  =========================
Transfer create / submit / dispatch / receive ``transfer: operate``
Mark damaged                                  ``return_to_brand: operate``
Return to brand create / submit               ``return_to_brand: operate``
Adjustment create / submit                    ``stock_count: operate``
Write-off create / submit                     ``stock_count: operate``
V-flip create / submit                        ``stock: manage``
===========================================  =========================

Two consequences are deliberate, not accidents. The ladder is ordinal, so a role
holding ``approve`` clears an ``operate`` gate — which is why a brand manager
(``transfer: approve``) may move stock. And V-flip sits at ``stock: manage``,
which the design settled as an ownership relabel of stock that stays put: that
adds the warehouse and drops HO ops. Both follow the matrix; if either is wrong
it is a matrix change, not an exception here.

Reads are unchanged — any authenticated user, store-scoped at the queryset.

Store scope is a separate, unchanged concern: ``enforce_store_scope`` still runs
on every write, so holding the rung never means holding it *everywhere*.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from accounts.permissions import require_section
from accounts.sections import CAP_MANAGE, CAP_OPERATE
from masters.scoping import actionable_store_ids

#: Moving stock between locations — the transfer section's daily work.
CanWriteTransfer = require_section("transfer", CAP_OPERATE)

#: Marking damage and returning it to the brand are the same section's work:
#: the matrix's "Mark damage only" cell is the store person's rung on it.
CanWriteReturnToBrand = require_section("return_to_brand", CAP_OPERATE)

#: Adjustments and write-offs are both corrections that a count produces.
CanWriteStockCount = require_section("stock_count", CAP_OPERATE)

#: V-flip relabels who owns stock that never moves — an action on Stock itself,
#: at the rung that owns the section rather than merely operates in it.
CanFlipOwnership = require_section("stock", CAP_MANAGE)


def enforce_store_scope(user, store_id: int) -> None:
    """Raise 403 if the user's store scope excludes ``store_id``.

    Network roles (actionable_store_ids → None) pass unconditionally; a
    brand-scoped user resolves to no stores and is refused.
    Store-scoped users must have ``store_id`` in their assigned set.
    """
    allowed = actionable_store_ids(user)
    if allowed is None:
        return  # unrestricted
    if store_id not in allowed:
        raise PermissionDenied("You do not have permission to operate on this store.")


class IsOutboundReader(BasePermission):
    """Any authenticated user may read outbound docs (list/detail).

    Store scoping is handled at the queryset level, not here.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
