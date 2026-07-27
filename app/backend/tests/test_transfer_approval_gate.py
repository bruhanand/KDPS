"""Every transfer needs the Operations Head before stock leaves (#137).

The transfer core shipped before the actor model (#104) was ruled, so a
warehouse or store person could empty a shelf on their own say-so. The ruling:
*every* transfer, within-state and cross-state, waits for the Operations Head;
the Owner overrides; the maker never decides their own.

Seams:
- **API seam (primary)**: the whole life through the DRF API — a draft is born
  in somebody else's inbox, an unapproved dispatch is refused *by the server*
  and not merely by a hidden button, an approved one posts, and the pieces are
  provably still on the shelf after a refusal.
- **Policy-data seam**: who approves and above what value is a stored
  ``ApprovalPolicy`` row, retunable in Setup with no release (Rule 12) — while
  "the maker is never the checker" is in code and no Setup edit reaches it.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalPolicy, ApprovalStatus
from approvals.services import display_name
from core.documents import DocStatus, VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import StoreTransfer, StoreTransferLine
from stockledger.models import InTransitStock, StockLedgerEntry, StockOnHand

FY = "26-27"


@pytest.fixture()
def gate(db):
    """A warehouse, a same-state store, a cross-state store, and four people.

    ``sender`` is the warehouse person who makes and dispatches transfers,
    ``ops`` the Operations Head the ruling puts in front of every one of them,
    ``owner`` the override, and ``bystander`` an Accounts reader who is senior
    on money but only a viewer on transfers.
    """
    entity = LegalEntity.objects.create(code="tg-ent", name="Gate Entity", pan="AAACT9876C")
    gstin_jh = Gstin.objects.create(
        gstin="20AAACT9876C1ZS", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    gstin_bh = Gstin.objects.create(
        gstin="10AAACT9876C1ZU", state_code="10", state_name="Bihar", legal_entity=entity
    )
    warehouse = Store.objects.create(
        code="TG-WH", name="Gate Warehouse", gstin=gstin_jh, store_type="warehouse"
    )
    store = Store.objects.create(code="TG-A", name="Gate Store A", gstin=gstin_jh)
    store_bh = Store.objects.create(code="TG-BH", name="Gate Store Bihar", gstin=gstin_bh)

    Brand.objects.create(
        code="tg-br",
        name="GateBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    def _user(username, role_code, scope=ScopeType.ALL, stores=()):
        u = User.objects.create_user(
            username=username,
            password=TEST_PASSWORD,
            role=make_role(role_code),
            entity=entity,
            scope_type=scope,
        )
        for s in stores:
            u.stores.add(s)
        return u

    sender = _user("tg_sender", "warehouse")
    ops = _user("tg_ops", "ho_ops")
    owner = _user("tg_owner", "owner")
    bystander = _user("tg_bystander", "accounts")

    for barcode, design, qty, unit_cost in [("TG001", "Shirt", 20, 45000)]:
        sku = Sku.objects.create(
            barcode=barcode,
            design=design,
            color="Blue",
            size="M",
            brand="GateBrand",
            item="shirt",
            hsn="6205",
            mrp_paise=99900,
        )
        Cohort.objects.create(
            sku=sku, barcode=barcode, season="SS26", unit_cost_paise=unit_cost, mrp_paise=99900
        )
        dims = dict(
            sku_code=barcode,
            design=design,
            color="Blue",
            size="M",
            brand="GateBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
        )
        StockOnHand.objects.create(
            store=warehouse,
            gstin=gstin_jh,
            net_qty=qty,
            net_value_paise=qty * unit_cost,
            **dims,
        )
        StockLedgerEntry.objects.create(
            store=warehouse,
            gstin=gstin_jh,
            qty=qty,
            amount=qty * unit_cost,
            kind="pt_inward",
            doc_number="TG-SEED",
            line_no=1,
            **dims,
        )

    for code in ["TG-WH", "TG-A", "TG-BH"]:
        VoucherSeries.objects.create(
            fy=FY, store_code=code, doc_type="STO", prefix=f"{code}/STO/{FY}/", next_seq=1
        )

    return {
        "warehouse": warehouse,
        "store": store,
        "store_bh": store_bh,
        "sender": sender,
        "ops": ops,
        "owner": owner,
        "bystander": bystander,
    }


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _draft(g, destination=None, plan=(("TG001", 4),), **extra) -> dict:
    """Create a draft through the API, as the warehouse person."""
    resp = _client(g["sender"]).post(
        "/api/outbound/transfers",
        {
            "source_store": g["warehouse"].id,
            "destination_store": (destination or g["store"]).id,
            "transfer_type": "store_split",
            "lines": [{"sku_code": b, "qty_planned": q} for b, q in plan],
            **extra,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data


def _dispatch(g, transfer_id, user=None, scans=(("TG001", 4),)):
    return _client(user or g["sender"]).post(
        f"/api/outbound/transfers/{transfer_id}/dispatch",
        {"scans": [{"barcode": b, "qty": q} for b, q in scans]},
        format="json",
    )


def _approval(transfer_id) -> Approval:
    """The live request against a transfer. ``approver_roles`` is deliberately
    not on the inbox read shape — who *may* decide is the engine's business, not
    the client's — so the roles are asserted here, on the row itself."""
    return Approval.objects.filter(kind="transfer", object_id=transfer_id).latest("created_at")


def _decide(g, transfer_id, actor, action="approve", reason=""):
    approval = Approval.objects.get(kind="transfer", object_id=transfer_id, status="pending")
    return _client(actor).post(
        f"/api/approvals/{approval.pk}/decide",
        {"action": action, "reason": reason},
        format="json",
    )


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_draft_transfer_is_born_waiting_for_the_operations_head(gate):
    """Asking is not a step the maker can forget — the draft is created pending."""
    g = gate
    data = _draft(g)

    assert data["approval"]["status"] == ApprovalStatus.PENDING
    assert data["approval"]["kind"] == "transfer"
    assert _approval(data["id"]).approver_roles == ["ho_ops", "owner"]
    # The inbox row says where the pieces are going, and from where.
    assert data["approval"]["title"].startswith("To TG-A · TG-WH")


@pytest.mark.django_db(transaction=True)
def test_an_unapproved_transfer_cannot_be_dispatched_through_the_api(gate):
    """The refusal is on the server, not on the button: a maker who calls the
    endpoint directly still moves nothing."""
    g = gate
    data = _draft(g)

    resp = _dispatch(g, data["id"])
    assert resp.status_code == 400
    assert "approval" in str(resp.data).lower()

    # Nothing moved, nothing was numbered, nothing is on the road.
    transfer = StoreTransfer.objects.get(pk=data["id"])
    assert transfer.docstatus == DocStatus.DRAFT
    assert not transfer.doc_number
    assert StockOnHand.objects.get(store=g["warehouse"], sku_code="TG001").net_qty == 20
    assert not InTransitStock.objects.exists()
    assert not StockLedgerEntry.objects.filter(kind="transfer_out").exists()


@pytest.mark.django_db(transaction=True)
def test_an_approved_transfer_dispatches_and_records_who_cleared_it(gate):
    """Approved by the Operations Head, the stock moves — and the document keeps
    saying who let it."""
    g = gate
    data = _draft(g)

    assert _decide(g, data["id"], g["ops"]).status_code == 200

    resp = _dispatch(g, data["id"])
    assert resp.status_code == 200, resp.data
    assert resp.data["docstatus"] == DocStatus.SUBMITTED
    assert resp.data["approval"]["status"] == ApprovalStatus.APPROVED
    assert resp.data["approved_by"] == g["ops"].pk
    assert resp.data["created_by_name"] and resp.data["approved_by_name"]

    assert StockOnHand.objects.get(store=g["warehouse"], sku_code="TG001").net_qty == 16
    assert InTransitStock.objects.get(transfer_doc_number=resp.data["doc_number"]).qty == 4


@pytest.mark.django_db(transaction=True)
def test_a_rejected_transfer_stays_on_the_shelf_and_says_why(gate):
    """Reject carries a reason, and the refusal survives to the dispatch call."""
    g = gate
    data = _draft(g)

    assert _decide(g, data["id"], g["ops"], "reject", "Send it next week.").status_code == 200

    resp = _dispatch(g, data["id"])
    assert resp.status_code == 400
    assert "Send it next week." in str(resp.data)
    assert StockOnHand.objects.get(store=g["warehouse"], sku_code="TG001").net_qty == 20


@pytest.mark.django_db(transaction=True)
def test_a_rejected_transfer_can_be_asked_again_and_then_dispatches(gate):
    """A rejection is not a dead end: the maker asks again and the trail keeps
    both answers."""
    g = gate
    data = _draft(g)
    _decide(g, data["id"], g["ops"], "reject", "Wrong destination store.")

    resp = _client(g["sender"]).post(f"/api/outbound/transfers/{data['id']}/request-approval")
    assert resp.status_code == 200, resp.data
    assert resp.data["approval"]["status"] == ApprovalStatus.PENDING
    assert resp.data["approval_history"][0]["status"] == ApprovalStatus.REJECTED

    assert _decide(g, data["id"], g["ops"]).status_code == 200
    assert _dispatch(g, data["id"]).status_code == 200


# ---------------------------------------------------------------------------
# Who decides
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_request_lands_in_the_operations_heads_inbox_and_nobody_elses(gate):
    """Seeded from the ratified table: the transfer family's default approver is
    the Operations Head, with the Owner beside them."""
    g = gate
    data = _draft(g)

    for who, expected in [(g["ops"], 1), (g["owner"], 1), (g["bystander"], 0)]:
        rows = _client(who).get("/api/approvals/inbox").data
        assert len([r for r in rows if r["object_id"] == data["id"]]) == expected, who.username

    # And never in the maker's own — a self-approval cannot succeed, so it is
    # never offered.
    assert _client(g["sender"]).get("/api/approvals/inbox").data == []


@pytest.mark.django_db(transaction=True)
def test_the_owner_can_override_any_transfer_approval(gate):
    """The Owner is never blocked in their own business."""
    g = gate
    data = _draft(g)

    assert _decide(g, data["id"], g["owner"]).status_code == 200
    resp = _dispatch(g, data["id"])
    assert resp.status_code == 200, resp.data
    assert resp.data["approved_by"] == g["owner"].pk


@pytest.mark.django_db(transaction=True)
def test_the_maker_cannot_approve_their_own_transfer(gate):
    """The first floor rule, at the API seam."""
    g = gate
    data = _draft(g)

    resp = _decide(g, data["id"], g["sender"])
    assert resp.status_code in (403, 404)
    assert _dispatch(g, data["id"]).status_code == 400


@pytest.mark.django_db(transaction=True)
def test_no_setup_edit_can_let_the_maker_approve_their_own_transfer(gate):
    """Who approves is data; *not yourself* is not. Handing the maker's own role
    the approving seat in Setup still does not let them clear their own
    document."""
    g = gate
    policy = ApprovalPolicy.objects.get(kind="transfer")
    policy.band_roles = ["warehouse", "ho_ops", "owner"]
    policy.escalated_roles = ["warehouse", "ho_ops", "owner"]
    policy.save()

    data = _draft(g)
    assert _decide(g, data["id"], g["sender"]).status_code in (403, 404)
    assert _dispatch(g, data["id"]).status_code == 400

    # A *different* warehouse person now may, because that part is data.
    other = User.objects.create_user(
        username="tg_other_wh",
        password=TEST_PASSWORD,
        role=make_role("warehouse"),
        entity=g["warehouse"].gstin.legal_entity,
        scope_type=ScopeType.ALL,
    )
    assert _decide(g, data["id"], other).status_code == 200
    assert _dispatch(g, data["id"]).status_code == 200


@pytest.mark.django_db(transaction=True)
def test_who_approves_and_above_what_value_is_retuned_in_setup_not_in_code(gate):
    """Rule 12. Retuning the stored policy moves the request to a different desk
    and re-bands it, with no release — the width of the gate is configuration."""
    g = gate
    policy = ApprovalPolicy.objects.get(kind="transfer")
    # Small moves go to a store manager, big ones keep climbing to the Owner.
    policy.band_paise = 100_000  # ₹1,000
    policy.band_roles = ["store_manager"]
    policy.escalated_roles = ["owner"]
    policy.save()

    small = _draft(g, plan=(("TG001", 2),))  # 2 × ₹450 = ₹900, in band
    big = _draft(g, plan=(("TG001", 4),))  # 4 × ₹450 = ₹1,800, escalated

    assert _approval(small["id"]).approver_roles == ["store_manager"]
    assert _approval(big["id"]).approver_roles == ["owner"]
    assert _decide(g, big["id"], g["ops"]).status_code == 403  # no longer their desk
    assert _decide(g, big["id"], g["owner"]).status_code == 200


@pytest.mark.django_db(transaction=True)
def test_a_transfer_with_no_configured_policy_is_a_closed_gate(gate):
    """Missing configuration refuses — it never reads as "nobody was asked".

    Setup can retune the transfer policy row to anything; what it must never be
    able to produce is a transfer that quietly needs no approval at all. With no
    row the draft is refused outright and rolls back, so there is nothing to
    dispatch later.
    """
    from approvals.services import ApprovalRequired

    g = gate
    ApprovalPolicy.objects.filter(kind="transfer").delete()

    with pytest.raises(ApprovalRequired):
        _draft(g, plan=(("TG001", 1),))

    assert not StoreTransfer.objects.exists()


# ---------------------------------------------------------------------------
# Cross-state
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_cross_state_transfer_meets_the_same_gate(gate):
    """Bihar ↔ Jharkhand is two distinct persons under GST, so it is the last
    move that should be exempt — same inbox, same refusal, same approver."""
    g = gate
    data = _draft(g, destination=g["store_bh"], eway_bill_number="EWB-2026-000777")

    assert data["is_cross_state"] is True
    assert _approval(data["id"]).approver_roles == ["ho_ops", "owner"]
    assert data["approval"]["title"].startswith("To TG-BH · cross-state")
    assert _dispatch(g, data["id"]).status_code == 400

    assert _decide(g, data["id"], g["ops"]).status_code == 200
    resp = _dispatch(g, data["id"])
    assert resp.status_code == 200, resp.data
    assert resp.data["eway_bill_number"] == "EWB-2026-000777"


@pytest.mark.django_db(transaction=True)
def test_a_cross_state_transfer_still_needs_its_eway_bill(gate):
    """The carton cannot legally travel without one, and the API says so too —
    not only the screen."""
    g = gate
    resp = _client(g["sender"]).post(
        "/api/outbound/transfers",
        {
            "source_store": g["warehouse"].id,
            "destination_store": g["store_bh"].id,
            "transfer_type": "store_split",
            "lines": [{"sku_code": "TG001", "qty_planned": 1}],
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "eway_bill_number" in resp.data


# ---------------------------------------------------------------------------
# The scan-to-build case — no plan, so nothing to price
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_plan_less_transfer_is_worth_unknown_and_unknown_escalates(gate):
    """A store→store transfer picks its pieces at the scanner, so at approval
    time the books can put no value on it. Unknown must climb, never clear."""
    g = gate
    policy = ApprovalPolicy.objects.get(kind="transfer")
    policy.band_paise = 100_000
    policy.band_roles = ["store_manager"]
    policy.escalated_roles = ["owner"]
    policy.save()

    data = _draft(g, plan=())
    assert data["approval"]["value_paise"] == 0
    assert _approval(data["id"]).approver_roles == ["owner"]


# ---------------------------------------------------------------------------
# The plan is what the checker sees; the scan is what leaves
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_scanning_fewer_pieces_than_the_plan_still_dispatches(gate):
    """Rule 5: a plan/scan gap is flagged, never blocked."""
    g = gate
    data = _draft(g, plan=(("TG001", 6),))
    _decide(g, data["id"], g["ops"])

    resp = _dispatch(g, data["id"], scans=(("TG001", 2),))
    assert resp.status_code == 200, resp.data
    assert resp.data["dispatch_mismatch"] is True


@pytest.mark.django_db(transaction=True)
def test_the_carton_may_be_bigger_than_the_plan_the_checker_approved(gate):
    """Locked here because it is a *decision*, not an accident, and the next
    reader should not have to guess which.

    A transfer is approved on its plan and posts what was scanned, so the pieces
    that leave can exceed the pieces the Operations Head saw. Under the ratified
    transfer policy that costs nothing: there is no band, so every transfer —
    one shirt or a truckload — goes to the same desk, and a bigger carton could
    never have gone to a different one.

    It would start to matter if a band were configured in Setup, which #137
    explicitly invites: a cheap plan cleared in-band could then be loaded past
    the band on that signature. Closing that needs a ruling this ticket does not
    carry — whether a transfer should be approved on its plan at all, or asked
    for at the scanner — so it is raised on the PR rather than invented here.
    """
    g = gate
    data = _draft(g, plan=(("TG001", 1),))
    _decide(g, data["id"], g["ops"])

    resp = _dispatch(g, data["id"], scans=(("TG001", 9),))
    assert resp.status_code == 200, resp.data
    assert resp.data["lines"][0]["qty_dispatched"] == 9
    assert resp.data["dispatch_mismatch"] is True


@pytest.mark.django_db(transaction=True)
def test_dispatch_records_when_it_left_and_who_sent_it(gate):
    """The stamps survive the post: ``post()`` writes only the FSM columns, so
    these have to be saved in their own right."""
    g = gate
    data = _draft(g)
    _decide(g, data["id"], g["ops"])
    assert _dispatch(g, data["id"]).status_code == 200

    transfer = StoreTransfer.objects.get(pk=data["id"])
    assert transfer.dispatch_date is not None
    assert transfer.dispatched_by_id == g["sender"].pk

    # And the screen can say so: a raw id the page cannot render is the same
    # blank the store has always seen.
    read = _client(g["ops"]).get(f"/api/outbound/transfers/{data['id']}").data
    assert read["dispatch_date"] is not None
    assert read["dispatched_by_name"] == display_name(g["sender"])


# ---------------------------------------------------------------------------
# Drafts that predate the gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_draft_made_before_the_gate_is_backfilled_into_the_inbox(gate):
    """Without the backfill an existing alpha draft is bricked in both
    directions — it cannot dispatch (no approval) and cannot be sent for one
    (``ask_again`` is the rejected-only route). It must land in the inbox and
    then behave like any other transfer.

    The migration function is called the way ``conftest`` calls the policy seed:
    the rows it writes are the point, not the schema editor.
    """
    from importlib import import_module

    from django.apps import apps as django_apps

    g = gate
    stranded = StoreTransfer.objects.create(
        source_store=g["warehouse"],
        destination_store=g["store"],
        transfer_type="store_split",
        created_by=g["sender"],
    )
    StoreTransferLine.objects.create(
        transfer=stranded, sku_code="TG001", qty_planned=3, unit_cost_paise=45000
    )
    assert _dispatch(g, stranded.pk, scans=(("TG001", 3),)).status_code == 400

    backfill = import_module("outbound.migrations.0017_backfill_transfer_approvals")
    backfill.raise_pending_approvals(django_apps, None)

    raised = _approval(stranded.pk)
    assert raised.status == ApprovalStatus.PENDING
    assert raised.made_by_id == g["sender"].pk
    assert raised.store_id == g["warehouse"].pk
    assert raised.value_paise == 3 * 45000
    assert raised.approver_roles == ["ho_ops", "owner"]

    # It is now an ordinary transfer: the Operations Head clears it and it goes.
    assert _decide(g, stranded.pk, g["ops"]).status_code == 200
    assert _dispatch(g, stranded.pk, scans=(("TG001", 3),)).status_code == 200

    # And running it twice does not double-raise.
    backfill.raise_pending_approvals(django_apps, None)
    assert Approval.objects.filter(kind="transfer", object_id=stranded.pk).count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_backfill_leaves_posted_transfers_and_live_requests_alone(gate):
    """It may not invent a signature for stock that already moved, and it may
    not raise a second request beside one a person is already looking at."""
    from importlib import import_module

    from django.apps import apps as django_apps

    g = gate
    posted = _draft(g)
    _decide(g, posted["id"], g["ops"])
    assert _dispatch(g, posted["id"]).status_code == 200
    waiting = _draft(g, plan=(("TG001", 1),))

    before = Approval.objects.filter(kind="transfer").count()
    import_module("outbound.migrations.0017_backfill_transfer_approvals").raise_pending_approvals(
        django_apps, None
    )
    assert Approval.objects.filter(kind="transfer").count() == before
    assert Approval.objects.filter(kind="transfer", object_id=waiting["id"]).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_transfer_built_outside_the_api_cannot_dispatch_either(gate):
    """The wall is in the posting layer, so a shell or a management command hits
    it exactly as the API does."""
    from outbound.costing import OutboundPostingError
    from outbound.posting import post_transfer_dispatch

    g = gate
    transfer = StoreTransfer.objects.create(
        source_store=g["warehouse"],
        destination_store=g["store"],
        transfer_type="store_split",
        created_by=g["sender"],
    )
    StoreTransferLine.objects.create(transfer=transfer, sku_code="TG001", qty_planned=2)

    with pytest.raises(OutboundPostingError, match="approval"):
        post_transfer_dispatch(transfer, {"TG001": 2}, user=g["sender"])

    assert StockOnHand.objects.get(store=g["warehouse"], sku_code="TG001").net_qty == 20
