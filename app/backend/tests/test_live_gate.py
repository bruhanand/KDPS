"""The live-API gate must distinguish "no server" from "the wrong server".

Issue #93's failure was not a crash: a stale container answered every probe
correctly and simply was not the code under test. These tests pin the judgement
that catches that - and pin that its message *names* what differs, because "the
server is stale" without specifics is exactly the kind of note that gets waved
through on the next run.
"""

from __future__ import annotations

from _live_gate import mismatch_reason

TREE = ("accounts.0001_initial", "accounts.0007_brand_scoped_users", "core.0001_initial")
DIGEST = "abc123def456"


def test_a_server_running_this_checkout_is_not_a_mismatch() -> None:
    reported = {"count": len(TREE), "digest": DIGEST, "names": list(TREE)}

    assert mismatch_reason(reported, target="http://x", our_names=TREE, our_digest=DIGEST) is None


def test_a_server_behind_the_checkout_names_the_migrations_it_lacks() -> None:
    """The real #93 shape: a container built before #85's `section_access` landed."""
    behind = [name for name in TREE if name != "accounts.0007_brand_scoped_users"]
    reported = {"count": len(behind), "digest": "staleaaaaaaa", "names": behind}

    reason = mismatch_reason(
        reported, target="http://localhost:8001", our_names=TREE, our_digest=DIGEST
    )

    assert reason is not None
    assert "accounts.0007_brand_scoped_users" in reason
    assert "http://localhost:8001" in reason
    assert "./scripts/dev.sh --api" in reason


def test_a_server_ahead_of_the_checkout_names_what_the_checkout_lacks() -> None:
    ahead = [*TREE, "outbound.0020_from_another_branch"]
    reported = {"count": len(ahead), "digest": "aheadaaaaaaa", "names": ahead}

    reason = mismatch_reason(reported, target="http://x", our_names=TREE, our_digest=DIGEST)

    assert reason is not None
    assert "this checkout has not got outbound.0020_from_another_branch" in reason


def test_a_long_list_of_differences_is_summarised_not_dumped() -> None:
    tree = tuple(f"app.{i:04d}_migration" for i in range(20))
    reported = {"count": 0, "digest": "emptyaaaaaaa", "names": []}

    reason = mismatch_reason(reported, target="http://x", our_names=tree, our_digest=DIGEST)

    assert reason is not None
    assert "(+16 more)" in reason


def test_a_hardened_server_that_withholds_names_still_reports_the_mismatch() -> None:
    """Render publishes count + digest only; that is enough to detect, if not to itemise."""
    reported = {"count": 41, "digest": "otherdigest1"}

    reason = mismatch_reason(reported, target="http://x", our_names=TREE, our_digest=DIGEST)

    assert reason is not None
    assert "41 migrations" in reason
    assert "otherdigest1" in reason and DIGEST in reason


def test_a_server_with_no_identity_at_all_is_older_than_this_check() -> None:
    reason = mismatch_reason(None, target="http://x", our_names=TREE, our_digest=DIGEST)

    assert reason is not None
    assert "does not report a migration identity" in reason
