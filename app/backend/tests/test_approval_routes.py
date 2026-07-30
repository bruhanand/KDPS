"""Approval routes as data — multi-step chains and the Ops-Head short-circuit (#172).

The approvals app learns **ordered routes stored as rows**: a route names its
steps, each step names the roles that may clear it, and approving the current
step advances the request to the next one. A later step may be marked
short-circuitable, which is the D10 ruling in one flag — the Operations Head
approves a stock request directly and the store manager's step closes behind
them, recorded with the actual actor rather than pretended away.

A request with **no route keeps today's behaviour exactly**: one decision, one
approver, done. That is the first thing this suite pins, because every other
approval family in the system rides it.

Two seams:

- **Service seam** (``approvals.services.decide``) — progression, short-circuit,
  the role gate at each step, reject-needs-reason, and maker ≠ checker at
  *every* step.
- **API seam** — a stock request raised through the real endpoint walks the
  seeded route, moves between the two approvers' inboxes as it goes, and reports
  its step trail the way the Approvals screen reads it.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalRoute, ApprovalStatus, ApprovalStepDecision
from approvals.services import (
    NotAnApproverError,
    SelfApprovalError,
    decide,
    inbox_for,
)
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.maker_checker import request_document_approval
from outbound.models import StockRequest, WriteOff, WriteOffLine
from stockledger.models import StockOnHand

FY = "26-27"


# ---------------------------------------------------------------------------
# Rig
# ---------------------------------------------------------------------------


@pytest.fixture()
def rig(db):
    """Two stores and the four people around a cross-store ask: the ``staff``
    who raises it, their own ``manager`` (step 1), the ``ops`` head (step 2,
    who may short-circuit), and an ``owner``."""
    entity = LegalEntity.objects.create(code="ar-ent", name="Route Entity", pan="AAACR9876C")
    gstin = Gstin.objects.create(
        gstin="20AAACR9876C1ZS", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    warehouse = Store.objects.create(
        code="AR-WH", name="Route Warehouse", gstin=gstin, store_type="warehouse"
    )
    store_a = Store.objects.create(code="AR-A", name="Route Store A", gstin=gstin)

    Brand.objects.create(
        code="ar-br",
        name="RouteBrand",
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

    staff = _user("ar_staff", "store_staff", scope=ScopeType.STORE, stores=[store_a])
    manager = _user("ar_manager", "store_manager", scope=ScopeType.STORE, stores=[store_a])
    other_manager = _user(
        "ar_other_mgr", "store_manager", scope=ScopeType.STORE, stores=[warehouse]
    )
    ops = _user("ar_ops", "ho_ops")
    owner = _user("ar_owner", "owner")
    accountant = _user("ar_accounts", "accounts")

    sku = Sku.objects.create(
        barcode="AR001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="RouteBrand",
        item="shirt",
        hsn="6205",
        mrp_paise=99900,
    )
    Cohort.objects.create(
        sku=sku, barcode="AR001", season="SS26", unit_cost_paise=45000, mrp_paise=99900
    )
    StockOnHand.objects.create(
        store=warehouse,
        sku_code="AR001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="RouteBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        net_qty=20,
    )

    return {
        "entity": entity,
        "warehouse": warehouse,
        "store_a": store_a,
        "staff": staff,
        "manager": manager,
        "other_manager": other_manager,
        "ops": ops,
        "owner": owner,
        "accountant": accountant,
    }


def _client(user) -> APIClient:
    client = APIClient()
    resp = client.post(
        "/api/auth/login", {"username": user.username, "password": TEST_PASSWORD}, format="json"
    )
    assert resp.status_code == 200, resp.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


def _raise_request(rig, actor=None) -> dict:
    """Raise a stock request through the real endpoint, as the counter would."""
    client = _client(actor or rig["staff"])
    resp = client.post(
        "/api/outbound/stock-requests",
        {
            "requesting_store": rig["store_a"].id,
            "fulfilling_store": rig["warehouse"].id,
            "lines": [{"sku_code": "AR001", "qty": 4}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data


def _write_off(rig) -> WriteOff:
    """An unrouted document — the single-step family this suite must not break."""
    write_off = WriteOff.objects.create(
        store=rig["store_a"], reason="damaged", created_by=rig["staff"]
    )
    WriteOffLine.objects.create(
        writeoff=write_off,
        sku_code="AR001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="RouteBrand",
        season="SS26",
        qty=2,
        unit_cost_paise=45000,
    )
    return write_off


# ---------------------------------------------------------------------------
# The seed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_stock_request_route_is_seeded_with_two_steps(db):
    route = ApprovalRoute.objects.get(kind="stock_request")
    steps = route.ordered_steps()

    assert [s["order"] for s in steps] == [1, 2]
    assert "store_manager" in steps[0]["roles"]
    assert "ho_ops" in steps[1]["roles"]
    # The direct-approve ruling: the Operations Head's step closes the one below.
    assert steps[0]["later_step_may_short_circuit"] is False
    assert steps[1]["later_step_may_short_circuit"] is True


# ---------------------------------------------------------------------------
# A null route is today's behaviour, untouched
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_unrouted_approval_still_decides_in_one_step(rig):
    """The write-off family has no route; one approval still finishes it."""
    approval = request_document_approval(_write_off(rig), requested_by=rig["staff"])

    assert approval.route_id is None
    assert approval.current_step == 0
    assert approval.step_trail() == []

    decided = decide(approval, actor=rig["manager"], action="approve")

    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by_id == rig["manager"].id
    assert not ApprovalStepDecision.objects.filter(approval=decided).exists()


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_routed_approval_advances_one_step_at_a_time(rig):
    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])

    assert approval.route is not None
    assert approval.current_step == 0
    # Who may act *now* is the step's own roles plus any later step allowed to
    # close it — that is what the inbox filter reads, so it has to be on the row.
    assert "store_manager" in approval.approver_roles
    assert "ho_ops" in approval.approver_roles

    after_step_one = decide(approval, actor=rig["manager"], action="approve")

    # Still waiting: the manager cleared their step, not the request.
    assert after_step_one.status == ApprovalStatus.PENDING
    assert after_step_one.current_step == 1
    assert after_step_one.approver_roles == ["ho_ops", "owner"]
    assert after_step_one.decided_by_id is None

    final = decide(after_step_one, actor=rig["ops"], action="approve")

    assert final.status == ApprovalStatus.APPROVED
    assert final.decided_by_id == rig["ops"].id
    assert final.decided_at is not None

    trail = list(ApprovalStepDecision.objects.filter(approval=final).order_by("step_order"))
    assert [(d.step_order, d.decided_by_id, d.short_circuited) for d in trail] == [
        (0, rig["manager"].id, False),
        (1, rig["ops"].id, False),
    ]


@pytest.mark.django_db
def test_a_cleared_step_leaves_that_approvers_inbox_and_enters_the_next(rig):
    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])

    # Step 1 is the *requesting* store's manager — the ask is theirs to sanity
    # check before it reaches HO. The warehouse's own manager is not asked.
    assert list(inbox_for(rig["manager"]).values_list("id", flat=True)) == [approval.id]
    assert list(inbox_for(rig["other_manager"]).values_list("id", flat=True)) == []
    # The Operations Head sees it from the start: theirs is the step that may
    # close the one below it.
    assert approval.id in set(inbox_for(rig["ops"]).values_list("id", flat=True))

    decide(approval, actor=rig["manager"], action="approve")

    assert list(inbox_for(rig["manager"]).values_list("id", flat=True)) == []
    assert approval.id in set(inbox_for(rig["ops"]).values_list("id", flat=True))


# ---------------------------------------------------------------------------
# The short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_operations_head_approves_directly_and_the_step_below_closes(rig):
    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])

    final = decide(approval, actor=rig["ops"], action="approve")

    assert final.status == ApprovalStatus.APPROVED
    assert final.decided_by_id == rig["ops"].id

    trail = list(ApprovalStepDecision.objects.filter(approval=final).order_by("step_order"))
    assert len(trail) == 2
    # The closed step names who actually closed it — never the manager who
    # never touched it.
    assert trail[0].short_circuited is True
    assert trail[0].decided_by_id == rig["ops"].id
    assert trail[1].short_circuited is False
    assert trail[1].decided_by_id == rig["ops"].id


@pytest.mark.django_db
def test_an_earlier_step_may_not_reach_forward(rig):
    """Short-circuit runs one way only: a store manager never clears HO's step."""
    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])
    decide(approval, actor=rig["manager"], action="approve")

    approval.refresh_from_db()
    with pytest.raises(NotAnApproverError):
        decide(approval, actor=rig["other_manager"], action="approve")

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING
    assert approval.current_step == 1


@pytest.mark.django_db
def test_a_role_on_no_remaining_step_cannot_decide(rig):
    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])

    with pytest.raises(NotAnApproverError):
        decide(approval, actor=rig["accountant"], action="approve")


# ---------------------------------------------------------------------------
# Maker ≠ checker, at every step
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_maker_cannot_clear_a_step_even_when_their_role_is_on_it(rig):
    """A manager who raised the ask themselves does not also approve step 1."""
    data = _raise_request(rig, actor=rig["manager"])
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])

    with pytest.raises(SelfApprovalError):
        decide(approval, actor=rig["manager"], action="approve")


@pytest.mark.django_db
def test_one_person_cannot_clear_two_steps_of_the_same_request(rig):
    """Two steps means two people. A role listed on both is still one pair of
    hands, and a chain cleared start-to-finish by one person is no chain."""
    route = ApprovalRoute.objects.get(kind="stock_request")
    route.steps = [
        {"order": 1, "roles": ["ho_ops"], "label": "First", "later_step_may_short_circuit": False},
        {"order": 2, "roles": ["ho_ops"], "label": "Second", "later_step_may_short_circuit": False},
    ]
    route.save(update_fields=["steps"])

    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])
    decide(approval, actor=rig["ops"], action="approve")

    approval.refresh_from_db()
    with pytest.raises(SelfApprovalError):
        decide(approval, actor=rig["ops"], action="approve")


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_reject_at_the_first_step_needs_a_reason_and_ends_the_request(rig):
    from approvals.services import ApprovalError

    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])

    with pytest.raises(ApprovalError):
        decide(approval, actor=rig["manager"], action="reject")

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING

    rejected = decide(
        approval, actor=rig["manager"], action="reject", reason="Customer changed their mind"
    )

    assert rejected.status == ApprovalStatus.REJECTED
    assert rejected.reason == "Customer changed their mind"
    # It died at step 1 and the record says so — no step was ever cleared.
    assert rejected.current_step == 0
    assert not ApprovalStepDecision.objects.filter(approval=rejected).exists()


@pytest.mark.django_db
def test_a_reject_at_a_later_step_records_where_it_died(rig):
    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])
    decide(approval, actor=rig["manager"], action="approve")

    approval.refresh_from_db()
    rejected = decide(approval, actor=rig["ops"], action="reject", reason="No stock to spare")

    assert rejected.status == ApprovalStatus.REJECTED
    assert rejected.current_step == 1
    states = [step["state"] for step in rejected.step_trail()]
    assert states == ["done", "rejected"]


# ---------------------------------------------------------------------------
# The trail the screen reads
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_step_trail_reads_as_the_screen_shows_it(rig):
    data = _raise_request(rig)
    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])

    trail = approval.step_trail()
    assert [step["state"] for step in trail] == ["current", "waiting"]
    assert trail[0]["label"] == "Store manager"
    assert trail[1]["label"] == "Operations Head"

    decide(approval, actor=rig["manager"], action="approve")
    approval.refresh_from_db()

    trail = approval.step_trail()
    assert [step["state"] for step in trail] == ["done", "current"]
    assert trail[0]["decided_by_name"] == rig["manager"].username
    assert trail[0]["decided_at"] is not None
    assert trail[0]["short_circuited"] is False


@pytest.mark.django_db
def test_the_api_walks_the_chain_and_reports_each_step(rig):
    """End to end, the way the Approvals screen drives it."""
    data = _raise_request(rig)
    approval_id = Approval.objects.get(kind="stock_request", object_id=data["id"]).id

    manager_client = _client(rig["manager"])
    inbox = manager_client.get("/api/approvals/inbox")
    assert inbox.status_code == 200
    row = next(r for r in inbox.data if r["id"] == approval_id)
    assert row["current_step"] == 0
    assert [s["state"] for s in row["steps"]] == ["current", "waiting"]

    step_one = manager_client.post(
        f"/api/approvals/{approval_id}/decide", {"action": "approve"}, format="json"
    )
    assert step_one.status_code == 200, step_one.data
    assert step_one.data["status"] == ApprovalStatus.PENDING
    assert step_one.data["current_step"] == 1
    assert [s["state"] for s in step_one.data["steps"]] == ["done", "current"]

    # Cleared, so it is gone from the manager's inbox and still in HO's.
    assert all(r["id"] != approval_id for r in manager_client.get("/api/approvals/inbox").data)

    ops_client = _client(rig["ops"])
    assert any(r["id"] == approval_id for r in ops_client.get("/api/approvals/inbox").data)

    step_two = ops_client.post(
        f"/api/approvals/{approval_id}/decide", {"action": "approve"}, format="json"
    )
    assert step_two.status_code == 200, step_two.data
    assert step_two.data["status"] == ApprovalStatus.APPROVED
    assert [s["state"] for s in step_two.data["steps"]] == ["done", "done"]

    assert StockRequest.objects.get(pk=data["id"]).status == "approved"


@pytest.mark.django_db
def test_the_api_refuses_a_step_the_callers_role_is_not_on(rig):
    data = _raise_request(rig)
    approval_id = Approval.objects.get(kind="stock_request", object_id=data["id"]).id

    resp = _client(rig["accountant"]).post(
        f"/api/approvals/{approval_id}/decide", {"action": "approve"}, format="json"
    )
    # Out of the accountant's role *and* out of their store scope — either way
    # the gate is closed; it is never a 200.
    assert resp.status_code in (403, 404)
    assert Approval.objects.get(pk=approval_id).status == ApprovalStatus.PENDING
