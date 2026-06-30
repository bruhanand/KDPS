"""Fail-closed data scoping (ADR-0003), kept out of any view module so apps don't
peer-import each other. A user is scoped all / entity / region / store_group /
store over LegalEntity → GSTIN → Store; an unrecognised or empty scope resolves
to *no rows*, never to everything."""

from __future__ import annotations

from typing import Any

from masters.models import Store


def visible_store_ids(user: Any) -> list[int] | None:
    """Store ids the user may see, or None meaning 'all stores' (no restriction)."""
    if getattr(user, "is_superuser", False):
        return None
    scope = getattr(user, "scope_type", None)
    if scope == "all":
        return None
    if scope == "entity" and getattr(user, "entity_id", None):
        return list(
            Store.objects.filter(gstin__legal_entity_id=user.entity_id).values_list("id", flat=True)
        )
    # store / store_group / region → explicit membership; empty ⇒ sees nothing
    return list(user.stores.values_list("id", flat=True))


def scoped_stores(user: Any) -> Any:
    qs = Store.objects.filter(is_active=True).select_related("gstin")
    ids = visible_store_ids(user)
    return qs if ids is None else qs.filter(id__in=ids)


def scope_by_store(qs: Any, user: Any, field: str = "store_id") -> Any:
    """Restrict a queryset to the user's stores (fail-closed)."""
    ids = visible_store_ids(user)
    return qs if ids is None else qs.filter(**{f"{field}__in": ids})
