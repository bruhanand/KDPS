"""The store Dashboard aggregator (#174, D10 step 1).

`GET /api/store/dashboard` is one store's morning: what it sold (nothing yet -
the Sale document is #177), what is waiting for somebody, what is on the road,
and - for a manager only - how the month is going against the store's target.

It writes nothing, so what is worth testing is what it *answers*: which store it
decides it is about, which counts it puts on the queue, and who is shown the
manager row.

The five acceptance criteria on the ticket, in order:

  · the contract shape, store-scoped, manager block capability-gated;
  · every action-queue row is a count linking into a section that exists;
  · a cashier sees the money tiles, and no manager row;
  · month-to-date reads the targets master;
  · a fresh store renders noughts, never an error.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from alerts.models import Alert, AlertKind, AlertStatus
from approvals.models import Approval, ApprovalStatus
from core.documents import VoucherSeries
from core.fiscal import financial_year
from masters.models import Gstin, LegalEntity, Store, StoreTarget
from outbound.models import CountStatus, MarkDamaged, Stocktake, StoreTransfer, StoreTransferLine

URL = "/api/store/dashboard"

#: The six keys this build can honestly count. The other three in the contract
#: (`held_bills`, `uncosted_sale_lines`, `continuity_flags`) read `sell` tables
#: that #177-#186 create; see `storefront/dashboard.py` for why they are absent
#: rather than nought.
QUEUE_KEYS = [
    "approvals_pending",
    "transfers_to_receive",
    "grn_pt_pending",
    "quarantine_to_confirm",
    "rtb_windows_closing",
    "open_count_session",
]


@pytest.fixture
def network(db):
    entity = LegalEntity.objects.create(code="dash-ent", name="Dashboard Entity", pan="AAACD1234B")
    gstin = Gstin.objects.create(
        gstin="20AAACD1234B1ZQ", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    stores = {
        "deo": Store.objects.create(code="DASH-DEO", name="Dashboard Deoghar", gstin=gstin),
        "ran": Store.objects.create(code="DASH-RAN", name="Dashboard Ranchi", gstin=gstin),
    }
    # Documents in this suite are posted for real rather than INSERTed submitted:
    # the docstatus FSM trigger refuses a row that is born posted, and a count of
    # "submitted" rows that never walked the FSM would be counting a state the
    # application cannot produce.
    fy = financial_year(timezone.localdate())
    for store in stores.values():
        for doc_type in ("STO", "DMG"):
            VoucherSeries.objects.create(
                fy=fy,
                store_code=store.code,
                doc_type=doc_type,
                prefix=f"{store.code}/{doc_type}/{fy}/",
                next_seq=1,
            )
    return {"entity": entity, "gstin": gstin, **stores}


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _store_user(network, username: str, role_code: str, store: Store) -> User:
    user = User.objects.create_user(
        username=username,
        password=TEST_PASSWORD,
        role=make_role(role_code, f"{role_code} (dashboard test)"),
        entity=network["entity"],
        scope_type=ScopeType.STORE,
    )
    user.stores.add(store)
    return user


@pytest.fixture
def cashier(network):
    """`store_staff` - `sell: operate`. Bills, and does not authorise."""
    return _client(_store_user(network, "dash_cashier", "store_staff", network["deo"]))


def _retune_sell(user: User, capability: str) -> None:
    """Move this user's role to ``capability`` on Sell, in the stored row.

    Mutates the instance the client is authenticated as, not a second copy of the
    same row: `force_authenticate` hands the view *this* object, and a `Role`
    re-fetched by query would be saved without the request ever seeing it.
    """
    user.role.section_access["sell"] = {"capability": capability, "label": "Retuned by test"}
    user.role.save(update_fields=["section_access"])


@pytest.fixture
def manager_user(network):
    """A store manager holding `sell: approve` - the rung D10 spells "manager"
    with (over-cap override, plain return, dead-till handover).

    Granted here by retuning the stored row, because that is the only way it can
    be granted: the ratified sheet wrote one Sell cell for both store roles,
    ``operate``, and an override may only vary the sections the sheet left blank
    (`rbac_matrix._check_overrides_stay_off_the_sheet`). Moving a sheet cell is a
    two-administrator access change through the editor #173 built, not a code
    edit - so the gate reads the stored row and this fixture writes one. See
    `test_the_seeded_store_manager_does_not_hold_the_rung_yet` below.
    """
    user = _store_user(network, "dash_manager", "store_manager", network["deo"])
    _retune_sell(user, "approve")
    return user


@pytest.fixture
def manager(manager_user):
    return _client(manager_user)


@pytest.fixture
def owner(network):
    """Whole-entity scope: sees fifty stores and has picked none of them."""
    user = User.objects.create_user(
        username="dash_owner",
        password=TEST_PASSWORD,
        role=make_role("owner", "Owner (dashboard test)"),
        entity=network["entity"],
        scope_type=ScopeType.ENTITY,
    )
    return _client(user)


# --- which store is this? -------------------------------------------------


def test_a_store_login_gets_its_own_store_without_asking(cashier, network):
    body = cashier.get(URL).json()
    assert body["store"] == "DASH-DEO"


def test_naming_a_store_outside_your_entitlement_is_refused(cashier, network):
    r = cashier.get(URL, {"store": "DASH-RAN"})
    assert r.status_code == 403
    assert r.json()["code"] == "SCOPE_DENIED"


def test_that_same_caller_may_name_their_own_store(cashier):
    """The refusal above proves nothing unless its mirror passes - a 403 from the
    gate and a 403 from scope look identical from outside."""
    r = cashier.get(URL, {"store": "DASH-DEO"})
    assert r.status_code == 200
    assert r.json()["store"] == "DASH-DEO"


def test_a_network_login_with_no_unit_picked_is_asked_to_pick(owner):
    """Fifty stores in view is not one store's day. Answering with the first of
    them would be arbitrary, and arbitrary is worse than refused."""
    r = owner.get(URL)
    assert r.status_code == 403
    assert r.json()["code"] == "SCOPE_DENIED"
    assert "Pick a store" in r.json()["error"]


def test_the_top_bar_switcher_names_the_store_for_a_network_login(owner, network):
    body = owner.get(URL, headers={"X-KDPS-Unit": "DASH-RAN"}).json()
    assert body["store"] == "DASH-RAN"


def test_an_out_of_scope_unit_header_refuses_in_this_endpoints_own_shape(cashier):
    """The contract says this endpoint answers `{error, code}` and nothing else,
    so the scoping layer's own DRF refusal must not leak through."""
    r = cashier.get(URL, headers={"X-KDPS-Unit": "DASH-RAN"})
    assert r.status_code == 403
    assert r.json() == {"error": r.json()["error"], "code": "SCOPE_DENIED"}
    assert "detail" not in r.json()


def test_each_of_the_three_refusals_says_which_one_it_was(cashier, owner):
    """One code, three causes. The sentence is the only thing telling them
    apart, so a person who did pick a store is never told to pick one."""
    no_pick = owner.get(URL).json()["error"]
    bad_code = cashier.get(URL, {"store": "DASH-NOPE"}).json()["error"]
    bad_unit = cashier.get(URL, headers={"X-KDPS-Unit": "DASH-RAN"}).json()["error"]
    assert "Pick a store" in no_pick
    assert "DASH-NOPE" in bad_code
    assert "Pick a store" not in bad_unit
    assert len({no_pick, bad_code, bad_unit}) == 3


def test_a_named_store_may_not_outrank_the_unit_in_the_top_bar(owner, network):
    """The whole screen is gated once, on scope narrowed by the switcher, and
    every count then reads that one store. Letting `?store=` reach past the
    switcher would put two scope models on one page: the approvals row counts
    through `inbox_for`, which obeys the switcher, so it alone would read nought
    while the other five counted the store that was asked for."""
    r = owner.get(URL, {"store": "DASH-DEO"}, headers={"X-KDPS-Unit": "DASH-RAN"})
    assert r.status_code == 403
    assert r.json()["code"] == "SCOPE_DENIED"
    assert (
        owner.get(URL, {"store": "DASH-DEO"}, headers={"X-KDPS-Unit": "DASH-DEO"}).status_code
        == 200
    )


def test_every_row_counts_the_store_the_screen_says_it_is_about(owner, network):
    """The regression the gate above prevents, asserted on the rows themselves:
    with the switcher and `?store=` naming the same store, the approvals row is
    not quietly nought while the rest of the queue counts."""
    deo = network["deo"]
    _ask(network, deo, roles=["owner"])
    body = owner.get(URL, {"store": "DASH-DEO"}, headers={"X-KDPS-Unit": "DASH-DEO"}).json()
    counts = {row["key"]: row["count"] for row in body["action_queue"]}
    assert body["store"] == "DASH-DEO"
    assert counts["approvals_pending"] == 1


# --- a fresh store --------------------------------------------------------


def test_a_fresh_store_renders_noughts_and_never_errors(cashier):
    body = cashier.get(URL).json()
    assert body["today"] == {
        "net_sales_paise": 0,
        "bills": 0,
        "avg_bill_paise": 0,
        "pieces": 0,
        "collections": {"cash": 0, "card": 0, "upi": 0, "credit_note": 0},
        "vs_yesterday_pct": None,
    }
    assert [row["count"] for row in body["action_queue"]] == [0] * len(QUEUE_KEYS)
    assert body["live"] == {"offers": [], "in_transit": []}


def test_the_money_tiles_say_whether_they_can_count_at_all(cashier):
    """A store with no bills yet today and a store with no POS both read nought.
    `sales_live` is the only thing that tells the two apart, so the screen can."""
    assert cashier.get(URL).json()["sales_live"] is False


def test_the_sparkline_has_seven_dated_points_before_it_has_any_values(cashier):
    last7 = cashier.get(URL).json()["last7"]
    today = timezone.localdate()
    assert [row["date"] for row in last7] == [
        (today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)
    ]
    assert {row["net_sales_paise"] for row in last7} == {0}


def test_every_queue_row_is_a_key_this_build_can_actually_count(cashier):
    """The three `sell` keys are absent, not nought: nothing can be put on hold
    until there is a till, and "0 bills on hold" is a sentence about a morning."""
    body = cashier.get(URL).json()
    assert [row["key"] for row in body["action_queue"]] == QUEUE_KEYS


# --- the queue counts what is there ---------------------------------------


def test_the_queue_counts_this_stores_work_and_not_the_next_stores(cashier, manager, network):
    deo, ran = network["deo"], network["ran"]
    MarkDamaged.objects.create(store=deo)
    MarkDamaged.objects.create(store=deo)
    MarkDamaged.objects.create(store=ran)
    Stocktake.objects.create(store=deo, status=CountStatus.OPEN)
    Stocktake.objects.create(store=ran, status=CountStatus.OPEN)
    Alert.objects.create(
        kind=AlertKind.RETURN_WINDOW,
        kind_label="Return window",
        title="MUFTI at DASH-DEO",
        dedupe_key="return_window:dash:1",
        store=deo,
        status=AlertStatus.OPEN,
    )

    counts = {row["key"]: row["count"] for row in cashier.get(URL).json()["action_queue"]}
    assert counts["quarantine_to_confirm"] == 2
    assert counts["open_count_session"] == 1
    assert counts["rtb_windows_closing"] == 1


def test_a_confirmed_damage_report_leaves_the_queue(cashier, network):
    """The row is work waiting on a person, not a history of damage: a posted
    report has had its confirmation and belongs to quarantine now."""
    mark = MarkDamaged.objects.create(store=network["deo"])
    mark.post()
    counts = {row["key"]: row["count"] for row in cashier.get(URL).json()["action_queue"]}
    assert counts["quarantine_to_confirm"] == 0


def test_a_closed_count_leaves_the_queue(cashier, network):
    Stocktake.objects.create(store=network["deo"], status=CountStatus.CLOSED)
    counts = {row["key"]: row["count"] for row in cashier.get(URL).json()["action_queue"]}
    assert counts["open_count_session"] == 0


def _ask(network, store: Store, *, roles: list[str]) -> Approval:
    """Somebody at ``store`` asks for a damage report to be confirmed.

    Asked by a third person on purpose: `inbox_for` never offers you your own
    request, so an approval raised by the caller under test would count nought
    for the right reason and prove nothing.
    """
    return Approval.objects.create(
        kind="mark_damaged",
        kind_label="Damage",
        title=f"Damage at {store.code}",
        subject=MarkDamaged.objects.create(store=store),
        store=store,
        status=ApprovalStatus.PENDING,
        approver_roles=roles,
        made_by=_asker(network),
        requested_by=_asker(network),
    )


def _asker(network) -> User:
    existing = User.objects.filter(username="dash_asker").first()
    if existing:
        return existing
    return _store_user(network, "dash_asker", "store_staff", network["deo"])


def test_only_approvals_waiting_on_you_are_counted(cashier, network):
    """`inbox_for`'s rules, not a fresh count of pending rows: a card promising
    "1 waiting for you" that opens onto an empty inbox is worse than no card."""
    deo = network["deo"]
    _ask(network, deo, roles=["ho_ops"])
    counts = {row["key"]: row["count"] for row in cashier.get(URL).json()["action_queue"]}
    assert counts["approvals_pending"] == 0

    _ask(network, deo, roles=["store_staff"])
    counts = {row["key"]: row["count"] for row in cashier.get(URL).json()["action_queue"]}
    assert counts["approvals_pending"] == 1


def test_the_next_stores_approvals_are_not_on_your_queue(cashier, network):
    ran = network["ran"]
    _ask(network, ran, roles=["store_staff"])
    counts = {row["key"]: row["count"] for row in cashier.get(URL).json()["action_queue"]}
    assert counts["approvals_pending"] == 0


# --- what is on the road --------------------------------------------------


def _dispatch(source: Store, destination: Store, *, dispatched: int, received: int = 0) -> str:
    """A transfer on the road from ``source`` to ``destination``, posted through
    the FSM so it carries a real number."""
    transfer = StoreTransfer.objects.create(
        source_store=source,
        destination_store=destination,
        dispatch_date=timezone.now(),
        expected_arrival_note="Bus, Friday evening",
    )
    StoreTransferLine.objects.create(
        transfer=transfer,
        sku_code="DASH-SKU-1",
        qty_dispatched=dispatched,
        qty_received=received,
    )
    transfer.post()
    return transfer.doc_number or ""


def test_a_carton_on_the_road_is_both_a_queue_row_and_a_live_card(cashier, network):
    number = _dispatch(network["ran"], network["deo"], dispatched=40)
    body = cashier.get(URL).json()
    counts = {row["key"]: row["count"] for row in body["action_queue"]}
    assert counts["transfers_to_receive"] == 1
    assert body["live"]["in_transit"] == [
        {"doc_number": number, "pieces": 40, "expected": "Bus, Friday evening"}
    ]


def test_a_fully_scanned_in_carton_is_off_the_road(cashier, network):
    """The count and the card read the same three columns `qty_in_transit` does,
    so they cannot disagree with the transfer screen."""
    _dispatch(network["ran"], network["deo"], dispatched=40, received=40)
    body = cashier.get(URL).json()
    counts = {row["key"]: row["count"] for row in body["action_queue"]}
    assert counts["transfers_to_receive"] == 0
    assert body["live"]["in_transit"] == []


def test_a_carton_headed_elsewhere_is_not_this_stores_business(cashier, network):
    _dispatch(network["deo"], network["ran"], dispatched=5)
    counts = {row["key"]: row["count"] for row in cashier.get(URL).json()["action_queue"]}
    assert counts["transfers_to_receive"] == 0


def test_a_draft_transfer_is_not_yet_on_the_road(cashier, network):
    """Nothing has left the sending store until the document posts, so nothing is
    waiting to be received here."""
    transfer = StoreTransfer.objects.create(
        source_store=network["ran"],
        destination_store=network["deo"],
        dispatch_date=timezone.now(),
    )
    StoreTransferLine.objects.create(transfer=transfer, sku_code="DASH-SKU-3", qty_dispatched=9)
    body = cashier.get(URL).json()
    counts = {row["key"]: row["count"] for row in body["action_queue"]}
    assert counts["transfers_to_receive"] == 0
    assert body["live"]["in_transit"] == []


# --- the manager row ------------------------------------------------------


def test_a_cashier_sees_the_money_tiles_but_no_manager_row(cashier):
    body = cashier.get(URL).json()
    assert "today" in body
    assert "manager" not in body


def test_a_manager_gets_the_row_and_it_reads_the_targets_master(manager, network):
    StoreTarget.objects.create(
        store=network["deo"], month=timezone.localdate().replace(day=1), target_paise=250000000
    )
    body = manager.get(URL).json()
    assert body["manager"]["target_paise"] == 250000000
    assert body["manager"]["mtd_net_paise"] == 0
    assert body["manager"]["day_close"]["state"] == "not_built"


def test_a_month_with_no_target_set_reads_nought_not_missing(manager):
    """A store's month always has a number, even when nobody has set one - the
    row draws either way rather than blinking in and out of existence."""
    assert manager.get(URL).json()["manager"]["target_paise"] == 0


def test_last_months_target_is_not_this_months(manager, network):
    first = timezone.localdate().replace(day=1)
    last_month = (first - timedelta(days=1)).replace(day=1)
    StoreTarget.objects.create(store=network["deo"], month=last_month, target_paise=999900000)
    assert manager.get(URL).json()["manager"]["target_paise"] == 0


def test_the_manager_row_follows_the_stored_matrix_not_the_role_name(manager, manager_user):
    """Which role holds `sell: approve` is admin-editable data (#173), so the
    gate has to read the stored row. Drop the rung and the row goes with it, on
    the very next request - an approved access change is live immediately."""
    assert "manager" in manager.get(URL).json()
    _retune_sell(manager_user, "operate")
    assert "manager" not in manager.get(URL).json()


def test_the_money_rung_guards_the_target_here_as_it_does_on_the_master(network):
    """The row carries a store's target, and `StoreTarget` is Money data - the
    master that serves the same rows asks for `money: view`. A second door onto
    data with a lock on the first is not a second view of it.

    The case that proved it: IT Admin holds `sell: manage` and, by a ratified
    cell, no Money at all. Gating on Sell alone handed that seat the number.
    """
    StoreTarget.objects.create(
        store=network["deo"], month=timezone.localdate().replace(day=1), target_paise=250000000
    )
    it_admin = _store_user(network, "dash_it", "it_admin", network["deo"])
    assert it_admin.role.section_access["sell"]["capability"] == "manage"
    assert it_admin.role.section_access["money"]["capability"] == "none"
    assert "manager" not in _client(it_admin).get(URL).json()


def test_dropping_the_money_rung_takes_the_row_with_it(manager, manager_user):
    """The mirror of the above on the caller who does hold both: it is the Money
    rung doing the work, not a role name."""
    assert "manager" in manager.get(URL).json()
    manager_user.role.section_access["money"] = {"capability": "none", "label": "Retuned by test"}
    manager_user.role.save(update_fields=["section_access"])
    assert "manager" not in manager.get(URL).json()


def test_the_seeded_store_manager_does_not_hold_the_rung_yet(network):
    """Recorded, not asserted as desirable: the ratified sheet gives both store
    roles `sell: operate`, so out of the box the manager row reaches nobody at a
    store. D10 assumes a store manager can authorise - the grant is an access
    change two administrators make in the editor, and this test is what will
    fail, loudly and in the right place, on the day the sheet moves instead.
    """
    seeded = _client(_store_user(network, "dash_seeded_mgr", "store_manager", network["deo"]))
    assert "manager" not in seeded.get(URL).json()


def test_the_target_a_manager_reads_is_their_own_stores(manager, network):
    StoreTarget.objects.create(
        store=network["ran"], month=timezone.localdate().replace(day=1), target_paise=500000000
    )
    assert manager.get(URL).json()["manager"]["target_paise"] == 0


# --- the shape ------------------------------------------------------------


def test_the_payload_carries_every_block_the_contract_names(manager):
    body = manager.get(URL).json()
    assert set(body) == {
        "store",
        "sales_live",
        "today",
        "action_queue",
        "live",
        "last7",
        "manager",
    }
    assert isinstance(body["last7"], list)
    assert set(body["live"]) == {"offers", "in_transit"}


def test_an_anonymous_caller_gets_nothing(db):
    assert APIClient().get(URL).status_code in (401, 403)


def test_todays_first_of_month_is_the_month_the_target_is_keyed_on(manager, network):
    """Guards the one date arithmetic in the endpoint: `month` is the first of
    the month by DB constraint, and a lookup on today's date would find nothing
    on every day but the first."""
    assert date.today().replace(day=1).day == 1
    StoreTarget.objects.create(
        store=network["deo"], month=timezone.localdate().replace(day=1), target_paise=1
    )
    assert manager.get(URL).json()["manager"]["target_paise"] == 1
