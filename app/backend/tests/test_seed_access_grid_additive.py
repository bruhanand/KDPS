"""Re-seeding never revokes an access change two administrators agreed (#224).

`seed_foundation` used to write the ratified sheet over `Role.section_access`
on every run. Since grill decision 11 the grid is data an administrator
maintains without a release (Rule 12), applied by two people with an audit row
behind it - so a redeploy that re-ran the seed silently took those grants back,
with nothing on any screen to say it had happened.

The seed is now **additive only** on that one column: it fills a section the
stored row does not state yet, and never touches one it does. That keeps both
traps shut - a retune survives every re-seed, and a section added after a role
was seeded still reaches it.
"""

from __future__ import annotations

from django.core.management import call_command

from accounts.models import Role
from accounts.rbac_matrix import section_access_for
from accounts.sections import CAP_NONE, SECTION_CODES


def test_reseeding_keeps_an_approved_access_change(db):
    """The grant this feature exists to protect: a store manager's `sell: approve`."""
    call_command("seed_foundation")
    role = Role.objects.get(code="store_manager")
    assert role.section_access["sell"]["capability"] != "approve"  # the sheet's word

    # What an applied AccessChange leaves on the row (accounts.matrix.replacement_row).
    role.section_access["sell"] = {"capability": "approve", "label": "Approve returns"}
    role.section_access["booking"] = {"capability": CAP_NONE, "label": "Closed in Setup"}
    role.save(update_fields=["section_access"])

    call_command("seed_foundation")

    role.refresh_from_db()
    assert role.section_access["sell"] == {"capability": "approve", "label": "Approve returns"}
    assert role.section_access["booking"] == {"capability": CAP_NONE, "label": "Closed in Setup"}


def test_reseeding_leaves_every_untouched_cell_exactly_as_it_was(db):
    call_command("seed_foundation")
    before = {role.code: dict(role.section_access) for role in Role.objects.all()}

    call_command("seed_foundation")

    after = {role.code: dict(role.section_access) for role in Role.objects.all()}
    assert after == before


def test_reseeding_grants_a_section_added_after_the_role_was_seeded(db):
    """The other trap: additive must still mean a new section reaches old roles.

    A role seeded before a section existed has no key for it, and an absent key
    fail-closes to `none` - so without the fill the section would be invisible
    to everyone until somebody hand-edited every role.
    """
    call_command("seed_foundation")
    role = Role.objects.get(code="ho_ops")
    retuned = {"capability": "manage", "label": "Retuned by two admins"}
    role.section_access["stock"] = retuned
    del role.section_access["reports"]  # a section this role predates
    role.save(update_fields=["section_access"])

    call_command("seed_foundation")

    role.refresh_from_db()
    assert role.section_access["reports"] == section_access_for("ho_ops")["reports"]
    assert role.section_access["stock"] == retuned  # and the fill touched nothing else


def test_a_row_with_no_grid_at_all_is_filled_from_the_sheet(db):
    """Additive-only must not leave a blank row blank - every section gets stated."""
    call_command("seed_foundation")
    role = Role.objects.get(code="accounts")
    role.section_access = {}
    role.save(update_fields=["section_access"])

    call_command("seed_foundation")

    role.refresh_from_db()
    assert role.section_access == section_access_for("accounts")
    assert set(role.section_access) == set(SECTION_CODES)
