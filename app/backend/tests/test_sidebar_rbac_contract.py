"""SIDEBAR RBAC contract — the authenticated-user payload (issue #85).

Hermetic (`db` fixture), so it runs in CI's `pytest tests` step. It proves the
server, not the client, decides what each of the six roles may see and do:

  · each role's `/me` payload carries exactly its matrix sections + capabilities;
  · a user with no role / no units gets nothing (fail-closed);
  · a section API called by the wrong role is denied server-side;
  · retuning access is a data edit — no code release (Rule 12).
"""

from __future__ import annotations

from _creds import TEST_PASSWORD
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.rbac_matrix import MATRIX, ROLE_PERSONA, section_access_for
from accounts.sections import CAP_NONE, SECTION_CODES
from masters.models import Gstin, LegalEntity, Store

# One seeded role code per persona (store_person → store_staff for the test).
PERSONA_ROLE_CODE = {
    "owner": "owner",
    "store_person": "store_staff",
    "warehouse": "warehouse",
    "brand_manager": "brand_manager",
    "accounts": "accounts",
    "admin": "it_admin",
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
    # Store person can't book, can't reach Setup, but operates Sell.
    assert "booking" not in caps["store_person"]
    assert "setup" not in caps["store_person"]
    assert caps["store_person"]["sell"] == "operate"
    # Warehouse can't sell.
    assert "sell" not in caps["warehouse"]
    # Brand manager has no money either.
    assert "money" not in caps["brand_manager"]
    # Only Owner and Accounts fully manage money.
    assert caps["owner"]["money"] == "manage"
    assert caps["accounts"]["money"] == "manage"


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


def test_derived_roles_do_not_gain_rbac_admin(db):
    """Users & Roles admin needs setup:manage — held only by Owner/Admin. The
    legacy non-persona roles must stay below it, so seeding them can't silently
    escalate anyone onto the admin APIs (issue #85 review: data_steward 403)."""
    for code in ("data_steward", "ho_ops"):
        user = _make_user(f"d_{code}", _make_role(code))
        assert _client(user).get("/api/auth/admin/roles").status_code == 403, code
        assert section_access_for(code)["setup"]["capability"] != "manage", code


# --- Access is data, not code (Rule 12) -----------------------------------
def test_retuning_section_access_is_a_data_change(db):
    role = _make_role("accounts")
    user = _make_user("acc2", role)
    # Before: accounts can't manage Setup.
    assert _client(user).get("/api/auth/admin/roles").status_code == 403

    # Grant setup:manage by editing the role row — no code release.
    role.section_access["setup"] = {"capability": "manage", "label": "Granted"}
    role.save(update_fields=["section_access"])

    assert _client(user).get("/api/auth/admin/roles").status_code == 200
    body = _client(user).get("/api/auth/me").json()
    assert body["capabilities"]["setup"] == "manage"


def test_seed_matrix_covers_every_canonical_role(db):
    """Guardrail: every persona role resolves to a full 12-section map."""
    for role_code in ROLE_PERSONA:
        access = section_access_for(role_code)
        assert set(access) == set(SECTION_CODES), role_code
        for entry in access.values():
            assert "capability" in entry and "label" in entry
