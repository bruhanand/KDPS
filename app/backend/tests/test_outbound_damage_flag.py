"""Damage becomes flag-then-confirm (#138, amending slice 2's #69).

Anand's ruling of 26 July: a store person who marks a piece damaged raises a
**flag** — nothing moves, the piece stays in the store's sellable stock and the
person who reported it is recorded. A warehouse or HO person's **confirmation**
is what posts the piece into quarantine. Someone who holds both rungs does it in
one action.

Seams:
- **Ledger seam**: no stock entry exists between the flag and the confirmation,
  and the quarantine bucket only ever fills on a confirmation — so the
  returnable pool, which is built from confirmed quarantine, can never see a
  flag.
- **API seam**: a store role calling the confirm endpoint is refused by the
  server, not merely hidden in the UI.
"""

from __future__ import annotations

import pytest
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalStatus
from core.documents import DocStatus, VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import MarkDamaged
from stockledger.models import QuarantineStock, StockLedgerEntry, StockOnHand

FY = "26-27"


@pytest.fixture()
def damage_scaffold(db):
    """One store holding ten sellable shirts, and the three people this ruling
    needs: the store person who reports damage, a second store person (who also
    may not confirm), and the warehouse person who may."""
    entity = LegalEntity.objects.create(code="dmg-ent", name="Damage Entity", pan="AAACD1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACD1234C1ZS",
        state_code="20",
        state_name="Jharkhand",
        legal_entity=entity,
    )
    store = Store.objects.create(code="D-A", name="Damage Store A", gstin=gstin)

    Brand.objects.create(
        code="dmg-br",
        name="DamageBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    store_role = make_role("store_manager", "Store manager (damage test)")
    reporter = User.objects.create_user(
        username="dmg_store", password="Test@123", role=store_role, scope_type=ScopeType.STORE
    )
    reporter.stores.add(store)
    colleague = User.objects.create_user(
        username="dmg_store2", password="Test@123", role=store_role, scope_type=ScopeType.STORE
    )
    colleague.stores.add(store)

    warehouse_role = make_role("warehouse", "Warehouse (damage test)")
    confirmer = User.objects.create_user(
        username="dmg_wh",
        password="Test@123",
        role=warehouse_role,
        entity=entity,
        scope_type=ScopeType.ALL,
    )

    sku = Sku.objects.create(
        barcode="DM001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="DamageBrand",
        item="shirt",
        hsn="6205",
        mrp_paise=99900,
    )
    Cohort.objects.create(
        sku=sku, barcode="DM001", season="SS26", unit_cost_paise=45000, mrp_paise=99900
    )
    StockOnHand.objects.create(
        store=store,
        gstin=gstin,
        sku_code="DM001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="DamageBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        net_qty=10,
        net_value_paise=10 * 45000,
    )
    StockLedgerEntry.objects.create(
        store=store,
        gstin=gstin,
        sku_code="DM001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="DamageBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty=10,
        amount=10 * 45000,
        kind="pt_inward",
        doc_number="DMG-SEED",
        line_no=1,
    )
    VoucherSeries.objects.create(
        fy=FY, store_code="D-A", doc_type="DMG", prefix=f"D-A/DMG/{FY}/", next_seq=1
    )

    return {
        "gstin": gstin,
        "store": store,
        "reporter": reporter,
        "colleague": colleague,
        "confirmer": confirmer,
    }


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _flag(scaffold, qty: int = 3, user=None):
    """The store reports damage → the flag, as the API returns it."""
    resp = _client(user or scaffold["reporter"]).post(
        "/api/outbound/mark-damaged",
        {"store": scaffold["store"].id, "scans": [{"barcode": "DM001", "qty": qty}]},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data


def _approval(mark_id: int) -> Approval:
    return Approval.objects.get(kind="damage", object_id=mark_id)


# ---------------------------------------------------------------------------
# The flag — a report, not a movement
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_store_flag_writes_nothing_to_the_stock_ledger(damage_scaffold):
    """The ledger seam: between the flag and the confirmation there is no stock
    entry at all — the shirt is still on the shelf, just reported."""
    s = damage_scaffold
    flag = _flag(s, qty=3)

    assert flag["docstatus"] == DocStatus.DRAFT
    assert flag["flag_status"] == "flagged"
    assert flag["doc_number"] is None

    mark = MarkDamaged.objects.get(pk=flag["id"])
    assert mark.created_by_id == s["reporter"].id
    assert mark.confirmed_by_id is None

    # Nothing moved: no legs, no quarantine bucket, sellable stock untouched.
    assert not StockLedgerEntry.objects.filter(kind__in=("damage_out", "quarantine_in")).exists()
    assert not QuarantineStock.objects.exists()
    assert StockOnHand.objects.get(store=s["store"], sku_code="DM001").net_qty == 10

    # …and it is waiting for someone who holds the confirming rung.
    approval = _approval(mark.pk)
    assert approval.status == ApprovalStatus.PENDING
    assert approval.made_by_id == s["reporter"].id
    assert "warehouse" in approval.approver_roles


@pytest.mark.django_db(transaction=True)
def test_an_unconfirmed_flag_never_reaches_the_quarantine_pool(damage_scaffold):
    """The returnable pool is built from *confirmed* quarantine, so a flag alone
    must leave the quarantine read completely empty."""
    s = damage_scaffold
    _flag(s, qty=3)

    quar = _client(s["confirmer"]).get("/api/stockledger/quarantine")
    assert quar.status_code == 200
    assert quar.data["summary"]["units_quarantined"] == 0
    assert quar.data["rows"] == []


@pytest.mark.django_db(transaction=True)
def test_the_flag_is_visible_to_the_store_and_to_the_confirmer(damage_scaffold):
    """Two places, one flag: the store that reported it sees it awaiting
    confirmation, and the warehouse sees it as something to action."""
    s = damage_scaffold
    flag = _flag(s, qty=2)

    mine = _client(s["reporter"]).get("/api/outbound/mark-damaged")
    row = next(r for r in mine.data if r["id"] == flag["id"])
    assert row["flag_status"] == "flagged"
    assert row["created_by_name"] == s["reporter"].username

    inbox = _client(s["confirmer"]).get("/api/approvals/inbox")
    waiting = [a for a in inbox.data if a["object_id"] == flag["id"] and a["kind"] == "damage"]
    assert len(waiting) == 1
    assert waiting[0]["store_code"] == "D-A"


# ---------------------------------------------------------------------------
# The confirmation — what actually posts
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_warehouse_confirmation_is_what_posts_to_quarantine(damage_scaffold):
    """Confirming moves the pieces out of sellable stock into quarantine, and
    both names stay on the document for good."""
    s = damage_scaffold
    flag = _flag(s, qty=3)
    approval = _approval(flag["id"])

    resp = _client(s["confirmer"]).post(
        f"/api/approvals/{approval.pk}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 200, resp.data

    mark = MarkDamaged.objects.get(pk=flag["id"])
    assert mark.docstatus == DocStatus.SUBMITTED
    assert mark.doc_number is not None
    assert mark.created_by_id == s["reporter"].id
    assert mark.confirmed_by_id == s["confirmer"].id

    assert StockOnHand.objects.get(store=s["store"], sku_code="DM001").net_qty == 7
    quarantine = QuarantineStock.objects.get(store=s["store"], sku_code="DM001")
    assert quarantine.qty == 3
    assert quarantine.value_paise == 3 * 45000

    out = StockLedgerEntry.objects.get(doc_number=mark.doc_number, kind="damage_out")
    qin = StockLedgerEntry.objects.get(doc_number=mark.doc_number, kind="quarantine_in")
    assert out.qty == -3 and out.amount == -3 * 45000
    assert qin.qty == 3 and qin.amount == 3 * 45000


@pytest.mark.django_db(transaction=True)
def test_the_warehouse_flags_and_confirms_in_one_action(damage_scaffold):
    """A warehouse person who finds the damage themselves holds both rungs, so
    nobody else is asked — but the record still says so."""
    s = damage_scaffold
    posted = _flag(s, qty=2, user=s["confirmer"])

    assert posted["docstatus"] == DocStatus.SUBMITTED
    assert posted["flag_status"] == "confirmed"

    mark = MarkDamaged.objects.get(pk=posted["id"])
    assert mark.created_by_id == s["confirmer"].id
    assert mark.confirmed_by_id == s["confirmer"].id
    assert QuarantineStock.objects.get(store=s["store"], sku_code="DM001").qty == 2
    assert _approval(mark.pk).status == ApprovalStatus.NOT_REQUIRED


# ---------------------------------------------------------------------------
# Who may confirm — the API seam
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_store_role_calling_the_confirm_endpoint_is_refused(damage_scaffold):
    """Not merely hidden in the UI: the server refuses, and nothing posts."""
    s = damage_scaffold
    flag = _flag(s, qty=3)
    approval = _approval(flag["id"])

    resp = _client(s["colleague"]).post(
        f"/api/approvals/{approval.pk}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 403, resp.data

    assert MarkDamaged.objects.get(pk=flag["id"]).docstatus == DocStatus.DRAFT
    assert not QuarantineStock.objects.exists()
    assert StockOnHand.objects.get(store=s["store"], sku_code="DM001").net_qty == 10


@pytest.mark.django_db(transaction=True)
def test_the_reporter_cannot_confirm_their_own_flag(damage_scaffold):
    """Maker is never checker — a store person cannot wave their own report
    through even if their role were widened."""
    s = damage_scaffold
    flag = _flag(s, qty=3)
    approval = _approval(flag["id"])

    resp = _client(s["reporter"]).post(
        f"/api/approvals/{approval.pk}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 403
    assert not QuarantineStock.objects.exists()


# ---------------------------------------------------------------------------
# Rejection — the piece goes back to being ordinary stock
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_rejected_flag_returns_the_piece_to_normal_stock_with_a_reason(damage_scaffold):
    """Rejecting closes the report with a reason. Nothing ever left sellable
    stock, so the shirt simply carries on being sellable."""
    s = damage_scaffold
    flag = _flag(s, qty=3)
    approval = _approval(flag["id"])

    resp = _client(s["confirmer"]).post(
        f"/api/approvals/{approval.pk}/decide",
        {"action": "reject", "reason": "Only the tag was torn — it is sellable."},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.REJECTED
    assert approval.decided_by_id == s["confirmer"].id
    assert "tag was torn" in approval.reason

    assert StockOnHand.objects.get(store=s["store"], sku_code="DM001").net_qty == 10
    assert not QuarantineStock.objects.exists()

    mine = _client(s["reporter"]).get("/api/outbound/mark-damaged")
    row = next(r for r in mine.data if r["id"] == flag["id"])
    assert row["flag_status"] == "rejected"
    assert "tag was torn" in row["approval"]["reason"]


@pytest.mark.django_db(transaction=True)
def test_rejecting_without_a_reason_is_refused(damage_scaffold):
    s = damage_scaffold
    flag = _flag(s, qty=3)
    approval = _approval(flag["id"])

    resp = _client(s["confirmer"]).post(
        f"/api/approvals/{approval.pk}/decide", {"action": "reject"}, format="json"
    )
    assert resp.status_code == 400
    assert _approval(flag["id"]).status == ApprovalStatus.PENDING


@pytest.mark.django_db(transaction=True)
def test_a_flag_cannot_be_confirmed_once_the_stock_has_gone(damage_scaffold):
    """The flag does not block the shelf (Rule 5), so the piece can be sold
    while it waits. Confirming then has nothing to quarantine, and says so
    rather than posting a movement that isn't there."""
    s = damage_scaffold
    flag = _flag(s, qty=3)
    on_hand = StockOnHand.objects.get(store=s["store"], sku_code="DM001")
    on_hand.net_qty = 1
    on_hand.net_value_paise = 45000
    on_hand.save(update_fields=["net_qty", "net_value_paise"])

    approval = _approval(flag["id"])
    resp = _client(s["confirmer"]).post(
        f"/api/approvals/{approval.pk}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 400
    assert "Insufficient" in str(resp.data)

    # The decision rolled back with the posting — the flag is still waiting.
    assert _approval(flag["id"]).status == ApprovalStatus.PENDING
    assert MarkDamaged.objects.get(pk=flag["id"]).docstatus == DocStatus.DRAFT
    assert not QuarantineStock.objects.exists()
