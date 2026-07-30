"""The store-wise monthly target master (#171, D10 step 1).

One rupee target per store per month, set at HO and read by the store Dashboard.
It is a *master*, not a document - nothing posts, nothing balances - so the whole
slice is one table and one endpoint, and everything worth testing is at that
endpoint: who may write it, who may read whose, and which months are a month.

The four properties the ticket asks for:

  · upsert keyed on (store, first-of-month) - a second PUT corrects, never doubles;
  · a store login reads its own store's target and no other's;
  · writing needs ``money: manage``, and the row records who set it;
  · the grid the HO screen draws is one FY's worth of rows.
"""

from __future__ import annotations

from datetime import date

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from masters.models import Gstin, LegalEntity, Store, StoreTarget

URL = "/api/masters/store-targets"

#: ₹25,00,000 for a month, in paise - a plausible KDPS store's monthly number.
AUGUST_TARGET = 250000000


@pytest.fixture
def network(db):
    entity = LegalEntity.objects.create(code="tgt-ent", name="Target Entity", pan="AAACT1234B")
    gstin = Gstin.objects.create(
        gstin="20AAACT1234B1ZQ", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    return {
        "entity": entity,
        "deo": Store.objects.create(code="TGT-DEO", name="Target Deoghar", gstin=gstin),
        "bnk": Store.objects.create(code="TGT-BNK", name="Target Banka", gstin=gstin),
    }


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def books_keeper(network):
    """Owner - `money: manage`, scoped to the whole entity. The rung the matrix
    puts the target-setting cell behind."""
    user = User.objects.create_user(
        username="tgt_owner",
        password=TEST_PASSWORD,
        role=make_role("owner", "Owner (targets test)"),
        entity=network["entity"],
        scope_type=ScopeType.ENTITY,
    )
    return _client(user)


@pytest.fixture
def store_login(network):
    """A store manager at Deoghar - `money: operate`, so they read the section but
    may not write in it, and their scope is one store."""
    user = User.objects.create_user(
        username="tgt_sm",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (targets test)"),
        entity=network["entity"],
        scope_type=ScopeType.STORE,
    )
    user.stores.add(network["deo"])
    return _client(user)


@pytest.fixture
def brand_manager(network):
    """`money: none` - the section is closed to them outright."""
    user = User.objects.create_user(
        username="tgt_bm",
        password=TEST_PASSWORD,
        role=make_role("brand_manager", "Brand Manager (targets test)"),
        entity=network["entity"],
        scope_type=ScopeType.BRAND,
    )
    return _client(user)


def put(client: APIClient, store: str, month: str, target: int = AUGUST_TARGET):
    return client.put(URL, {"store": store, "month": month, "target_paise": target}, format="json")


# --- Upsert on (store, month) ---------------------------------------------


def test_first_put_creates_the_target(books_keeper, network):
    r = put(books_keeper, "TGT-DEO", "2026-08-01")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["store"] == "TGT-DEO"
    assert body["month"] == "2026-08-01"
    assert body["target_paise"] == AUGUST_TARGET
    assert StoreTarget.objects.count() == 1


def test_second_put_corrects_rather_than_doubles(books_keeper, network):
    """A target is a number, not an event: setting it again is a correction.

    The unique key is what makes that true, and it is the reason this endpoint is
    a PUT - a POST that appended would leave two answers to "what is August's
    target?" and no rule for picking one."""
    put(books_keeper, "TGT-DEO", "2026-08-01")
    r = put(books_keeper, "TGT-DEO", "2026-08-01", target=300000000)
    assert r.status_code == 200
    assert StoreTarget.objects.count() == 1
    assert StoreTarget.objects.get().target_paise == 300000000


def test_each_store_and_month_is_its_own_row(books_keeper, network):
    put(books_keeper, "TGT-DEO", "2026-08-01")
    put(books_keeper, "TGT-DEO", "2026-09-01")
    put(books_keeper, "TGT-BNK", "2026-08-01")
    assert StoreTarget.objects.count() == 3


# --- What a month is ------------------------------------------------------


@pytest.mark.parametrize("month", ["2026-08-15", "2026-08-31", "2026-02-29"])
def test_a_month_must_be_its_first_day(books_keeper, network, month):
    """The column *is* the month, so mid-month dates are refused rather than
    silently truncated: two callers sending the 15th and the 20th of August must
    not be able to create two rows that both mean August."""
    r = put(books_keeper, "TGT-DEO", month)
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION"
    assert not StoreTarget.objects.exists()


def test_a_negative_target_is_refused(books_keeper, network):
    r = put(books_keeper, "TGT-DEO", "2026-08-01", target=-1)
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION"
    assert not StoreTarget.objects.exists()


def test_zero_is_a_legitimate_target(books_keeper, network):
    """A store that is closed for the month has a target, and it is nought - the
    rule is ``>= 0``, so nought must not be mistaken for "unset"."""
    r = put(books_keeper, "TGT-DEO", "2026-08-01", target=0)
    assert r.status_code == 200
    assert StoreTarget.objects.get().target_paise == 0


@pytest.mark.parametrize("target", ["25 lakh", 1.5, None, "", "1e6"])
def test_a_target_that_is_not_whole_paise_is_refused(books_keeper, network, target):
    """Money is integer paise (ADR-0004). A rupee decimal arriving here means the
    conversion was skipped upstream, and the money column would rather refuse it
    than round it."""
    r = put(books_keeper, "TGT-DEO", "2026-08-01", target=target)
    assert r.status_code == 400, r.json()
    assert r.json()["code"] == "VALIDATION"
    assert not StoreTarget.objects.exists()


def test_an_unknown_store_is_not_found(books_keeper, network):
    r = put(books_keeper, "NOPE", "2026-08-01")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


# --- The write gate and the actor stamp -----------------------------------


def test_the_actor_is_stamped_on_the_row(books_keeper, network):
    """Who moved a store's number is part of the answer, not metadata: the
    Dashboard shows the target, and the only way back to a person is this stamp."""
    put(books_keeper, "TGT-DEO", "2026-08-01")
    assert StoreTarget.objects.get().set_by.username == "tgt_owner"


def test_a_store_login_may_not_write_a_target(store_login, network):
    """`money: operate` ("Expenses only") reads the section and writes nothing in
    it - a store must not be able to set the number it is judged against."""
    r = put(store_login, "TGT-DEO", "2026-08-01")
    assert r.status_code == 403
    assert not StoreTarget.objects.exists()


def test_money_closed_means_the_endpoint_is_closed(brand_manager, network):
    assert brand_manager.get(URL).status_code == 403
    assert put(brand_manager, "TGT-DEO", "2026-08-01").status_code == 403


def test_anonymous_is_refused(network):
    assert APIClient().get(URL).status_code == 401
    assert APIClient().put(URL, {}, format="json").status_code == 401


# --- Reads, and whose ------------------------------------------------------


@pytest.fixture
def seeded(books_keeper, network):
    put(books_keeper, "TGT-DEO", "2026-08-01")
    put(books_keeper, "TGT-BNK", "2026-08-01", target=100000000)
    return network


def test_ho_reads_every_store(books_keeper, seeded):
    rows = books_keeper.get(URL).json()
    assert {row["store"] for row in rows} == {"TGT-DEO", "TGT-BNK"}


def test_a_store_login_reads_only_its_own_store(store_login, seeded):
    """The acceptance criterion, and the one that would fail silently: a store
    manager asking the same question gets one row, not the network's."""
    rows = store_login.get(URL).json()
    assert [row["store"] for row in rows] == ["TGT-DEO"]


def test_a_store_login_cannot_widen_by_asking(store_login, seeded):
    """`?store=` filters within scope; it never reaches past it."""
    rows = store_login.get(f"{URL}?store=TGT-BNK").json()
    assert rows == []


def test_store_filter_narrows_for_ho(books_keeper, seeded):
    rows = books_keeper.get(f"{URL}?store=TGT-DEO").json()
    assert [row["store"] for row in rows] == ["TGT-DEO"]


def test_fy_filter_returns_one_financial_year(books_keeper, network):
    """The grid is drawn a financial year at a time (Apr–Mar), so the filter has
    to cut on the Indian FY and not on the calendar year: March 2027 belongs with
    August 2026, and April 2027 does not."""
    put(books_keeper, "TGT-DEO", "2026-08-01")
    put(books_keeper, "TGT-DEO", "2027-03-01")
    put(books_keeper, "TGT-DEO", "2027-04-01")
    rows = books_keeper.get(f"{URL}?fy=26-27").json()
    assert {row["month"] for row in rows} == {"2026-08-01", "2027-03-01"}


def test_rows_come_back_in_store_then_month_order(books_keeper, network):
    """A grid reads rows into cells; a stable order is what lets the screen do
    that without sorting twice."""
    put(books_keeper, "TGT-DEO", "2026-09-01")
    put(books_keeper, "TGT-BNK", "2026-08-01")
    put(books_keeper, "TGT-DEO", "2026-08-01")
    rows = books_keeper.get(URL).json()
    assert [(r["store"], r["month"]) for r in rows] == [
        ("TGT-BNK", "2026-08-01"),
        ("TGT-DEO", "2026-08-01"),
        ("TGT-DEO", "2026-09-01"),
    ]


def test_an_unknown_fy_is_refused_rather_than_ignored(books_keeper, seeded):
    """A filter nobody honours is worse than one that refuses: silently returning
    the whole network for `?fy=garbage` is how a screen shows the wrong year."""
    r = books_keeper.get(f"{URL}?fy=2026")
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION"


# --- The switcher gets no vote ---------------------------------------------
#
# The grid's rows come from `/masters/stores`, which is deliberately not narrowed
# by the top-bar unit; its cells come from this endpoint. If the two were gated
# differently the screen would show every store's row with only the picked
# store's numbers in it - "no target set" printed over targets that exist, and
# the year's total collapsing to one store. These hold them to one boundary.


def test_the_top_bar_unit_does_not_hide_other_stores_targets(books_keeper, seeded):
    with_unit = books_keeper.get(URL, headers={"X-KDPS-Unit": "TGT-DEO"}).json()
    assert {row["store"] for row in with_unit} == {"TGT-DEO", "TGT-BNK"}


def test_the_rows_and_the_cells_answer_to_the_same_boundary(books_keeper, seeded):
    """Stated as the property rather than as two counts: whatever the switcher is
    set to, every store the picker offers is a store whose targets came back."""
    for unit in ["", "TGT-DEO", "TGT-BNK"]:
        headers = {"X-KDPS-Unit": unit} if unit else {}
        offered = {row["code"] for row in books_keeper.get("/api/masters/stores").json()}
        answered = {row["store"] for row in books_keeper.get(URL, headers=headers).json()}
        assert answered <= offered
        assert answered == {"TGT-DEO", "TGT-BNK"}


def test_a_store_login_is_still_held_to_its_own_store(store_login, seeded):
    """Ignoring the switcher must not be read as ignoring scope. Same request,
    same one row, whichever unit the header names."""
    for unit in ["", "TGT-DEO"]:
        headers = {"X-KDPS-Unit": unit} if unit else {}
        rows = store_login.get(URL, headers=headers).json()
        assert [row["store"] for row in rows] == ["TGT-DEO"]


# --- Writing where you are not entitled ------------------------------------


@pytest.fixture
def out_of_scope_keeper(network):
    """`money: manage`, but entitled to one store. The rung says what a person may
    do; it never says where."""
    user = User.objects.create_user(
        username="tgt_acct",
        password=TEST_PASSWORD,
        role=make_role("accounts", "Accounts (targets test)"),
        entity=network["entity"],
        scope_type=ScopeType.STORE,
    )
    user.stores.add(network["deo"])
    return _client(user)


def test_the_money_rung_does_not_reach_past_the_stores_you_hold(out_of_scope_keeper, network):
    r = put(out_of_scope_keeper, "TGT-BNK", "2026-08-01")
    assert r.status_code == 403
    assert r.json()["code"] == "SCOPE_DENIED"
    assert not StoreTarget.objects.exists()


def test_that_same_caller_may_still_set_their_own_store(out_of_scope_keeper, network):
    """The negative above has to be scope and not the gate, so its mirror runs
    beside it: the refusal proves nothing unless the allowed case passes."""
    assert put(out_of_scope_keeper, "TGT-DEO", "2026-08-01").status_code == 200
    assert StoreTarget.objects.get().store.code == "TGT-DEO"


def test_a_closed_store_gets_no_target(books_keeper, network):
    """A store that is shut is not a store to plan against, so it answers as one
    that never existed rather than accepting a number nobody will sell."""
    network["bnk"].is_active = False
    network["bnk"].save(update_fields=["is_active"])
    r = put(books_keeper, "TGT-BNK", "2026-08-01")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


# --- The model's own guard -------------------------------------------------


def test_the_database_refuses_a_negative_target(network):
    """The API validates, and the table refuses independently: a raw write is
    still a write, and "no store owes a negative month" is a property of the
    data, not of the endpoint that usually creates it."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        StoreTarget.objects.create(store=network["deo"], month=date(2026, 8, 1), target_paise=-100)


def test_the_database_refuses_a_mid_month_date(network):
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        StoreTarget.objects.create(store=network["deo"], month=date(2026, 8, 15), target_paise=100)
