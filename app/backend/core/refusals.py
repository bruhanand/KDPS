"""The D10 refusal body: a sentence for the person, a code for the caller.

Deliberately not DRF's ``{"detail": ...}``. The till replays writes from a
durable queue and has to tell "retry forever" from "this bill needs a human",
which it does on the code, never on the prose (`api-contract.md`, conventions).

Lives in `core` because it is a wire convention rather than any one app's rule,
and because the two callers that share it today - the store-target grid in
`masters` and the dashboard in `storefront` - have no other place they both
already import. It was private to `masters.views` while that was the only
endpoint using it, with a note saying it would move here when the second one
landed; this is that move.
"""

from __future__ import annotations

from typing import Any

from rest_framework.response import Response


def refuse(code: str, message: str, status: int) -> Response:
    """One refusal, in the shape every D10 endpoint answers with."""
    return Response({"error": message, "code": code}, status=status)


def first_message(errors: Any) -> str:
    """The first sentence out of a DRF error tree, flattened.

    A refusal body carries one message, and a serializer's is keyed by field. The
    first one is the one the person needs: these forms are three fields wide, and
    a screen that fixes the named field re-submits and hears about the next.
    """
    if isinstance(errors, dict):
        for value in errors.values():
            found = first_message(value)
            if found:
                return found
        return ""
    if isinstance(errors, list):
        for item in errors:
            found = first_message(item)
            if found:
                return found
        return ""
    return str(errors).strip()
