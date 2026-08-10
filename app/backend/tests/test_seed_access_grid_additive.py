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
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.rbac_matrix import section_access_for
from accounts.sections import CAP_NONE, SECTION_CODES


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _approved_change(role_code: str, **cells: str) -> None:
    """Move cells the way the product does: one admin proposes, a second applies.

    Written through the real endpoints rather than by assigning to the JSON
    column, because the thing under test is whether *an approved access change*
    survives a re-seed. A hand-written row would still pass if the editor's
    stored shape drifted, which is exactly the drift this has to notice.
    """
    proposer = User.objects.get(username="admin")  # it_admin
    checker = User.objects.get(username="owner")  # the second access administrator
    row = {
        section: {"capability": cell["capability"]}
        for section, cell in Role.objects.get(code=role_code).section_access.items()
    }
    row.update({section: {"capability": capability} for section, capability in cells.items()})

    proposed = _client(proposer).put(
        f"/api/auth/admin/roles/{role_code}/access", {"section_access": row}, format="json"
    )
    assert proposed.status_code == 202, proposed.content
    decided = _client(checker).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )
    assert decided.status_code == 200, decided.content


def test_reseeding_keeps_an_access_change_two_administrators_approved(db):
    """The grant this feature exists to protect: a store manager's `sell: approve`.

    Without it no counter can approve a return, and it is exactly the kind of
    retune a redeploy used to take back.
    """
    call_command("seed_foundation")
    assert Role.objects.get(code="store_manager").section_access["sell"]["capability"] != "approve"

    _approved_change("store_manager", sell="approve", booking=CAP_NONE)
    approved = dict(Role.objects.get(code="store_manager").section_access)

    call_command("seed_foundation")

    role = Role.objects.get(code="store_manager")
    assert role.section_access["sell"]["capability"] == "approve"
    assert role.section_access["booking"]["capability"] == CAP_NONE
    assert role.section_access == approved  # label and all, not just the rung


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


def test_a_role_two_administrators_switched_off_stays_off(db):
    """The same defect from the other side, and this one fails open.

    Deactivating a role is an access change two administrators agree. A seed
    that set `is_active=True` on every run would re-open a seat they closed.
    """
    call_command("seed_foundation")
    Role.objects.filter(code="promo").update(is_active=False)

    call_command("seed_foundation")

    assert Role.objects.get(code="promo").is_active is False


def test_a_kept_cell_is_narrowed_to_a_floor_that_has_since_tightened(db, monkeypatch):
    """Keeping a retune must not mean keeping a rung the floor now locks.

    Both editing doors refuse a crossing edit, so a stored row can only cross a
    floor when the floor moves under it - which a release can do, because the
    four rules are ratified in code. The old overwriting seed healed that by
    accident; the additive one has to do it on purpose.
    """
    from accounts import floors

    call_command("seed_foundation")
    role = Role.objects.get(code="warehouse")
    role.section_access["stock"] = {"capability": "manage", "label": "Full (all locations)"}
    role.save(update_fields=["section_access"])
    assert floors.floor_violations("warehouse", role.section_access) == []  # legal today

    tightened = floors.Floor(
        rule=3,
        section="stock",
        locked_rung="manage",
        held_by=frozenset({"owner"}),
        applies_to=None,
        reason="Ratified after this row was stored.",
    )
    monkeypatch.setattr(floors, "FLOORS", (*floors.FLOORS, tightened))

    call_command("seed_foundation")

    role.refresh_from_db()
    assert role.section_access["stock"]["capability"] == "approve"  # pulled to the ceiling
    assert floors.floor_violations("warehouse", role.section_access) == []
