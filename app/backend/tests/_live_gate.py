"""Is the server the live suites are about to drive the same code as this checkout?

Split out of ``conftest.py`` so the comparison can be tested directly, without a
server to point at. ``conftest`` does the HTTP; this module does the judging.

The rule (issue #93): a disagreement is an *environment* problem, so it produces
a skip that names what differs - never a silent pass, and never a local failure
that would put a red mark against a tree that is perfectly fine.
"""

from __future__ import annotations

from collections.abc import Sequence

RESTART_HINT = "Restart it from this working tree: ./scripts/dev.sh --api"


def _summarise(migrations: Sequence[str], limit: int = 4) -> str:
    head = ", ".join(migrations[:limit])
    rest = len(migrations) - limit
    return f"{head} (+{rest} more)" if rest > 0 else head


def mismatch_reason(
    reported: object,
    *,
    target: str,
    our_names: Sequence[str],
    our_digest: str,
) -> str | None:
    """Why the server at ``target`` is not this checkout - or None when it is.

    ``reported`` is whatever ``/api/health`` put under ``migrations``: a dict with
    ``digest`` and ``count``, plus ``names`` when the server is willing to publish
    them. Anything else means the server predates this check, which by itself
    proves it is older than this checkout.
    """
    if not isinstance(reported, dict):
        return (
            f"the server at {target} does not report a migration identity on /api/health, "
            f"so it predates issue #93 - which means it is certainly older than this "
            f"checkout. {RESTART_HINT}"
        )

    if reported.get("digest") == our_digest:
        return None

    ours = set(our_names)
    theirs = reported.get("names")
    if isinstance(theirs, list):
        server_lacks = sorted(ours - set(theirs))
        tree_lacks = sorted(set(theirs) - ours)
        differences = []
        if server_lacks:
            differences.append(f"the server has not got {_summarise(server_lacks)}")
        if tree_lacks:
            differences.append(f"this checkout has not got {_summarise(tree_lacks)}")
        detail = "; ".join(differences) or "the same migrations in a different order"
    else:
        detail = (
            f"the server carries {reported.get('count')} migrations "
            f"(digest {reported.get('digest')}), this checkout carries "
            f"{len(ours)} (digest {our_digest})"
        )

    return (
        f"the server at {target} is running different code than this working tree: "
        f"{detail}. Testing against it would prove nothing about this checkout. "
        f"{RESTART_HINT}"
    )
