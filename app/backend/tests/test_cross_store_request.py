"""The ask raised off the cross-store search (#175, D10 §3).

The search finds the piece somewhere else (``test_cross_store_availability``);
this is what happens when the counter taps "Request this". It is the ordinary
stock request with two things added and one thing deliberately absent:

- it carries **where it came from**, so "a customer asked and we didn't have it"
  is countable rather than lost;
- it carries the **time the counter quoted** the waiting customer — a quote, not
  a hold: nothing is reserved and the piece can still sell where it stands;
- and nothing anywhere checks whether the ask is *possible*. That was locked in
  the grill: the humans on the route have the phone call and the shelf, and a
  projection saying nought is a number the shop floor is routinely ahead of.

The route in front of it (own store manager → Operations Head, with the Ops-Head
short-circuit) is the chain ``test_approval_routes`` proves in general; here it
is walked end to end on the journey this ticket actually builds.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalStatus, ApprovalStepDecision
from core.documents import VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import StockRequest, StockRequestSource
from stockledger.models import StockOnHand

FY = "26-27"
#: The time the counter quoted, and the instant it must still mean after a round
#: trip. Compared as an instant, never as a string: the API renders in India's
#: timezone, so 17:30Z reads back as 23:00+05:30 - the same moment, spelt for the
#: person reading it.
QUOTED = "2026-08-02T17:30:00Z"
QUOTED_INSTANT = datetime(2026, 8, 2, 17, 30, tzinfo=UTC)


@pytest.fixture()
def rig(db):
    """Store A (asking, holds nothing), a warehouse (holding), and the three
    people on the route: the ``staff`` who raises it, their own ``manager``
    (step 1) and the ``ops`` head (step 2, who may short-circuit)."""
    entity = LegalEntity.objects.create(code="cs-ent", name="Cross Entity", pan="AAACC5432C")
    gstin = Gstin.objects.create(
        gstin="20AAACC5432C1ZS", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    warehouse = Store.objects.create(
        code="CS-WH", name="Cross Warehouse", gstin=gstin, store_type="warehouse"
    )
    store_a = Store.objects.create(code="CS-A", name="Cross Store A", gstin=gstin)
    store_b = Store.objects.create(code="CS-B", name="Cross Store B", gstin=gstin)

    Brand.objects.create(
        code="cs-br",
        name="CrossBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    def _user(username, role_code, scope=ScopeType.ALL, stores=()):
        user = User.objects.create_user(
            username=username,
            password=TEST_PASSWORD,
            role=make_role(role_code),
            entity=entity,
            scope_type=scope,
        )
        for store in stores:
            user.stores.add(store)
        return user

    staff = _user("cs_staff", "store_staff", scope=ScopeType.STORE, stores=[store_a])
    manager = _user("cs_manager", "store_manager", scope=ScopeType.STORE, stores=[store_a])
    ops = _user("cs_ops", "ho_ops")

    sku = Sku.objects.create(
        barcode="CS001",
        design="CH9001",
        color="Blue",
        size="L",
        brand="CrossBrand",
        item="Chinos",
        hsn="6203",
        mrp_paise=249900,
    )
    Cohort.objects.create(
        sku=sku, barcode="CS001", season="SS26", unit_cost_paise=120000, mrp_paise=249900
    )
    # Only the warehouse holds any. Store B holds none on purpose — it is the
    # store the "no availability check" test asks for stock from.
    StockOnHand.objects.create(
        store=warehouse,
        gstin=gstin,
        sku_code="CS001",
        design="CH9001",
        color="Blue",
        size="L",
        brand="CrossBrand",
        season="SS26",
        item="Chinos",
        hsn="6203",
        net_qty=6,
        net_value_paise=720000,
    )

    for code in ("CS-A", "CS-B", "CS-WH"):
        VoucherSeries.objects.create(
            fy=FY, store_code=code, doc_type="SRQ", prefix=f"{code}/SRQ/{FY}/", next_seq=1
        )
        VoucherSeries.objects.create(
            fy=FY, store_code=code, doc_type="STO", prefix=f"{code}/STO/{FY}/", next_seq=1
        )

    return {
        "warehouse": warehouse,
        "store_a": store_a,
        "store_b": store_b,
        "staff": staff,
        "manager": manager,
        "ops": ops,
    }


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _request_this(rig, actor=None, fulfilling=None, **extra):
    """ "Request this", the way the search-result button posts it."""
    return _client(actor or rig["staff"]).post(
        "/api/outbound/stock-requests",
        {
            "requesting_store": rig["store_a"].id,
            "fulfilling_store": (fulfilling or rig["warehouse"]).id,
            "lines": [
                {
                    "sku_code": "CS001",
                    "design": "CH9001",
                    "color": "Blue",
                    "size": "L",
                    "brand": "CrossBrand",
                    "season": "SS26",
                    "item": "Chinos",
                    "hsn": "6203",
                    "qty": 1,
                }
            ],
            **extra,
        },
        format="json",
    )


def _decide(request_id, actor, action="approve", reason=""):
    approval = Approval.objects.get(kind="stock_request", object_id=request_id)
    return _client(actor).post(
        f"/api/approvals/{approval.pk}/decide",
        {"action": action, "reason": reason},
        format="json",
    )


# ---------------------------------------------------------------------------
# What the search-raised ask carries
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_ask_carries_where_it_came_from_and_the_time_quoted(rig):
    resp = _request_this(rig, source="cross_store_search", expected_arrival_at=QUOTED)

    assert resp.status_code == 201, resp.data
    assert resp.data["source"] == StockRequestSource.CROSS_STORE_SEARCH
    assert resp.data["expected_arrival_at"] is not None

    stored = StockRequest.objects.get(pk=resp.data["id"])
    assert stored.source == StockRequestSource.CROSS_STORE_SEARCH
    assert stored.expected_arrival_at == QUOTED_INSTANT


@pytest.mark.django_db
def test_it_reads_back_on_the_request_the_store_watches(rig):
    """The counter quoted a time to a person who is going to come back and ask
    about it, so the detail screen has to be able to say it."""
    created = _request_this(rig, source="cross_store_search", expected_arrival_at=QUOTED)
    detail = _client(rig["staff"]).get(f"/api/outbound/stock-requests/{created.data['id']}")

    assert detail.status_code == 200, detail.data
    assert detail.data["source"] == "cross_store_search"
    assert datetime.fromisoformat(detail.data["expected_arrival_at"]) == QUOTED_INSTANT


@pytest.mark.django_db
def test_an_ask_raised_by_hand_is_unchanged(rig):
    """Every existing caller posts neither field. They must keep working, and
    keep being distinguishable from the ones the search raised."""
    resp = _request_this(rig)

    assert resp.status_code == 201, resp.data
    assert resp.data["source"] == StockRequestSource.MANUAL
    assert resp.data["expected_arrival_at"] is None


@pytest.mark.django_db
def test_no_hold_is_placed_on_the_piece(rig):
    """A quote, never a promise: the warehouse's six pieces are still six, all
    free to sell, and nothing sits in transit."""
    resp = _request_this(rig, source="cross_store_search", expected_arrival_at=QUOTED)
    assert resp.status_code == 201, resp.data

    on_hand = StockOnHand.objects.get(store=rig["warehouse"], sku_code="CS001")
    assert on_hand.net_qty == 6


# ---------------------------------------------------------------------------
# Possibility is the humans' call
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_store_holding_none_of_it_can_still_be_asked(rig):
    """Locked in the grill: no availability or blocking validation anywhere.

    CS-B holds nought of CS001 — the projection says so — and the ask still
    lands. The store manager on the phone knows about the box that came in this
    morning and the ledger does not.
    """
    resp = _request_this(
        rig, fulfilling=rig["store_b"], source="cross_store_search", expected_arrival_at=QUOTED
    )

    assert resp.status_code == 201, resp.data
    assert resp.data["status"] == "pending_approval"


@pytest.mark.django_db
def test_asking_for_more_than_exists_is_not_refused_either(rig):
    """Six on the shelf, sixty asked for. Still the approvers' call."""
    resp = _client(rig["staff"]).post(
        "/api/outbound/stock-requests",
        {
            "requesting_store": rig["store_a"].id,
            "fulfilling_store": rig["warehouse"].id,
            "source": "cross_store_search",
            "lines": [{"sku_code": "CS001", "design": "CH9001", "size": "L", "qty": 60}],
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data


# ---------------------------------------------------------------------------
# The route, walked on this journey
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_ask_walks_its_own_managers_step_then_the_ops_head(rig):
    created = _request_this(rig, source="cross_store_search", expected_arrival_at=QUOTED)
    request_id = created.data["id"]

    # Step 1 — the asking store's own manager, in the asking store's inbox.
    approval = Approval.objects.get(kind="stock_request", object_id=request_id)
    assert approval.store_id == rig["store_a"].id

    step_one = _decide(request_id, rig["manager"])
    assert step_one.status_code == 200, step_one.data
    assert step_one.data["status"] == ApprovalStatus.PENDING
    assert step_one.data["current_step"] == 1

    step_two = _decide(request_id, rig["ops"])
    assert step_two.status_code == 200, step_two.data
    assert step_two.data["status"] == ApprovalStatus.APPROVED

    assert StockRequest.objects.get(pk=request_id).status == "approved"


@pytest.mark.django_db
def test_the_ops_head_approves_it_directly_end_to_end(rig):
    """The direct-approve ruling on the real endpoint: the Operations Head does
    not wait for the manager's tap, and the step below closes behind them —
    recorded as closed *by the Operations Head*, never pretended away."""
    created = _request_this(rig, source="cross_store_search", expected_arrival_at=QUOTED)
    request_id = created.data["id"]

    resp = _decide(request_id, rig["ops"])

    assert resp.status_code == 200, resp.data
    assert resp.data["status"] == ApprovalStatus.APPROVED
    assert [s["state"] for s in resp.data["steps"]] == ["done", "done"]

    approval = Approval.objects.get(kind="stock_request", object_id=request_id)
    # ``step_order`` is the route's 0-based index: 0 is the manager's step.
    manager_step = ApprovalStepDecision.objects.get(approval=approval, step_order=0)
    assert manager_step.short_circuited is True
    assert manager_step.decided_by_id == rig["ops"].id

    assert StockRequest.objects.get(pk=request_id).status == "approved"


@pytest.mark.django_db
def test_an_approved_ask_keeps_the_time_the_counter_quoted(rig):
    """The quote survives the route — it is what the counter tells the customer
    when they ring back, and it must not be lost the moment HO touches it."""
    created = _request_this(rig, source="cross_store_search", expected_arrival_at=QUOTED)
    request_id = created.data["id"]
    _decide(request_id, rig["ops"])

    detail = _client(rig["staff"]).get(f"/api/outbound/stock-requests/{request_id}")
    assert detail.data["status"] == "approved"
    assert datetime.fromisoformat(detail.data["expected_arrival_at"]) == QUOTED_INSTANT
    assert detail.data["source"] == "cross_store_search"
