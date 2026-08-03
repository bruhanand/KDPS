"""The network location list (#147) — where a transfer may be *sent*.

A store person scoped to one store got an empty destination picker and could not
start a transfer at all, because both pickers were fed from the scoped store
list. The destination now has its own feed; `masters.views.LocationListView`
carries the argument for why it is unscoped. These tests hold it to the price of
that: the whole network, identity fields only, and never the same list as
`/masters/stores`.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from masters.models import Gstin, LegalEntity, Store

# Exactly what a picker needs to name a place and tell whether sending there is
# a cross-registration supply. Nothing costed, nothing scope-sensitive (#132).
IDENTITY_FIELDS = {"id", "code", "name", "store_type", "gstin", "state_code", "state_name"}


@pytest.fixture
def network(db):
    entity = LegalEntity.objects.create(code="loc-ent", name="Location Entity", pan="AAACL1234B")
    gstin_jh = Gstin.objects.create(
        gstin="20AAACL1234B1ZQ", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    gstin_bh = Gstin.objects.create(
        gstin="10AAACL1234B1ZQ", state_code="10", state_name="Bihar", legal_entity=entity
    )
    home = Store.objects.create(code="LOC-DEO", name="Loc Deoghar", gstin=gstin_jh)
    Store.objects.create(code="LOC-BNK", name="Loc Banka", gstin=gstin_bh)
    Store.objects.create(
        code="LOC-WH", name="Loc Warehouse", gstin=gstin_jh, store_type=Store.StoreType.WAREHOUSE
    )
    Store.objects.create(code="LOC-OLD", name="Loc Closed", gstin=gstin_jh, is_active=False)
    return {"entity": entity, "home": home}


@pytest.fixture
def store_user(network):
    user = User.objects.create_user(
        username="loc_sm",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (locations test)"),
        entity=network["entity"],
        scope_type=ScopeType.STORE,
    )
    user.stores.add(network["home"])
    client = APIClient()
    client.force_authenticate(user)
    return client


def codes(response):
    return {row["code"] for row in response.json()}


def test_store_user_sees_the_whole_network(store_user):
    """The picker a store person needs: every active location, both states."""
    r = store_user.get("/api/masters/locations")
    assert r.status_code == 200
    assert codes(r) == {"LOC-DEO", "LOC-BNK", "LOC-WH"}


def test_locations_are_not_the_scoped_stores_list(store_user):
    """The two pickers must not be collapsible back onto one source: the scoped
    list is what this person may operate on (their own store), the network list
    is where they may send."""
    scoped = codes(store_user.get("/api/masters/stores"))
    network = codes(store_user.get("/api/masters/locations"))
    assert scoped == {"LOC-DEO"}
    assert network > scoped


def test_closed_locations_are_not_offered(store_user):
    assert "LOC-OLD" not in codes(store_user.get("/api/masters/locations"))


def test_identity_fields_only(store_user):
    """Unscoped means lean: a name, a type, a registration and a state — nothing
    costed and nothing the caller's scope would otherwise have hidden."""
    rows = store_user.get("/api/masters/locations").json()
    assert rows, "expected the network to be non-empty"
    for row in rows:
        assert set(row) == IDENTITY_FIELDS


def test_registration_and_state_travel_with_each_location(store_user, network):
    """Cross-state detection is the screen's job and it reads this list, so both
    the registration it compares and the state it names have to be on every row.

    The registration is what `StoreTransfer.save()` compares to set
    `is_cross_state`, so serving it here is what keeps the warning on screen and
    the flag in the books saying the same thing."""
    by_code = {row["code"]: row for row in store_user.get("/api/masters/locations").json()}
    assert by_code["LOC-DEO"]["gstin"] == Store.objects.get(code="LOC-DEO").gstin_id
    assert by_code["LOC-DEO"]["gstin"] != by_code["LOC-BNK"]["gstin"]
    assert by_code["LOC-DEO"]["gstin"] == by_code["LOC-WH"]["gstin"]
    assert by_code["LOC-DEO"]["state_code"] == "20"
    assert by_code["LOC-BNK"]["state_code"] == "10"
    assert by_code["LOC-BNK"]["state_name"] == "Bihar"


def test_anonymous_is_refused(network):
    assert APIClient().get("/api/masters/locations").status_code == 401
