"""The D10 refusal body: a sentence for the person, a code for the caller.

Deliberately not DRF's ``{"detail": ...}``. The till replays writes from a
durable queue and has to tell "retry forever" from "this bill needs a human",
which it does on the code, never on the prose (`api-contract.md`, conventions).

Lives in `core` because it is a wire convention rather than any one app's rule,
and the two endpoints that share it today - the store-target grid in `masters`
and the dashboard in `storefront` - have no nearer place they both already
import. It was private to `masters.views` while that was the only caller, with a
note saying it would move here when the second one landed; this is that move.

**Nothing here imports a web framework**, and that is the whole reason it is a
body-builder rather than a response-builder. `core` is the kernel: it may not
learn about HTTP, and this module would otherwise be the first thing in it to
import DRF. So the *shape* lives here, once, and each view does its own
`Response(refusal_body(...), status=...)` - which also keeps the status beside
the branch that chose it, where each contract's error table puts it.
"""

from __future__ import annotations

from typing import Any


def refusal_body(code: str, message: str) -> dict[str, str]:
    """One refusal, in the shape every D10 endpoint answers with.

    ``error`` is first so that a client walking the body in order meets the
    sentence before the code; no caller may *rely* on that order, and the PWA's
    `apiErrorMessage` reads `error` by name.
    """
    return {"error": message, "code": code}


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
