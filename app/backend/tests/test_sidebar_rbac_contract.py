"""RBAC contract - the authenticated-user payload (issues #85, #130).

Hermetic (`db` fixture), so it runs in CI's `pytest tests` step. It proves the
server, not the client, decides what each of the nine roles may see and do:

  · each role's `/me` payload carries exactly its matrix sections + capabilities;
  · every seeded role is answered by the one ratified table - no second source;
  · what `seed_foundation` stores on a Role row is that same table;
  · a user with no role / no units gets nothing (fail-closed);
  · a section API called by the wrong role is denied server-side;
  · retuning access is a data edit — no code release (Rule 12).
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from django.core.management import call_command
from rest_framework.test import APIClient

from accounts import rbac_matrix
from accounts.management.commands.seed_foundation import ROLES as SEED_ROLES
from accounts.models import Role, User
from accounts.rbac_matrix import (
    KNOWN_ROLE_CODES,
    MATRIX,
    ROLE_PERSONA,
    section_access_for,
)
from accounts.sections import CAP_NONE, SECTION_CODES
from masters.models import Gstin, LegalEntity, Store

# One seeded role code per persona (store_person → store_staff for the test).
# All eight rows of the ratified table, covering all nine seeded roles - the two
# store codes share the "Store Person" row.
PERSONA_ROLE_CODE = {
    "owner": "owner",
    "store_person": "store_staff",
    "warehouse": "warehouse",
    "brand_manager": "brand_manager",
    "accounts": "accounts",
    "admin": "it_admin",
    "ho_ops": "ho_ops",
    "data_steward": "data_steward",
}


def _make_role(code: str) -> Role:
    return Role.objects.create(
        code=code,
        name=code.title(),
        nav_groups=["home"],
        section_access=section_access_for(code),
        is_system=True,
    )


def _make_user(username: str, role: Role | None, *, scope: str = "all") -> User:
    user = User.objects.create(username=username, role=role, scope_type=scope)
    user.set_password(TEST_PASSWORD)
    user.save()
    return user


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _expected_visible(persona: str) -> dict[str, str]:
    """{section: capability} the sheet grants this persona, none excluded."""
    return {
        section: capability
        for section, (capability, _label) in MATRIX[persona].items()
        if capability != CAP_NONE
    }


# --- Each role gets exactly its matrix sections + capabilities -------------
def test_every_persona_payload_matches_the_matrix(db):
    for persona, role_code in PERSONA_ROLE_CODE.items():
        role = _make_role(role_code)
        user = _make_user(f"u_{role_code}", role)
        resp = _client(user).get("/api/auth/me")
        assert resp.status_code == 200, persona
        body = resp.json()

        expected = _expected_visible(persona)
        # capabilities map is exactly the granted sections, nothing more/less.
        assert body["capabilities"] == expected, persona
        # sections list carries the same codes, in canonical sidebar order.
        got_codes = [s["code"] for s in body["sections"]]
        assert got_codes == [c for c in SECTION_CODES if c in expected], persona
        # every entry exposes its capability + the exact sheet wording.
        for entry in body["sections"]:
            cap, label = MATRIX[persona][entry["code"]]
            assert entry["capability"] == cap
            assert entry["scope_label"] == label


def test_sheet_specific_cells_are_honoured(db):
    """Spot-check the load-bearing cells so a transcription slip is caught."""
    caps = {
        persona: _client(_make_user(f"s_{code}", _make_role(code)))
        .get("/api/auth/me")
        .json()["capabilities"]
        for persona, code in PERSONA_ROLE_CODE.items()
    }
    # Admin has NO money (Sheet-1 note 2, kept).
    assert "money" not in caps["admin"]
    # Store person reads bookings without placing one, can't reach Setup, and
    # operates Sell.
    assert caps["store_person"]["booking"] == "view"
    assert "setup" not in caps["store_person"]
    assert caps["store_person"]["sell"] == "operate"
    # Warehouse can't sell.
    assert "sell" not in caps["warehouse"]
    # PT making moved to the warehouse (#119): it rose one rung above the
    # store on Receive Goods, and the store's cell kept its rung.
    assert caps["warehouse"]["receive_goods"] == "approve"
    assert caps["store_person"]["receive_goods"] == "operate"
    # Brand manager has no money either.
    assert "money" not in caps["brand_manager"]
    # Only Owner and Accounts fully manage money.
    assert caps["owner"]["money"] == "manage"
    assert caps["accounts"]["money"] == "manage"
    # HRMS (#87, derived — no sheet row; renamed from "staff" by #118): the
    # store person's daily attendance surface is real, and a brand manager —
    # whose scope is brands, not people — has none.
    assert caps["store_person"]["hrms"] == "operate"
    assert "hrms" not in caps["brand_manager"]


# --- Fail-closed ----------------------------------------------------------
def test_user_with_no_role_sees_nothing(db):
    user = _make_user("orphan", None, scope="store")  # no role, no stores
    body = _client(user).get("/api/auth/me").json()
    assert body["sections"] == []
    assert body["capabilities"] == {}
    assert body["business_units"] == []
    assert body["all_business_units"] is False


def test_store_scoped_user_without_stores_has_no_units(db):
    role = _make_role("store_staff")
    user = _make_user("newstore", role, scope="store")  # store scope, 0 stores
    body = _client(user).get("/api/auth/me").json()
    assert body["capabilities"]  # it does see sections
    assert body["business_units"] == []  # but acts nowhere yet
    assert body["all_business_units"] is False


def test_all_scoped_user_flagged_all_units(db):
    entity = LegalEntity.objects.create(code="e", name="E")
    gstin = Gstin.objects.create(
        gstin="10AAACK1234M1Z5", legal_entity=entity, state_code="10", state_name="Bihar"
    )
    Store.objects.create(code="DEO", name="Deoghar", store_type="store", gstin=gstin)
    user = _make_user("boss", _make_role("owner"), scope="all")
    body = _client(user).get("/api/auth/me").json()
    assert body["all_business_units"] is True
    assert [u["code"] for u in body["business_units"]] == ["DEO"]


# --- Server-side enforcement (not just a hidden menu) ---------------------
def test_wrong_role_denied_on_section_api(db):
    # Setup = manage only for Owner/Admin; Accounts holds setup:view → denied.
    accounts = _make_user("acc", _make_role("accounts"))
    assert _client(accounts).get("/api/auth/admin/roles").status_code == 403

    owner = _make_user("own", _make_role("owner"))
    assert _client(owner).get("/api/auth/admin/roles").status_code == 200


def test_the_two_ho_roles_do_not_gain_rbac_admin(db):
    """Users & Roles admin needs setup:manage - held only by Owner/Admin. The two
    head-office rows must stay below it, so seeding them can't silently escalate
    anyone onto the admin APIs (issue #85 review: data_steward 403). Ratifying
    the rows (#130) changed their status, not their power."""
    for code in ("data_steward", "ho_ops"):
        user = _make_user(f"d_{code}", _make_role(code))
        assert _client(user).get("/api/auth/admin/roles").status_code == 403, code
        assert section_access_for(code)["setup"]["capability"] != "manage", code


# --- One table, nine roles (#130) ------------------------------------------
def test_every_seeded_role_is_a_ratified_row(db):
    """No role is answered by a fallback, and no ratified row is unreachable.

    `ho_ops` and `data_steward` used to live in a `DERIVED_ACCESS` block that
    disclaimed itself as "NOT the RBAC matrix", so a role's access could only be
    read by first knowing which of two structures it came from. Ratified 26 Jul
    2026: one table, and the seed and the table agree on which roles exist.
    """
    seeded = {spec["code"] for spec in SEED_ROLES}
    assert seeded == set(KNOWN_ROLE_CODES) == set(ROLE_PERSONA)
    # Ten since 3 Aug 2026: Promo / Marketing joined the sheet (D11 R2) — the
    # person who authors offers and publishes them to the shops.
    assert len(seeded) == 10

    for code in KNOWN_ROLE_CODES:
        access = section_access_for(code)
        assert set(access) == set(SECTION_CODES), code
        # Every cell traces to the persona row (or the one declared override) -
        # nothing resolves through an absent section any more.
        persona_cells = MATRIX[ROLE_PERSONA[code]]
        assert set(persona_cells) == set(SECTION_CODES), code


def test_the_ratified_ho_rows_reach_the_live_payload(db):
    """The rows that were derived now answer like any other - through /me."""
    caps = {
        code: _client(_make_user(f"r_{code}", _make_role(code)))
        .get("/api/auth/me")
        .json()["capabilities"]
        for code in ("ho_ops", "data_steward")
    }
    # HO Operations books goods and approves movement, but never inwards one
    # (the buyer must not confirm receipt of their own order) and holds no money.
    assert caps["ho_ops"]["booking"] == "operate"
    assert caps["ho_ops"]["receive_goods"] == "view"
    assert caps["ho_ops"]["transfer"] == "approve"
    assert caps["ho_ops"]["stock_count"] == "approve"
    assert "money" not in caps["ho_ops"]
    assert "setup" not in caps["ho_ops"]
    # The Data Steward owns masters and reads stock; it posts nothing.
    assert caps["data_steward"]["setup"] == "operate"
    assert caps["data_steward"]["stock"] == "view"
    for shut in ("money", "sell", "booking", "receive_goods", "transfer"):
        assert shut not in caps["data_steward"], shut


def test_the_store_person_can_see_bookings_but_not_place_one(db):
    """The ratified correction to the sheet's "No" (PRD #104, 26 Jul 2026).

    A store plans space and staff against the goods headed to it, so the section
    opens - read-only. Placing one stays at `operate`, which the store does not
    hold. *Which* bookings it sees is record scope, and #101's work.
    """
    for code in ("store_staff", "store_manager"):
        body = _client(_make_user(f"b_{code}", _make_role(code))).get("/api/auth/me").json()
        assert body["capabilities"]["booking"] == "view", code
        assert [s["code"] for s in body["sections"] if s["code"] == "booking"] == ["booking"]


def test_the_client_copy_of_the_table_is_current():
    """The PWA's test fixtures are generated from this table, not transcribed.

    The live menu is already the server's answer, but the client suite used to
    assert against nine hand-copied personas - so a cell could be corrected here
    and the client would keep passing against the old wording. This fails the
    moment the generated file falls behind, and names the command that fixes it.
    """
    from accounts.management.commands.dump_rbac_matrix import TARGET, rendered

    assert TARGET.exists(), f"{TARGET} is missing - run manage.py dump_rbac_matrix"
    assert TARGET.read_text() == rendered(), (
        f"{TARGET.name} is stale - run `python manage.py dump_rbac_matrix` and commit it"
    )


def test_seeding_stores_exactly_the_table(db):
    """The stored answer is the table's - the seed writes no opinion of its own.

    `Role.section_access` is what every gate actually reads, so a seed that
    drifted from the table would make the table decorative.
    """
    call_command("seed_foundation")

    for role in Role.objects.filter(code__in=KNOWN_ROLE_CODES):
        assert role.section_access == section_access_for(role.code), role.code


# --- The payload is the stored row, whatever it says (#173) ----------------
def test_the_payload_follows_a_retuned_row_not_the_seed_table(db):
    """The matrix became an admin-editable screen, so the seed is only a start.

    Every other assertion in this file builds a role *from* ``rbac_matrix`` and
    then checks the payload against ``rbac_matrix``, which agrees with itself
    whether or not `/me` ever reads the database. This one retunes the stored
    row away from the table in both directions - a section opened, a section
    closed - and requires the payload to follow the row.
    """
    role = _make_role("store_staff")
    user = _make_user("retuned_cashier", role)
    seeded = _client(user).get("/api/auth/me").json()["capabilities"]
    assert seeded["booking"] == "view"  # what the table says
    assert "setup" not in seeded

    role.section_access["booking"] = {"capability": CAP_NONE, "label": "Closed in Setup"}
    role.section_access["setup"] = {"capability": "operate", "label": "Products only"}
    role.save(update_fields=["section_access"])

    retuned = _client(user).get("/api/auth/me").json()
    assert "booking" not in retuned["capabilities"]
    assert retuned["capabilities"]["setup"] == "operate"
    assert [s["code"] for s in retuned["sections"] if s["code"] == "setup"] == ["setup"]
    # And the table is untouched - the row moved, not the seed.
    assert section_access_for("store_staff")["booking"]["capability"] == "view"


# --- Access is data, not code (Rule 12) -----------------------------------
def test_setup_manage_cannot_configure_away_the_access_admin_floor(db):
    role = _make_role("accounts")
    user = _make_user("acc2", role)
    # Before: accounts can't manage Setup.
    assert _client(user).get("/api/auth/admin/roles").status_code == 403

    # Grant setup:manage by editing the role row — no code release.
    role.section_access["setup"] = {"capability": "manage", "label": "Granted"}
    role.save(update_fields=["section_access"])

    assert _client(user).get("/api/auth/admin/roles").status_code == 403
    body = _client(user).get("/api/auth/me").json()
    assert body["capabilities"]["setup"] == "manage"


def test_store_manager_and_cashier_differ_only_on_hrms(db):
    """The one place the two store roles part company (#96).

    Both are the "Store Person" persona and must agree on all twelve ratified
    sheet cells. The sketch's "Member Details" — bank details, monthly target vs
    achievement — is manager work, so the manager holds `hrms: manage` and the
    cashier keeps `operate` (own attendance). An override may only touch a
    section the sheet never covered, which is what keeps the rest identical.
    """
    manager = section_access_for("store_manager")
    cashier = section_access_for("store_staff")

    assert manager["hrms"]["capability"] == "manage"
    assert cashier["hrms"]["capability"] == "operate"
    differing = {s for s in SECTION_CODES if manager[s] != cashier[s]}
    assert differing == {"hrms"}

    # And the lift reaches the live payload, not just the seed table.
    body = _client(_make_user("mgr", _make_role("store_manager"))).get("/api/auth/me").json()
    assert body["capabilities"]["hrms"] == "manage"
    # Managing people is not managing money or users — the override is confined.
    assert body["capabilities"]["money"] == "operate"
    assert "setup" not in body["capabilities"]


def test_overrides_cannot_contradict_the_sheet(monkeypatch):
    """Guardrail: the override hook fails loudly if it reaches a sheet cell.

    `_validate()` runs at import, so a real off-sheet override could never ship —
    it would crash the process. This proves the guard actually fires: point an
    override at `money` (a ratified sheet section) and `_validate()` must raise.
    Without it, `ROLE_OVERRIDES` becomes a back door for quietly editing the
    matrix in code — exactly what Rule 12 and the role editor exist to prevent.
    """
    monkeypatch.setattr(
        rbac_matrix,
        "ROLE_OVERRIDES",
        {"store_manager": {"money": ("manage", "back door")}},
    )
    with pytest.raises(AssertionError, match="may not override sheet sections"):
        rbac_matrix._validate()


def test_seed_matrix_covers_every_canonical_role(db):
    """Guardrail: every persona role resolves to a map of every known section."""
    for role_code in ROLE_PERSONA:
        access = section_access_for(role_code)
        assert set(access) == set(SECTION_CODES), role_code
        for entry in access.values():
            assert "capability" in entry and "label" in entry
