"""The refusal body every till-facing endpoint answers with — a sentence for the
person, a code for the caller.

The shape is the D10 contract's: ``{"error": "<human message>", "code":
"<ERROR_CODE>"}``, deliberately not DRF's ``{"detail": ...}``. The reason is the
till. It replays writes from a durable queue, and on a 4xx it has to tell "retry
forever" from "this bill needs a human" — a decision it makes on the code, never
on the prose, because the prose is written for the person reading the exception
card and will change.

It lives in the kernel for the same reason ``core.textsearch`` does: more than
one app answers this way, none of them may import each other, and a convention
copied is a convention that drifts. `masters.views` wrote the first copy (#171)
and said in its own docstring that it should move here when the second one
landed; the sale (#177) is the second.
"""

from __future__ import annotations

from typing import Any

from rest_framework.response import Response


def refuse(code: str, message: str, status: int) -> Response:
    """A refusal carrying both halves: the sentence and the machine-readable code."""
    return Response({"error": message, "code": code}, status=status)


def first_message(errors: Any) -> str:
    """The first sentence out of a DRF error tree, flattened.

    A refusal body carries one message, and a serializer's is keyed by field. The
    first one is the one the person needs: a screen that fixes the named field
    re-submits and hears about the next.
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
