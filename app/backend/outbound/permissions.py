"""Outbound RBAC — one gate per endpoint group, plus store-scope enforcement.

There is no outbound role list. Every write resolves through the *same* section
capability that shapes the caller's sidebar (``require_section``, issue #85), so
a screen and the API behind it can no longer disagree — and Accounts, which the
matrix gives ``view`` on stock, transfers, counting and returns, can no longer
write in any of them (#94).

The mapping, read straight off the ratified SIDEBAR RBAC matrix:

============================================  ===========================
Endpoint group                                Gate
============================================  ===========================
Transfer create / submit / dispatch / receive ``transfer: operate``
Transfer PT read / download                   ``transfer: view``
Transfer gap closure raise / post             ``transfer: approve``
Mark damaged                                  ``return_to_brand: operate``
Return to brand create / submit               ``return_to_brand: operate``
Adjustment create / submit                    ``stock_count: operate``
Write-off create / submit                     ``stock_count: operate``
V-flip create / submit                        ``stock: manage``
============================================  ===========================

Two consequences are deliberate, not accidents. The ladder is ordinal, so a role
holding ``approve`` clears an ``operate`` gate — which is why a brand manager
(``transfer: approve``) may move stock. And V-flip sits at ``stock: manage``,
which the design settled as an ownership relabel of stock that stays put: that
adds the warehouse and drops HO ops. Both follow the matrix; if either is wrong
it is a matrix change, not an exception here.

Reads are otherwise unchanged — any authenticated user (DRF's own
``IsAuthenticated``; outbound has no general read rule of its own), store-scoped
at the queryset. The transfer PT is the one exception above, and only because it
is a priced file people download and forward.

Store scope is a separate, unchanged concern: ``enforce_store_scope`` still runs
on every write, so holding the rung never means holding it *everywhere*.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from accounts.actor_policies import user_may_act
from accounts.permissions import require_section
from accounts.sections import CAP_APPROVE, CAP_MANAGE, CAP_OPERATE, CAP_VIEW
from masters.scoping import actionable_store_ids

#: Moving stock between locations — the transfer section's daily work.
CanWriteTransfer = require_section("transfer", CAP_OPERATE)

#: Reading a transfer's PT — the packing document, priced (#72). Gated at the
#: section's lowest rung rather than left open: the file carries unit costs, so
#: somebody the matrix gives no transfer cell at all has no business opening it.
#: This is deliberately stricter than the transfer document itself, which sits on
#: the pre-existing ungated baseline; whether *that* should stay open is the same
#: question for every outbound detail read, and belongs with #104, not here.
CanReadTransferPT = require_section("transfer", CAP_VIEW)

#: Deciding what became of pieces that went missing between two locations. A rung
#: above the daily work on purpose: the design gives gap closure to the Operations
#: Head, so the person who sent or received the carton must not be able to write
#: off their own shortfall. Seniority is all this expresses — the separate rule
#: that bars anyone entitled to the *receiving* store, senior or not, is enforced
#: in ``posting._refuse_self_closure`` so a shell hits it too (#71).
CanCloseTransferGap = require_section("transfer", CAP_APPROVE)

#: Marking damage and returning it to the brand are the same section's work:
#: the matrix's "Mark damage only" cell is the store person's rung on it.
CanWriteReturnToBrand = require_section("return_to_brand", CAP_OPERATE)

#: Adjustments and write-offs are both corrections that a count produces.
CanWriteStockCount = require_section("stock_count", CAP_OPERATE)

#: V-flip relabels who owns stock that never moves — an action on Stock itself,
#: at the rung that owns the section rather than merely operates in it.
CanFlipOwnership = require_section("stock", CAP_MANAGE)


class CanExecuteVFlip(BasePermission):
    """Live policy above the immutable Accounts/Owner value-posting floor."""

    message = "Only an allowed Accounts or Owner user may execute a V-flip."

    def has_permission(self, request, view):
        return user_may_act(request.user, "outbound.execute_vflip")


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
