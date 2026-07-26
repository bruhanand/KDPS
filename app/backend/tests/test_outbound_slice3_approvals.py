"""Outbound slice 3 — approvals inbox + maker-checker (#70, PRD #67).

Seams (agreed in the PRD):
- **API seam (primary)**: the whole approval life through the DRF API — create a
  draft → it appears in a *second* person's inbox → approve/reject → the
  document posts or stays blocked. Self-approval refused on every wired type.
- **Database seam**: maker ≠ checker is a check constraint, not just a service
  rule; bypassing the service still fails.

Rulings (system.md · Maker-checker & the approvals inbox):
"No document is approved by the person who made it." · "One approvals inbox for
the whole system … approve/reject, a reason required on reject." · "Every
document shows made by X, approved by Y, on date Z — forever."
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from django.db.utils import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalPolicy, ApprovalStatus
from core.documents import DocStatus, VoucherSeries
from masters.models import Brand, Gstin, LegalEntity, Store
from outbound.models import StockAdjustment, VFlip, WriteOff
from stockledger.models import StockLedgerEntry, StockOnHand

FY = "26-27"


@pytest.fixture()
def mc(db):
    """One store with stock, plus four people:

    maker    — ho_ops, makes and clears counting corrections, but never its own
    checker  — owner, the second person on every family here
    packer   — warehouse, the one who makes V-flips (`stock: manage`, #94)
    outsider — accounts, a reader on stock and counting, scoped to another store
    """
    entity = LegalEntity.objects.create(code="mc-ent", name="MC Entity", pan="AAACM1234M")
    gstin = Gstin.objects.create(
        gstin="20AAACM1234M1ZS", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    store = Store.objects.create(code="MC-A", name="MC Store A", gstin=gstin)
    other = Store.objects.create(code="MC-B", name="MC Store B", gstin=gstin)

    brand = Brand.objects.create(
        code="mc-br",
        name="McBrand",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
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

    maker = _user("mc_maker", "ho_ops")
    checker = _user("mc_checker", "owner")
    packer = _user("mc_packer", "warehouse", ScopeType.STORE, [store])
    outsider = _user("mc_outsider", "accounts", ScopeType.STORE, [other])

    StockOnHand.objects.create(
        store=store,
        gstin=gstin,
        sku_code="MC001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="McBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        net_qty=10,
        net_value_paise=10 * 45000,
    )
    StockLedgerEntry.objects.create(
        store=store,
        gstin=gstin,
        sku_code="MC001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="McBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty=10,
        amount=10 * 45000,
        kind="pt_inward",
        doc_number="MC-SEED",
        line_no=1,
    )

    for code in ["MC-A", "MC-B"]:
        for doc_type in ["WRO", "VFL", "ADJ"]:
            VoucherSeries.objects.create(
                fy=FY,
                store_code=code,
                doc_type=doc_type,
                prefix=f"{code}/{doc_type}/{FY}/",
                next_seq=1,
            )

    return {
        "store": store,
        "other": other,
        "brand": brand,
        "maker": maker,
        "checker": checker,
        "packer": packer,
        "outsider": outsider,
    }


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _writeoff_payload(store, qty=2):
    return {
        "store": store.id,
        "reason": "Dead stock clearance",
        "lines": [{"sku_code": "MC001", "qty": qty, "unit_cost_paise": 45000}],
    }


def _create_writeoff(mc, qty=2):
    resp = _client(mc["maker"]).post(
        "/api/outbound/writeoffs", _writeoff_payload(mc["store"], qty), format="json"
    )
    assert resp.status_code == 201, resp.data
    return resp.data


def _create_adjustment(mc, *, adj_qty, unit_cost_paise=45000, user=None):
    """A one-line adjustment. ``adj_qty × unit_cost`` is the value at stake —
    the number the tolerance and the value band are read against."""
    resp = _client(user or mc["maker"]).post(
        "/api/outbound/adjustments",
        {
            "store": mc["store"].id,
            "reason": "miscount",
            "lines": [
                {
                    "sku_code": "MC001",
                    "book_qty": 10,
                    "counted_qty": 10 + adj_qty,
                    "adj_qty": adj_qty,
                    "unit_cost_paise": unit_cost_paise,
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data


# ---------------------------------------------------------------------------
# The document is born pending — and the creator is never its approver
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_creating_a_writeoff_asks_someone_else_and_stamps_nobody(mc):
    """A fresh write-off has no approver at all — it has a *request* for one.
    The old behaviour (the creator silently stamped as approver) is gone."""
    data = _create_writeoff(mc)

    wo = WriteOff.objects.get(pk=data["id"])
    assert wo.created_by_id == mc["maker"].id
    assert wo.approved_by_id is None  # nobody has approved it yet

    approval = Approval.objects.get(kind="writeoff", object_id=wo.id)
    assert approval.status == ApprovalStatus.PENDING
    assert approval.requested_by_id == mc["maker"].id
    assert approval.decided_by_id is None
    assert approval.store_id == mc["store"].id
    assert approval.value_paise == 2 * 45000
    assert approval.title == "MC-A · 1 line · 2 pcs"


@pytest.mark.django_db(transaction=True)
def test_client_supplied_approver_is_ignored(mc):
    """Even if a client posts ``approved_by``, the server refuses to honour it —
    the approver comes from the inbox, never from the payload."""
    payload = _writeoff_payload(mc["store"]) | {"approved_by": mc["maker"].id}
    resp = _client(mc["maker"]).post("/api/outbound/writeoffs", payload, format="json")
    assert resp.status_code == 201, resp.data
    assert WriteOff.objects.get(pk=resp.data["id"]).approved_by_id is None


@pytest.mark.django_db(transaction=True)
def test_writeoff_cannot_post_before_a_second_person_approves(mc):
    """Submitting an unapproved write-off is refused and nothing moves."""
    data = _create_writeoff(mc)

    resp = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/submit")
    assert resp.status_code == 400, resp.data
    assert "Waiting for approval" in str(resp.data)

    assert WriteOff.objects.get(pk=data["id"]).docstatus == DocStatus.DRAFT
    assert StockOnHand.objects.get(store=mc["store"], sku_code="MC001").net_qty == 10


# ---------------------------------------------------------------------------
# The inbox
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_one_inbox_lists_every_document_type_waiting_for_me(mc):
    """One endpoint, three different document families, one list."""
    maker = _client(mc["maker"])
    maker.post("/api/outbound/writeoffs", _writeoff_payload(mc["store"]), format="json")
    # A V-flip is the warehouse's to make — `stock: manage` (#94).
    _client(mc["packer"]).post(
        "/api/outbound/vflips",
        {
            "store": mc["store"].id,
            "original_brand": mc["brand"].id,
            "season": "SS26",
            "lines": [{"sku_code": "MC001", "qty": 1, "unit_cost_paise": 45000}],
        },
        format="json",
    )
    _create_adjustment(mc, adj_qty=-6)  # above tolerance, so it needs a checker

    inbox = _client(mc["checker"]).get("/api/approvals/inbox")
    assert inbox.status_code == 200
    assert sorted(row["kind"] for row in inbox.data) == ["adjustment", "vflip", "writeoff"]
    row = next(r for r in inbox.data if r["kind"] == "writeoff")
    assert row["kind_label"] == "Write-off"
    assert row["store_code"] == "MC-A"
    assert row["requested_by_name"] == "mc_maker"
    assert row["status"] == "pending"
    assert row["requested_at"] is not None


@pytest.mark.django_db(transaction=True)
def test_my_own_requests_are_never_in_my_inbox(mc):
    """A self-approval can never succeed, so it is never offered."""
    _create_writeoff(mc)
    assert _client(mc["maker"]).get("/api/approvals/inbox").data == []


@pytest.mark.django_db(transaction=True)
def test_inbox_is_role_gated(mc):
    """A warehouse packer may create outbound work but may not clear approvals."""
    _create_writeoff(mc)
    assert _client(mc["packer"]).get("/api/approvals/inbox").data == []


@pytest.mark.django_db(transaction=True)
def test_inbox_is_store_scoped_fail_closed(mc):
    """A store-scoped approver sees only their own stores' approvals (ADR-0003)."""
    _create_writeoff(mc)
    assert _client(mc["outsider"]).get("/api/approvals/inbox").data == []


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_approve_from_the_inbox_then_the_document_posts(mc):
    """The full loop: maker creates, checker approves from the inbox, the
    document posts, and the stock finally moves."""
    data = _create_writeoff(mc)
    approval_id = _client(mc["checker"]).get("/api/approvals/inbox").data[0]["id"]

    decided = _client(mc["checker"]).post(
        f"/api/approvals/{approval_id}/decide", {"action": "approve"}, format="json"
    )
    assert decided.status_code == 200, decided.data
    assert decided.data["status"] == "approved"
    assert decided.data["decided_by_name"] == "mc_checker"
    assert decided.data["decided_at"] is not None

    # The document already reads truthfully, before it posts.
    detail = _client(mc["maker"]).get(f"/api/outbound/writeoffs/{data['id']}").data
    assert detail["approved_by_name"] == "mc_checker"

    posted = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/submit")
    assert posted.status_code == 200, posted.data
    assert posted.data["docstatus"] == DocStatus.SUBMITTED
    assert StockOnHand.objects.get(store=mc["store"], sku_code="MC001").net_qty == 8

    # Posting stamps the document's own approver column — the checker, never the maker.
    assert WriteOff.objects.get(pk=data["id"]).approved_by_id == mc["checker"].id

    # ...and it is gone from the inbox.
    assert _client(mc["checker"]).get("/api/approvals/inbox").data == []


@pytest.mark.django_db(transaction=True)
def test_a_vflip_needs_a_second_person_too(mc):
    """Same rule, different document family — the V-flip's ``authorized_by``
    is the checker, and it will not post before that.

    The warehouse makes it: relabelling ownership is `stock: manage` (#94), a
    rung HO ops does not hold.
    """
    created = _client(mc["packer"]).post(
        "/api/outbound/vflips",
        {
            "store": mc["store"].id,
            "original_brand": mc["brand"].id,
            "season": "SS26",
            "lines": [{"sku_code": "MC001", "qty": 1, "unit_cost_paise": 45000}],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    vflip_id = created.data["id"]

    blocked = _client(mc["packer"]).post(f"/api/outbound/vflips/{vflip_id}/submit")
    assert blocked.status_code == 400
    assert VFlip.objects.get(pk=vflip_id).authorized_by_id is None

    approval = Approval.objects.get(kind="vflip", object_id=vflip_id)
    _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )

    posted = _client(mc["packer"]).post(f"/api/outbound/vflips/{vflip_id}/submit")
    assert posted.status_code == 200, posted.data
    assert VFlip.objects.get(pk=vflip_id).authorized_by_id == mc["checker"].id


@pytest.mark.django_db(transaction=True)
def test_an_adjustment_above_tolerance_needs_a_second_person_too(mc):
    """Same rule for stock adjustments once the variance is worth something —
    the book does not move on one signature."""
    adj_id = _create_adjustment(mc, adj_qty=-6)["id"]

    blocked = _client(mc["maker"]).post(f"/api/outbound/adjustments/{adj_id}/submit")
    assert blocked.status_code == 400
    assert StockOnHand.objects.get(store=mc["store"], sku_code="MC001").net_qty == 10

    approval = Approval.objects.get(kind="adjustment", object_id=adj_id)
    assert approval.value_paise == 6 * 45000  # magnitude at stake, not the sign
    _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )

    posted = _client(mc["maker"]).post(f"/api/outbound/adjustments/{adj_id}/submit")
    assert posted.status_code == 200, posted.data
    assert StockAdjustment.objects.get(pk=adj_id).approved_by_id == mc["checker"].id
    assert StockOnHand.objects.get(store=mc["store"], sku_code="MC001").net_qty == 4


# ---------------------------------------------------------------------------
# Self-approval
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_maker_cannot_approve_their_own_document(mc):
    """The explicit warehouse-team ask: the Maker is not the Checker."""
    _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")

    resp = _client(mc["maker"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 403, resp.data
    assert "cannot approve a document you created" in str(resp.data)

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING
    assert approval.decided_by_id is None


@pytest.mark.django_db(transaction=True)
def test_self_approval_is_refused_by_the_database_too(mc):
    """Defence in depth: even a caller that bypasses the service cannot write a
    row where the maker is the checker."""
    from django.utils import timezone

    _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    approval.status = ApprovalStatus.APPROVED
    approval.decided_by = approval.requested_by
    approval.decided_at = timezone.now()

    with pytest.raises(IntegrityError):
        approval.save()


@pytest.mark.django_db(transaction=True)
def test_a_role_that_cannot_approve_is_refused(mc):
    """Store-level roles cannot clear an HO-level approval."""
    _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    resp = _client(mc["packer"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_an_out_of_scope_approval_looks_like_it_does_not_exist(mc):
    """A store-scoped approver cannot reach another store's approval."""
    _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    resp = _client(mc["outsider"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reject_requires_a_reason(mc):
    """Reject with no reason is refused; the request stays pending."""
    _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")

    resp = _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "reject", "reason": "   "}, format="json"
    )
    assert resp.status_code == 400
    assert "reason is required" in str(resp.data)
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING


@pytest.mark.django_db(transaction=True)
def test_a_rejected_document_never_posts_and_says_why(mc):
    data = _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")

    rejected = _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide",
        {"action": "reject", "reason": "Stock is saleable at Deoghar"},
        format="json",
    )
    assert rejected.status_code == 200
    assert rejected.data["status"] == "rejected"
    assert rejected.data["reason"] == "Stock is saleable at Deoghar"

    blocked = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/submit")
    assert blocked.status_code == 400
    assert "Stock is saleable at Deoghar" in str(blocked.data)
    assert StockOnHand.objects.get(store=mc["store"], sku_code="MC001").net_qty == 10


@pytest.mark.django_db(transaction=True)
def test_rejecting_never_marks_the_rejecter_as_the_approver(mc):
    """Refusing a document is not approving it — the person who said no must
    never appear on it as its approver."""
    data = _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide",
        {"action": "reject", "reason": "Still saleable"},
        format="json",
    )

    assert WriteOff.objects.get(pk=data["id"]).approved_by_id is None
    detail = _client(mc["maker"]).get(f"/api/outbound/writeoffs/{data['id']}").data
    assert detail["approved_by_name"] == ""
    assert detail["approval"]["status"] == "rejected"


@pytest.mark.django_db(transaction=True)
def test_a_decided_approval_cannot_be_decided_again(mc):
    _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    checker = _client(mc["checker"])
    first = checker.post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    assert first.status_code == 200
    second = checker.post(
        f"/api/approvals/{approval.id}/decide",
        {"action": "reject", "reason": "changed my mind"},
        format="json",
    )
    assert second.status_code == 400
    assert "already approved" in str(second.data)


# ---------------------------------------------------------------------------
# Made by / approved by / when — forever
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_document_shows_made_by_approved_by_and_when(mc):
    data = _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )

    detail = _client(mc["packer"]).get(f"/api/outbound/writeoffs/{data['id']}").data
    assert detail["created_by_name"] == "mc_maker"
    assert detail["approved_by_name"] == "mc_checker"
    assert detail["approval"]["status"] == "approved"
    assert detail["approval"]["requested_by_name"] == "mc_maker"
    assert detail["approval"]["decided_at"] is not None


@pytest.mark.django_db(transaction=True)
def test_the_maker_can_watch_their_own_request_in_the_history(mc):
    """The inbox hides your own requests; the history does not — otherwise a
    maker could never see that they were rejected."""
    _create_writeoff(mc)
    history = _client(mc["maker"]).get("/api/approvals?status=pending")
    assert history.status_code == 200
    assert [row["kind"] for row in history.data] == ["writeoff"]


# ---------------------------------------------------------------------------
# Tolerance & value band — "within a configurable tolerance → auto-adjust,
# logged, done … approval is value-banded" (system.md · Stock counting)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_small_adjustment_posts_without_a_second_person(mc):
    """A ₹900 miscount does not queue behind the owner's morning inbox — it
    auto-adjusts and is logged, which is what the count design asks for."""
    adj_id = _create_adjustment(mc, adj_qty=-2)["id"]

    approval = Approval.objects.get(kind="adjustment", object_id=adj_id)
    assert approval.status == ApprovalStatus.NOT_REQUIRED
    assert approval.decided_by_id is None
    assert "tolerance" in approval.reason  # the rule that let it through, on the row

    posted = _client(mc["maker"]).post(f"/api/outbound/adjustments/{adj_id}/submit")
    assert posted.status_code == 200, posted.data
    assert StockOnHand.objects.get(store=mc["store"], sku_code="MC001").net_qty == 8


@pytest.mark.django_db(transaction=True)
def test_an_auto_adjusted_document_is_in_nobody_s_inbox(mc):
    """Not needing a checker is not the same as hiding: it is simply not a
    question anyone has to answer."""
    _create_adjustment(mc, adj_qty=-2)
    inbox = _client(mc["checker"]).get("/api/approvals/inbox")
    assert inbox.data == []


@pytest.mark.django_db(transaction=True)
def test_a_small_writeoff_still_needs_a_second_person(mc):
    """The tolerance belongs to counting, not to stock leaving the books: a
    write-off of the same value still waits for someone else."""
    data = _create_writeoff(mc, qty=2)  # ₹900 — under the adjustment tolerance
    approval = Approval.objects.get(kind="writeoff", object_id=data["id"])
    assert approval.status == ApprovalStatus.PENDING

    blocked = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/submit")
    assert blocked.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_a_mid_value_adjustment_may_be_cleared_by_the_in_charge(mc):
    """Up to the band the store in-charge approves; the row says so, so the
    inbox routes it without anyone branching on value at read time."""
    adj_id = _create_adjustment(mc, adj_qty=-6)["id"]  # ₹2,700
    approval = Approval.objects.get(kind="adjustment", object_id=adj_id)
    assert "store_manager" in approval.approver_roles
    assert "owner" in approval.approver_roles  # HO can always clear a small one


@pytest.mark.django_db(transaction=True)
def test_a_large_adjustment_goes_straight_to_ho(mc):
    adj_id = _create_adjustment(mc, adj_qty=60)["id"]  # ₹27,000 — above the band
    approval = Approval.objects.get(kind="adjustment", object_id=adj_id)
    assert "store_manager" not in approval.approver_roles
    assert "owner" in approval.approver_roles


@pytest.mark.django_db(transaction=True)
def test_the_tolerance_is_data_the_business_can_retune(mc):
    """Rule 12: the threshold is a row, not a constant. Drop it to zero and the
    same small adjustment needs a checker again — with no redeploy."""
    ApprovalPolicy.objects.create(
        kind="adjustment", tolerance_paise=0, escalated_roles=["owner", "ho_ops"]
    )

    adj_id = _create_adjustment(mc, adj_qty=-2)["id"]
    approval = Approval.objects.get(kind="adjustment", object_id=adj_id)
    assert approval.status == ApprovalStatus.PENDING


# ---------------------------------------------------------------------------
# The way back from a rejection — a refused draft is not a dead end
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_rejected_draft_can_be_fixed_and_asked_again(mc):
    data = _create_writeoff(mc)
    first = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{first.id}/decide",
        {"action": "reject", "reason": "Wrong store"},
        format="json",
    )

    again = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")
    assert again.status_code == 200, again.data
    assert again.data["approval"]["status"] == "pending"
    # The refusal is still on the record — that is the point of maker-checker.
    assert [h["status"] for h in again.data["approval_history"]] == ["rejected"]
    assert again.data["approval_history"][0]["reason"] == "Wrong store"

    second = Approval.objects.get(kind="writeoff", status=ApprovalStatus.PENDING)
    _client(mc["checker"]).post(
        f"/api/approvals/{second.id}/decide", {"action": "approve"}, format="json"
    )
    posted = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/submit")
    assert posted.status_code == 200, posted.data
    assert WriteOff.objects.get(pk=data["id"]).approved_by_id == mc["checker"].id


@pytest.mark.django_db(transaction=True)
def test_whoever_asks_again_is_barred_from_deciding_it(mc):
    """Otherwise a checker could reject a document, re-raise it themselves and
    then clear their own request — maker-checker with extra steps."""
    data = _create_writeoff(mc)
    first = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{first.id}/decide",
        {"action": "reject", "reason": "Wrong store"},
        format="json",
    )

    again = _client(mc["checker"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")
    assert again.status_code == 200, again.data

    second = Approval.objects.get(kind="writeoff", status=ApprovalStatus.PENDING)
    assert second.requested_by_id == mc["checker"].id

    refused = _client(mc["checker"]).post(
        f"/api/approvals/{second.id}/decide", {"action": "approve"}, format="json"
    )
    assert refused.status_code == 403
    assert "cannot approve a request you raised" in str(refused.data)


@pytest.mark.django_db(transaction=True)
def test_a_document_is_never_in_two_inboxes_at_once(mc):
    """Asking again while a request is still waiting is refused — by the view,
    and by a partial unique index underneath it."""
    data = _create_writeoff(mc)
    again = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")
    assert again.status_code == 400
    assert "already waiting" in str(again.data)
    assert Approval.objects.filter(kind="writeoff", object_id=data["id"]).count() == 1


@pytest.mark.django_db(transaction=True)
def test_an_approved_document_cannot_be_asked_again(mc):
    data = _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    again = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")
    assert again.status_code == 400
    assert "already cleared" in str(again.data)


@pytest.mark.django_db(transaction=True)
def test_a_posted_document_cannot_be_asked_again(mc):
    """A posted document is frozen — re-opening approval on it would imply the
    posting could be undone, which the kernel does not allow."""
    data = _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/submit")

    again = _client(mc["maker"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")
    assert again.status_code == 400
    assert "Only a draft" in str(again.data)


@pytest.mark.django_db(transaction=True)
def test_asking_again_is_store_scoped(mc):
    """Same fail-closed scoping as every other outbound write."""
    data = _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide",
        {"action": "reject", "reason": "Wrong store"},
        format="json",
    )
    refused = _client(mc["outsider"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")
    assert refused.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_a_reader_cannot_ask_again(mc):
    """Re-raising is a write, so it needs the write rung on the section.

    The reader here is Accounts, which the matrix gives `stock_count: view` —
    the refusal names the section, so it is the rung talking and not the store
    scope, which is checked later and would say something else (#94).
    """
    data = _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{approval.id}/decide",
        {"action": "reject", "reason": "Wrong store"},
        format="json",
    )
    refused = _client(mc["outsider"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")
    assert refused.status_code == 403
    assert "stock_count" in str(refused.data["detail"])


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (0, "₹0"),
        (99_900, "₹999"),
        (2_00_000, "₹2,000"),
        (25_00_000, "₹25,000"),
        (10_00_00_000, "₹10,00,000"),
    ],
)
def test_the_tolerance_reads_in_rupees_lakhs_and_crores(paise, expected):
    """The threshold is quoted on an audit row a person will read, so it is
    grouped the Indian way, not the thousands way."""
    from outbound.maker_checker import _inr

    assert _inr(paise) == expected


# ---------------------------------------------------------------------------
# The maker stays barred, however the request is re-raised
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_maker_cannot_approve_after_someone_else_asks_again(mc):
    """The hole re-asking opens if only the *asker* is checked: A writes it, B
    refuses it, B asks again — and A signs off their own document."""
    data = _create_writeoff(mc)
    first = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{first.id}/decide",
        {"action": "reject", "reason": "Wrong store"},
        format="json",
    )
    _client(mc["checker"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")

    second = Approval.objects.get(kind="writeoff", status=ApprovalStatus.PENDING)
    assert second.requested_by_id == mc["checker"].id
    assert second.made_by_id == mc["maker"].id  # unchanged — the author is the author

    refused = _client(mc["maker"]).post(
        f"/api/approvals/{second.id}/decide", {"action": "approve"}, format="json"
    )
    assert refused.status_code == 403
    assert "document you created" in str(refused.data)
    assert WriteOff.objects.get(pk=data["id"]).docstatus == DocStatus.DRAFT


@pytest.mark.django_db(transaction=True)
def test_the_maker_never_sees_a_re_raised_request_in_their_inbox(mc):
    data = _create_writeoff(mc)
    first = Approval.objects.get(kind="writeoff")
    _client(mc["checker"]).post(
        f"/api/approvals/{first.id}/decide",
        {"action": "reject", "reason": "Wrong store"},
        format="json",
    )
    _client(mc["checker"]).post(f"/api/outbound/writeoffs/{data['id']}/request-approval")

    assert _client(mc["maker"]).get("/api/approvals/inbox").data == []


@pytest.mark.django_db(transaction=True)
def test_the_database_bars_the_maker_too(mc):
    """Defence in depth: bypass the service and the constraint still holds."""
    _create_writeoff(mc)
    approval = Approval.objects.get(kind="writeoff")
    approval.decided_by = approval.made_by
    approval.decided_at = timezone.now()
    approval.status = ApprovalStatus.APPROVED
    with pytest.raises(IntegrityError):
        approval.save()


# ---------------------------------------------------------------------------
# The value the tolerance is read against comes from the books
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_maker_cannot_type_their_way_under_the_tolerance(mc):
    """The whole point of the tolerance is that small variances clear
    themselves. If the maker supplied the value, any variance could be made
    small — so the cost is read from stock, never from the payload."""
    adj_id = _create_adjustment(mc, adj_qty=-8, unit_cost_paise=1)["id"]

    approval = Approval.objects.get(kind="adjustment", object_id=adj_id)
    assert approval.value_paise == 8 * 45000  # the book's cost, not the typed ₹0.01
    assert approval.status == ApprovalStatus.PENDING

    blocked = _client(mc["maker"]).post(f"/api/outbound/adjustments/{adj_id}/submit")
    assert blocked.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_a_line_the_books_do_not_know_is_refused_outright(mc):
    """An unknown SKU is worth an unknown amount — and a money posting may not
    carry an unknown (#103).

    This used to be created and escalated to a checker at a value of ₹0, which
    meant the approver saw "nothing at stake" and the posting engine later
    relieved the pieces for free. The document is now refused where the problem
    actually is: at the line, when it is made.
    """
    resp = _client(mc["maker"]).post(
        "/api/outbound/adjustments",
        {
            "store": mc["store"].id,
            "reason": "miscount",
            "lines": [
                {
                    "sku_code": "NOT-IN-THE-BOOKS",
                    "book_qty": 0,
                    "counted_qty": 1,
                    "adj_qty": 1,
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "cannot price NOT-IN-THE-BOOKS" in str(resp.data)
    assert not StockAdjustment.objects.filter(store=mc["store"], reason="miscount").exists()


@pytest.mark.django_db(transaction=True)
def test_a_vflip_has_no_tolerance_either(mc):
    """Changing who owns a piece is never automatic, however small it is."""
    resp = _client(mc["packer"]).post(
        "/api/outbound/vflips",
        {
            "store": mc["store"].id,
            "original_brand": mc["brand"].id,
            "season": "SS26",
            "lines": [{"sku_code": "MC001", "qty": 1, "unit_cost_paise": 45000}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    approval = Approval.objects.get(kind="vflip", object_id=resp.data["id"])
    assert approval.status == ApprovalStatus.PENDING
