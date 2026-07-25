"""The business-unit switcher (issue #88) — what it offers, and what it enforces.

The top bar lets a person choose which unit they are working in. Two things have
to be true for that to be safe, and both are proved here:

  · the *list* comes only from the server — a store person is locked to their own
    store, an owner gets the network option, a brand manager gets brands instead
    of units, and someone with no units gets an empty, locked selector;
  · the *choice* only ever narrows — sending another store's unit header is a
    403, not a peek, and the switcher's own list never collapses to the pick.

Hermetic (`db` fixture), so it runs in CI's `pytest tests` step.
"""

from __future__ import annotations

from _creds import TEST_PASSWORD
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from accounts.models import Role, ScopeType, User
from accounts.rbac_matrix import section_access_for
from approvals.models import Approval, ApprovalStatus
from masters.models import Brand, Gstin, LegalEntity, Store
from stockledger.models import StockOnHand

ON_HAND = "/api/stockledger/on-hand"
ME = "/api/auth/me"


def _world() -> dict[str, object]:
    entity = LegalEntity.objects.create(code="kdps", name="KDPS Lifestyle", pan="AAACK1234M")
    bihar = Gstin.objects.create(
        legal_entity=entity, gstin="10AAACK1234M1Z5", state_code="10", state_name="Bihar"
    )
    jhk = Gstin.objects.create(
        legal_entity=entity, gstin="20AAACK1234M1Z3", state_code="20", state_name="Jharkhand"
    )
    deo = Store.objects.create(code="DEO", name="Deoghar", gstin=jhk, store_type="store")
    pat = Store.objects.create(code="PAT", name="Patna", gstin=bihar, store_type="store")
    peter = Brand.objects.create(code="peter-england", name="Peter England")
    mufti = Brand.objects.create(code="mufti", name="Mufti")
    # One shirt in each store, one of each brand, so every narrowing is visible
    # as a different answer rather than as "fewer rows".
    StockOnHand.objects.create(
        store=deo, gstin=jhk, sku_code="DEO-1", brand="PETER ENGLAND", net_qty=5, net_value_paise=1
    )
    StockOnHand.objects.create(
        store=pat, gstin=bihar, sku_code="PAT-1", brand="MUFTI", net_qty=7, net_value_paise=1
    )
    return {"entity": entity, "deo": deo, "pat": pat, "peter": peter, "mufti": mufti}


def _user(
    username: str,
    role_code: str,
    scope: str,
    *,
    stores: list[Store] | None = None,
    brands: list[Brand] | None = None,
) -> User:
    role, _ = Role.objects.get_or_create(
        code=role_code,
        defaults={
            "name": role_code.title(),
            "nav_groups": ["home"],
            "section_access": section_access_for(role_code),
            "is_system": True,
        },
    )
    user = User.objects.create(username=username, role=role, scope_type=scope)
    user.set_password(TEST_PASSWORD)
    user.save()
    user.stores.set(stores or [])
    user.brands.set(brands or [])
    return user


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _skus(response) -> set[str]:
    return {row["sku_code"] for row in response.json()["rows"]}


def _approval(store: Store, maker: User, *, roles: list[str]) -> Approval:
    """One pending approval sitting at ``store``, decidable by ``roles``."""
    return Approval.objects.create(
        kind="vflip",
        kind_label="V-flip",
        title=f"{store.code} · 1 line",
        content_type=ContentType.objects.get_for_model(Store),
        object_id=store.pk,
        store=store,
        approver_roles=list(roles),
        made_by=maker,
        requested_by=maker,
        status=ApprovalStatus.PENDING,
    )


# --- What the switcher offers ---------------------------------------------
def test_store_person_is_locked_to_their_own_store(db):
    w = _world()
    user = _user("deo.cashier", "store_staff", ScopeType.STORE, stores=[w["deo"]])
    body = _client(user).get(ME).json()

    assert [u["code"] for u in body["business_units"]] == ["DEO"]
    assert body["all_business_units"] is False  # no network option to offer
    assert body["business_unit_mode"] == "units"


def test_owner_gets_every_unit_and_the_network_option(db):
    _world()
    user = _user("owner", "owner", ScopeType.ALL)
    body = _client(user).get(ME).json()

    assert {u["code"] for u in body["business_units"]} == {"DEO", "PAT"}
    assert body["all_business_units"] is True


def test_a_user_with_no_units_gets_an_empty_locked_selector(db):
    _world()
    user = _user("nobody", "store_staff", ScopeType.STORE)  # store-scoped, no stores
    body = _client(user).get(ME).json()

    assert body["business_units"] == []
    assert body["all_business_units"] is False
    assert body["assigned_brands"] == []


def test_brand_manager_gets_brands_instead_of_units(db):
    w = _world()
    user = _user("brand1", "brand_manager", ScopeType.BRAND, brands=[w["peter"]])
    body = _client(user).get(ME).json()

    assert body["business_unit_mode"] == "brands"
    assert [b["code"] for b in body["assigned_brands"]] == ["peter-england"]
    # No network-unit view: their "all" is all their brands, not all stores.
    assert body["all_business_units"] is False


def test_the_switcher_list_does_not_collapse_to_the_chosen_unit(db):
    """Narrowing the *data* to the active unit must not narrow the list you pick
    from — otherwise choosing a unit strands you in it with no way back."""
    w = _world()
    user = _user("ops", "ho_ops", ScopeType.ALL)
    body = _client(user).get(ME, headers={"X-KDPS-Unit": w["deo"].code}).json()

    assert {u["code"] for u in body["business_units"]} == {"DEO", "PAT"}


# --- What the choice enforces ---------------------------------------------
def test_switching_unit_re_scopes_what_a_screen_shows(db):
    _world()
    user = _user("ops", "ho_ops", ScopeType.ALL)
    client = _client(user)

    assert _skus(client.get(ON_HAND)) == {"DEO-1", "PAT-1"}
    assert _skus(client.get(ON_HAND, headers={"X-KDPS-Unit": "DEO"})) == {"DEO-1"}
    assert _skus(client.get(ON_HAND, headers={"X-KDPS-Unit": "PAT"})) == {"PAT-1"}


def test_a_store_person_cannot_open_another_store_by_forging_the_header(db):
    w = _world()
    user = _user("deo.cashier", "store_staff", ScopeType.STORE, stores=[w["deo"]])
    client = _client(user)

    assert client.get(ON_HAND, headers={"X-KDPS-Unit": "PAT"}).status_code == 403
    # And with no header they still only ever see their own store.
    assert _skus(client.get(ON_HAND)) == {"DEO-1"}


def test_an_unknown_unit_is_refused_not_ignored(db):
    _world()
    user = _user("owner", "owner", ScopeType.ALL)

    assert _client(user).get(ON_HAND, headers={"X-KDPS-Unit": "NOPE"}).status_code == 403


def test_the_unit_header_never_widens_scope(db):
    """The header is a narrowing filter, never a grant: a store person naming
    their own store is fine, and that is the most it can ever do."""
    w = _world()
    user = _user("deo.cashier", "store_staff", ScopeType.STORE, stores=[w["deo"]])

    assert _skus(_client(user).get(ON_HAND, headers={"X-KDPS-Unit": "DEO"})) == {"DEO-1"}


# --- The brand manager's filter -------------------------------------------
def test_a_brand_manager_sees_only_their_brands_across_every_store(db):
    w = _world()
    user = _user("brand1", "brand_manager", ScopeType.BRAND, brands=[w["peter"]])

    # Peter England is stocked at Deoghar; Mufti at Patna is not theirs.
    assert _skus(_client(user).get(ON_HAND)) == {"DEO-1"}


def test_a_brand_manager_with_no_brands_sees_nothing(db):
    _world()
    user = _user("brand0", "brand_manager", ScopeType.BRAND)

    assert _skus(_client(user).get(ON_HAND)) == set()


def test_a_brand_manager_cannot_filter_to_a_brand_they_do_not_own(db):
    w = _world()
    user = _user("brand1", "brand_manager", ScopeType.BRAND, brands=[w["peter"]])
    client = _client(user)

    assert client.get(ON_HAND, headers={"X-KDPS-Brand": "Peter England"}).status_code == 200
    assert client.get(ON_HAND, headers={"X-KDPS-Brand": "Mufti"}).status_code == 403


def test_the_brand_filter_does_not_restrict_anyone_else(db):
    _world()
    user = _user("owner", "owner", ScopeType.ALL)

    assert _skus(_client(user).get(ON_HAND)) == {"DEO-1", "PAT-1"}


# --- The switcher narrows what you read, never what you may do ------------
def test_choosing_a_unit_does_not_revoke_authority_over_another(db):
    """The top bar is a *view*, not a demotion. Someone entitled to both stores
    who happens to be looking at Deoghar may still decide Patna's approval —
    otherwise the act of looking somewhere else silently strips your rights."""
    w = _world()
    maker = _user("maker", "store_staff", ScopeType.STORE, stores=[w["pat"]])
    approval = _approval(w["pat"], maker, roles=["ho_ops"])
    boss = _user("ops", "ho_ops", ScopeType.ALL)

    decided = _client(boss).post(
        f"/api/approvals/{approval.pk}/decide",
        {"action": "approve"},
        format="json",
        headers={"X-KDPS-Unit": "DEO"},
    )

    assert decided.status_code == 200, decided.data


def test_choosing_a_unit_does_not_block_scanning_at_another(db):
    """Same rule at the scan counter: the scan screen names its own store, and
    an entitled user scanning there must not be refused because the top bar is
    showing somewhere else."""
    w = _world()
    user = _user("ops", "ho_ops", ScopeType.ALL)

    found = _client(user).get(
        f"/api/outbound/scan-lookup?store={w['pat'].pk}&barcode=PAT-1",
        headers={"X-KDPS-Unit": "DEO"},
    )

    assert found.status_code == 200, found.data


def test_an_unknown_brand_is_refused_not_silently_empty(db):
    """A unit that doesn't exist is a 403, so a brand that doesn't exist must be
    one too. Answering "no rows" to a typo is indistinguishable from answering
    "this brand genuinely has no stock" — the screen lies either way."""
    _world()
    user = _user("owner", "owner", ScopeType.ALL)

    assert _client(user).get(ON_HAND, headers={"X-KDPS-Brand": "NOPE"}).status_code == 403


# --- A brand boundary that only stock understands must not leak elsewhere --
def test_a_brand_manager_sees_no_rows_a_brand_cannot_narrow(db):
    """A brand manager's boundary is brands, and an approval carries no brand.
    Nothing can prove the row is theirs, so nothing is shown — deny-by-default
    (ADR-0003), not "network-wide because stores don't apply to me"."""
    w = _world()
    maker = _user("maker", "store_staff", ScopeType.STORE, stores=[w["pat"]])
    _approval(w["pat"], maker, roles=["brand_manager"])
    manager = _user("brand1", "brand_manager", ScopeType.BRAND, brands=[w["peter"]])

    assert _client(manager).get("/api/approvals").json() == []
    assert _client(manager).get("/api/approvals/inbox").json() == []


def test_a_brand_manager_cannot_act_on_a_store_they_cannot_name(db):
    """Reading is only half of it. The write gates ask "is this store in your
    list?" — and an empty list must mean *no*, not *any*."""
    w = _world()
    manager = _user("brand1", "brand_manager", ScopeType.BRAND, brands=[w["peter"]])

    created = _client(manager).post(
        "/api/inbound/grns",
        {
            "store_id": w["pat"].id,
            "kind": "branded",
            "invoice_number": "INV-BM",
            "lines": [{"style_code": "TEE-1", "size": "M", "color": "Blue", "received_qty": 3}],
        },
        format="json",
    )

    assert created.status_code == 403, created.data
