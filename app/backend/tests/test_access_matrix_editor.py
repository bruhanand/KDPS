"""Issue #173 — an admin edits the access matrix; the money floors do not move.

These stay at the public seams: an HTTP request is accepted, refused or parked
for a second person, and the stored row either moved or did not. What they
deliberately do not assert is the shape of ``accounts.floors`` — the floor is a
promise about answers, and a test that reads the constant would pass on a floor
that had stopped binding.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from rest_framework.test import APIClient

from accounts.floors import FLOORS, RULES
from accounts.models import AccessChange, Role, User
from accounts.rbac_matrix import KNOWN_ROLE_CODES, section_access_for
from accounts.sections import CAP_MANAGE, CAP_NONE, CAP_OPERATE, CAP_VIEW, SECTION_CODES

MATRIX_URL = "/api/auth/admin/access-matrix"


def _role(code: str, **kwargs) -> Role:
    return Role.objects.create(
        code=code,
        name=code.replace("_", " ").title(),
        section_access=section_access_for(code),
        is_system=True,
        **kwargs,
    )


def _user(username: str, role: Role | None, **kwargs) -> User:
    user = User.objects.create(username=username, role=role, scope_type="all", **kwargs)
    user.set_password(TEST_PASSWORD)
    user.save()
    return user


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _access_url(code: str) -> str:
    return f"/api/auth/admin/roles/{code}/access"


def _row(role_code: str, **overrides: str) -> dict[str, dict[str, str]]:
    """A full thirteen-cell replacement: the seeded row with cells moved."""
    row = {
        section: {"capability": cell["capability"]}
        for section, cell in section_access_for(role_code).items()
    }
    for section, capability in overrides.items():
        row[section] = {"capability": capability}
    return row


@pytest.fixture
def admin(db) -> User:
    return _user("matrix_admin", _role("it_admin"))


@pytest.fixture
def checker(db) -> User:
    """The second access administrator — rule 4's other half."""
    return _user("matrix_checker", _role("owner"))


# --- GET: the grid ---------------------------------------------------------
def test_the_grid_is_roles_by_sections_plus_the_floor(admin):
    warehouse = _role("warehouse")

    body = _client(admin).get(MATRIX_URL).json()

    assert [s["code"] for s in body["sections"]] == SECTION_CODES
    assert body["capabilities"] == [CAP_NONE, CAP_VIEW, CAP_OPERATE, "approve", CAP_MANAGE]
    rows = {role["code"]: role for role in body["roles"]}
    assert set(rows) == {"it_admin", "warehouse"}
    # Every cell is stated, so "no access" is on the screen rather than inferred.
    assert set(rows["warehouse"]["section_access"]) == set(SECTION_CODES)
    assert rows["warehouse"]["section_access"]["receive_goods"]["capability"] == "approve"
    assert rows["warehouse"]["name"] == warehouse.name

    # The locked cells arrive with the reason the screen greys them with.
    locked = rows["warehouse"]["locked"]
    assert set(locked) == {"money", "setup"}
    assert locked["money"]["max_capability"] == "approve"
    assert locked["setup"]["max_capability"] == "approve"
    assert "named head-office human" in locked["money"]["reason"]
    assert "Owner or IT Admin" in locked["setup"]["reason"]
    # An IT Admin may hold full Setup, so that cell is not locked for it.
    assert set(rows["it_admin"]["locked"]) == {"money"}


def test_the_grid_states_all_four_rules_including_the_two_with_no_cell(admin):
    """Rule 1 and rule 4's second half cannot be a greyed cell, and saying
    nothing about them would read as "there are only three"."""
    body = _client(admin).get(MATRIX_URL).json()

    assert [r["rule"] for r in body["rules"]] == [1, 2, 3, 4]
    assert body["rules"][0]["text"] == RULES[1]
    with_cells = {floor.rule for floor in FLOORS}
    assert with_cells == {2, 3, 4}


def test_the_grid_shows_the_stored_row_not_the_seed_table(admin):
    warehouse = _role("warehouse")
    warehouse.section_access["stock_count"] = {"capability": CAP_NONE, "label": "Closed"}
    warehouse.save(update_fields=["section_access"])

    rows = {r["code"]: r for r in _client(admin).get(MATRIX_URL).json()["roles"]}

    assert rows["warehouse"]["section_access"]["stock_count"]["capability"] == CAP_NONE
    assert section_access_for("warehouse")["stock_count"]["capability"] == CAP_OPERATE


def test_a_short_stored_row_reads_as_no_access_not_as_a_hole(admin):
    """A hand-made role, or one seeded before a section existed, states 13 cells
    on the grid all the same — and the missing ones read `none`, the same
    fail-closed answer the gate gives them."""
    Role.objects.create(code="hand_made", name="Hand made", section_access={})

    rows = {r["code"]: r for r in _client(admin).get(MATRIX_URL).json()["roles"]}

    cells = rows["hand_made"]["section_access"]
    assert set(cells) == set(SECTION_CODES)
    assert {c["capability"] for c in cells.values()} == {CAP_NONE}


def test_the_grid_is_closed_to_a_role_without_setup_manage(db):
    steward = _user("grid_steward", _role("data_steward"))

    assert _client(steward).get(MATRIX_URL).status_code == 403


# --- PUT: the floor --------------------------------------------------------
@pytest.mark.parametrize(
    ("role_code", "section", "capability", "expected_ceiling"),
    [
        # Rule 2 — a store seat may raise its own expenses, never the books.
        ("store_staff", "money", CAP_MANAGE, CAP_OPERATE),
        ("store_manager", "money", "approve", CAP_OPERATE),
        # Rule 3 — full Money is Owner's and Accounts'.
        ("warehouse", "money", CAP_MANAGE, "approve"),
        ("it_admin", "money", CAP_MANAGE, "approve"),
        # Rule 4 — full Setup is the power to grant power.
        ("warehouse", "setup", CAP_MANAGE, "approve"),
        ("data_steward", "setup", CAP_MANAGE, "approve"),
    ],
)
def test_a_floor_crossing_cell_is_refused_naming_the_cell(
    admin, role_code, section, capability, expected_ceiling
):
    role = _role(role_code) if role_code != "it_admin" else Role.objects.get(code="it_admin")
    before = dict(role.section_access)

    response = _client(admin).put(
        _access_url(role_code),
        {"section_access": _row(role_code, **{section: capability})},
        format="json",
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "FLOOR_LOCKED"
    assert [c["section"] for c in body["cells"]] == [section]
    assert body["cells"][0]["max_capability"] == expected_ceiling
    assert body["cells"][0]["requested"] == capability
    assert body["cells"][0]["reason"].strip()
    role.refresh_from_db()
    assert role.section_access == before
    assert not AccessChange.objects.exists()


def test_two_crossed_floors_are_reported_together_not_one_at_a_time(admin):
    """An administrator who moved several cells is told about all of them."""
    _role("warehouse")

    response = _client(admin).put(
        _access_url("warehouse"),
        {"section_access": _row("warehouse", money=CAP_MANAGE, setup=CAP_MANAGE)},
        format="json",
    )

    assert response.status_code == 422
    assert {c["section"] for c in response.json()["cells"]} == {"money", "setup"}


def test_the_tighter_of_two_floors_on_one_cell_wins(admin):
    """Money is capped twice for a store seat — at `approve` by rule 3 and at
    `operate` by rule 2. Offering `approve` would be offering a rung the server
    refuses, so the grid and the refusal must both say `operate`."""
    _role("store_staff")

    grid = {r["code"]: r for r in _client(admin).get(MATRIX_URL).json()["roles"]}
    assert grid["store_staff"]["locked"]["money"]["max_capability"] == CAP_OPERATE

    refused = _client(admin).put(
        _access_url("store_staff"),
        {"section_access": _row("store_staff", money="approve")},
        format="json",
    )
    assert refused.status_code == 422
    assert refused.json()["cells"][0]["max_capability"] == CAP_OPERATE


def test_the_seeded_matrix_crosses_no_floor_of_its_own(db):
    """The starting content must satisfy the rules it starts under, or every
    fresh install ships already over the line."""
    from accounts.floors import floor_violations

    for code in KNOWN_ROLE_CODES:
        assert floor_violations(code, section_access_for(code)) == [], code


def test_the_older_whole_role_editor_cannot_walk_around_the_floor(admin):
    """The matrix screen is the front door; `PATCH /admin/roles/{pk}` edits the
    same column and would be the back one."""
    warehouse = _role("warehouse")

    response = _client(admin).patch(
        f"/api/auth/admin/roles/{warehouse.pk}",
        {"section_access": _row("warehouse", setup=CAP_MANAGE)},
        format="json",
    )

    assert response.status_code == 400
    assert "Owner or IT Admin" in str(response.json())
    assert not AccessChange.objects.exists()


# --- PUT: never by one person alone (rule 4) -------------------------------
def test_an_edit_waits_for_a_second_access_administrator(admin, checker):
    role = _role("warehouse")

    proposed = _client(admin).put(
        _access_url("warehouse"),
        {"section_access": _row("warehouse", transfer="approve")},
        format="json",
    )

    assert proposed.status_code == 202
    assert proposed.json()["status"] == "pending_approval"
    role.refresh_from_db()
    assert role.section_access["transfer"]["capability"] == CAP_OPERATE

    # The proposer is not the approver — rule 1, on this document too.
    approval_id = proposed.json()["approval_id"]
    assert (
        _client(admin)
        .post(f"/api/approvals/{approval_id}/decide", {"action": "approve"}, format="json")
        .status_code
        == 403
    )
    role.refresh_from_db()
    assert role.section_access["transfer"]["capability"] == CAP_OPERATE

    cleared = _client(checker).post(
        f"/api/approvals/{approval_id}/decide", {"action": "approve"}, format="json"
    )

    assert cleared.status_code == 200
    role.refresh_from_db()
    assert role.section_access["transfer"]["capability"] == "approve"


def test_the_change_is_logged_cell_by_cell_old_to_new(admin, checker):
    _role("warehouse")

    proposed = _client(admin).put(
        _access_url("warehouse"),
        {"section_access": _row("warehouse", transfer="approve", sell=CAP_VIEW)},
        format="json",
    )

    assert proposed.status_code == 202
    assert sorted(proposed.json()["cells"], key=lambda c: c["section"]) == [
        {"section": "sell", "from": CAP_NONE, "to": CAP_VIEW},
        {"section": "transfer", "from": CAP_OPERATE, "to": "approve"},
    ]
    change = AccessChange.objects.get()
    assert change.created_by == admin
    assert change.resource == AccessChange.Resource.ROLE
    assert {c["section"] for c in change.payload["_cells"]} == {"sell", "transfer"}
    assert "transfer operate→approve" in change.summary

    _client(checker).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )

    change.refresh_from_db()
    assert change.applied_by == checker
    assert change.applied_at is not None
    # The diff survives application — it is the audit trail, not an instruction.
    assert change.payload["_cells"]


def test_the_audit_annotation_is_never_written_onto_the_role(admin, checker):
    """`_cells` rides in the payload the applier walks; a column called `_cells`
    does not exist, so the applier has to know the difference."""
    role = _role("warehouse")

    proposed = _client(admin).put(
        _access_url("warehouse"),
        {"section_access": _row("warehouse", transfer="approve")},
        format="json",
    )
    _client(checker).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )

    role.refresh_from_db()
    assert not hasattr(role, "_cells")
    assert set(role.section_access) == set(SECTION_CODES)


def test_an_edit_that_changes_nothing_asks_nobody_to_approve_it(admin):
    _role("warehouse")

    response = _client(admin).put(
        _access_url("warehouse"), {"section_access": _row("warehouse")}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "unchanged"
    assert not AccessChange.objects.exists()


def test_a_section_left_out_of_the_body_is_removed_not_kept(admin, checker):
    """PUT replaces the row. An omission has to narrow access — the other
    reading (keep what was there) would make a half-sent form silently grant
    whatever the role held before."""
    role = _role("warehouse")

    proposed = _client(admin).put(
        _access_url("warehouse"),
        {"section_access": {"stock": {"capability": CAP_VIEW}}},
        format="json",
    )
    _client(checker).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )

    role.refresh_from_db()
    assert role.section_access["stock"]["capability"] == CAP_VIEW
    assert role.section_access["receive_goods"]["capability"] == CAP_NONE
    assert set(role.section_access) == set(SECTION_CODES)


def test_a_retuned_cell_loses_the_sheet_sentence_it_no_longer_describes(admin, checker):
    role = _role("store_staff")
    assert role.section_access["money"]["label"] == "Expenses only (create)"

    proposed = _client(admin).put(
        _access_url("store_staff"),
        {"section_access": _row("store_staff", money=CAP_VIEW)},
        format="json",
    )
    _client(checker).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )

    role.refresh_from_db()
    assert role.section_access["money"] == {"capability": CAP_VIEW, "label": "View only"}


# --- PUT: the other refusals ----------------------------------------------
def test_an_unknown_role_code_is_a_404(admin):
    response = _client(admin).put(_access_url("nobody"), {"section_access": {}}, format="json")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "body",
    [
        {"section_access": {"not_a_section": {"capability": CAP_VIEW}}},
        {"section_access": {"money": {"capability": "god"}}},
        {"section_access": "everything"},
    ],
    ids=["unknown section", "off-ladder rung", "not an object"],
)
def test_a_malformed_row_is_a_validation_error(admin, body):
    _role("warehouse")

    response = _client(admin).put(_access_url("warehouse"), body, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"
    assert not AccessChange.objects.exists()


def test_an_invented_setting_is_refused_out_loud(admin):
    """DRF's default is to ignore a field it does not know, which here would
    answer 202 to "allow_store_value_posting" and let an administrator believe
    they had switched a floor off."""
    _role("warehouse")

    response = _client(admin).put(
        _access_url("warehouse"),
        {"section_access": _row("warehouse"), "allow_store_value_posting": True},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["fields"] == ["allow_store_value_posting"]
    assert "floor rules" in response.json()["error"]


def test_setup_manage_alone_does_not_open_the_editor(db):
    """Both gates are asked. Rule 4 names Owner and IT Admin; the Setup rung is
    the ladder underneath it, and holding one without the other is not enough."""
    warehouse = _role("warehouse")
    warehouse.section_access["setup"] = {"capability": CAP_MANAGE, "label": "Granted"}
    warehouse.save(update_fields=["section_access"])
    granted = _user("setup_only", warehouse)

    assert _client(granted).get(MATRIX_URL).status_code == 200  # reading is the Setup rung
    assert (
        _client(granted)
        .put(_access_url("warehouse"), {"section_access": _row("warehouse")}, format="json")
        .status_code
        == 403
    )


def test_a_superuser_outside_the_floor_roles_cannot_edit_the_matrix(db):
    """Break-glass reaches every section, and still is not an access
    administrator unless the role on it says so (rule 4)."""
    outsider = _user("root_warehouse", _role("warehouse"), is_superuser=True)

    response = _client(outsider).put(
        _access_url("warehouse"),
        {"section_access": _row("warehouse", setup=CAP_OPERATE)},
        format="json",
    )

    assert response.status_code == 403
    assert not AccessChange.objects.exists()
