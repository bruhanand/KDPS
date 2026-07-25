"""Fail-closed data scoping (ADR-0003), kept out of any view module so apps don't
peer-import each other. A user is scoped all / entity / region / store_group /
store / brand over LegalEntity → GSTIN → Store; an unrecognised or empty scope
resolves to *no rows*, never to everything.

Two layers, deliberately separate (issue #88):

  · **scope** — `visible_store_ids` / `visible_brand_names`: everything this
    person may ever see. Admin-set data; the permission boundary.
  · **context** — `active_store_ids` / `active_brand_names`: the one unit (or
    brand) they picked in the top-bar switcher for *this* request. Always the
    intersection with scope, so the header can only ever narrow.

Queries scope by context (`scope_by_store`, `scope_by_brand`); write-permission
checks scope by the boundary (`visible_store_ids`) — you may still post to any
store you are entitled to, whichever one the switcher happens to be showing.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from masters.models import Brand, Store
from masters.unit_context import active_brand_name, active_unit_code

# Brand-scoped users (a brand manager) are not tied to stores — their scope is a
# set of brands, network-wide. Kept as a literal so `masters` never imports
# `accounts` (the FK already points the other way).
BRAND_SCOPE = "brand"


def visible_store_ids(user: Any) -> list[int] | None:
    """Store ids the user may see, or None meaning 'all stores' (no restriction)."""
    if getattr(user, "is_superuser", False):
        return None
    scope = getattr(user, "scope_type", None)
    if scope == "all":
        return None
    if scope == BRAND_SCOPE:
        # Network-wide across stores; what narrows a brand manager is the brand,
        # not the store (see `visible_brand_names`).
        return None
    if scope == "entity" and getattr(user, "entity_id", None):
        return list(
            Store.objects.filter(gstin__legal_entity_id=user.entity_id).values_list("id", flat=True)
        )
    # store / store_group / region → explicit membership; empty ⇒ sees nothing
    return list(user.stores.values_list("id", flat=True))


def visible_brand_names(user: Any) -> list[str] | None:
    """Brand names the user is limited to, or None meaning 'every brand'."""
    if getattr(user, "is_superuser", False):
        return None
    if getattr(user, "scope_type", None) != BRAND_SCOPE:
        return None
    return list(user.brands.filter(is_active=True).values_list("name", flat=True))


def scoped_stores(user: Any) -> Any:
    """Every store the user may see — the switcher's list of units, and the
    store pickers'. Deliberately *not* narrowed by the active unit: you pick a
    unit out of this list, so narrowing it by the pick would collapse it."""
    qs = Store.objects.filter(is_active=True).select_related("gstin")
    ids = visible_store_ids(user)
    return qs if ids is None else qs.filter(id__in=ids)


def scoped_brands(user: Any) -> Any:
    """Every brand the user is assigned — the brand manager's filter list."""
    qs = Brand.objects.filter(is_active=True)
    names = visible_brand_names(user)
    return qs if names is None else qs.filter(name__in=names)


def active_store_ids(user: Any) -> list[int] | None:
    """The store ids this request may read: the caller's scope, narrowed to the
    unit chosen in the switcher. None means 'no restriction' (network view).

    Raises 403 rather than silently widening or silently emptying: a unit that
    does not exist, or one outside the caller's scope, is an answer they must
    never get.
    """
    visible = visible_store_ids(user)
    code = active_unit_code()
    if not code:
        return visible
    store_id = Store.objects.filter(code=code, is_active=True).values_list("id", flat=True).first()
    if store_id is None:
        raise PermissionDenied(f"Unknown business unit '{code}'.")
    if visible is not None and store_id not in visible:
        raise PermissionDenied("You may not work in this business unit.")
    return [store_id]


def active_brand_names(user: Any) -> list[str] | None:
    """Brand names this request may read: assigned brands, narrowed to the one
    chosen in the switcher. None means 'no brand restriction'."""
    allowed = visible_brand_names(user)
    chosen = active_brand_name()
    if not chosen:
        return allowed
    if allowed is not None and not any(name.lower() == chosen.lower() for name in allowed):
        raise PermissionDenied("You may not work in this brand.")
    return [chosen]


def scope_by_store(qs: Any, user: Any, field: str = "store_id") -> Any:
    """Restrict a queryset to the unit the user is acting in (fail-closed)."""
    ids = active_store_ids(user)
    return qs if ids is None else qs.filter(**{f"{field}__in": ids})


def scope_by_brand(qs: Any, user: Any, field: str = "brand") -> Any:
    """Restrict a queryset to the brands the user is acting in (fail-closed).

    Stock rows carry the brand as the name printed on the PT (`PETER ENGLAND`),
    not a foreign key, so the match is case-insensitive against the master name.
    A brand-scoped user with no brands assigned sees nothing.
    """
    names = active_brand_names(user)
    if names is None:
        return qs
    if not names:
        return qs.none()
    match = Q()
    for name in names:
        match |= Q(**{f"{field}__iexact": name})
    return qs.filter(match)
