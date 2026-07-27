"""Read scope for outbound documents (issue #141) — one predicate per type.

Writing an outbound document has always been gated (`enforce_store_scope`);
reading one was not, so the Deoghar manager's Transfers screen listed a move
between two other stores and any voucher id opened. The gates live here, above
the views, for one reason: the top-bar search registry (`search.views`) narrows
exactly the same documents, and a predicate written twice is a predicate that
drifts. The `#101` rewrite found the booking predicate hand-copied three times.

Nothing here decides *policy* — that is `masters.scoping`, which resolves the
caller's stores, honours the top-bar switcher and fails a brand-scoped caller
closed. This module only says **where a document's store lives** when the answer
is not the plain `store_id` field.

The store-owned documents (return to brand, adjustment, write-off, V-flip, mark
damaged) need nothing here at all: they carry `store_id`, so their views call
`masters.scoping.scope_by_store` directly.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from masters.scoping import active_store_ids, is_brand_scoped


def transfer_at_stores(store_ids: list[int]) -> Q:
    """A transfer belongs to **both ends of the move**.

    The sender is answerable for the pieces and the receiver is expecting them,
    so either end may read it — matching the top-bar search, and the reason this
    document cannot go through the plain `store_id` gate.
    """
    return Q(source_store_id__in=store_ids) | Q(destination_store_id__in=store_ids)


def scope_transfers(qs: Any, user: Any) -> Any:
    """Restrict a transfer queryset to the caller's own end of the move.

    The reading counterpart of `masters.scoping.scope_by_store`, differing only in
    which field carries the store — so the brand-scoped branch fails closed the
    same way: a transfer carries no brand, nothing can prove a row is theirs, and
    "stores are the wrong question" must never resolve to "so show every store"
    (ADR-0003). #110 replaces that interim with cross-by-brand.
    """
    if is_brand_scoped(user):
        return qs.none()
    ids = active_store_ids(user)
    return qs if ids is None else qs.filter(transfer_at_stores(ids))
