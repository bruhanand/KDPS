"""Outbound slice 2 — quarantine + global mark-damaged (#69, PRD #67).

Seams (agreed in the PRD):
- **API seam**: the global mark-damaged action through the DRF view — a store +
  scanned pieces → a posted DMG document; the quarantine read filter; scoping.
  Amended by #138: it posts *here* because the actor holds the confirming rung
  (warehouse). A store person's mark-damaged is a flag that posts nothing, which
  is ``test_outbound_damage_flag.py``'s subject.
- **Stock-ledger seam**: mark-damaged moves the piece out of free-to-sell
  (``StockOnHand`` drops) and into the quarantine bucket (``QuarantineStock``)
  at the same store — never in no location, value conserved. The projections
  rebuild exactly from the append-only ledger.

Rulings (system.md OUTBOUND · Damage): damage is a *global action*, not a
receive-time event; quarantine is a *stock state in the ledger*, excluded from
free-to-sell; every mark-damaged records who did it and when (Rule 10). A
mark-damaged is a document (Rule 1).
"""

from __future__ import annotations

import pytest
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from core.documents import DocStatus, VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import MarkDamaged
from stockledger.models import QuarantineStock, StockLedgerEntry, StockOnHand

FY = "26-27"


@pytest.fixture()
def quar_scaffold(db):
    """One store with seeded sellable stock + a cohort cost, an all-scope user,
    plus a store-scoped user for the scoping test."""
    entity = LegalEntity.objects.create(code="q-ent", name="Quar Entity", pan="AAACT1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACT1234C1ZS",
        state_code="20",
        state_name="Jharkhand",
        legal_entity=entity,
    )
    store = Store.objects.create(code="Q-A", name="Quar Store A", gstin=gstin)
    other = Store.objects.create(code="Q-B", name="Quar Store B", gstin=gstin)

    Brand.objects.create(
        code="q-br",
        name="QuarBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    # Marking damage is `return_to_brand: operate` (#94) — the warehouse and the
    # store hold it; HO ops, which only monitors returns, no longer does.
    role = make_role("warehouse", "Warehouse (quar test)")
    user = User.objects.create_user(
        username="quar_ops",
        password="Test@123",
        role=role,
        entity=entity,
        scope_type=ScopeType.ALL,
    )

    sku = Sku.objects.create(
        barcode="QC001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="QuarBrand",
        item="shirt",
        hsn="6205",
        mrp_paise=99900,
    )
    Cohort.objects.create(
        sku=sku, barcode="QC001", season="SS26", unit_cost_paise=45000, mrp_paise=99900
    )

    for barcode, qty, unit_cost in [("QC001", 10, 45000)]:
        StockOnHand.objects.create(
            store=store,
            gstin=gstin,
            sku_code=barcode,
            design="Shirt",
            color="Blue",
            size="M",
            brand="QuarBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
            net_qty=qty,
            net_value_paise=qty * unit_cost,
        )
        StockLedgerEntry.objects.create(
            store=store,
            gstin=gstin,
            sku_code=barcode,
            design="Shirt",
            color="Blue",
            size="M",
            brand="QuarBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
            qty=qty,
            amount=qty * unit_cost,
            kind="pt_inward",
            doc_number="QUAR-SEED",
            line_no=1,
        )

    for code in ["Q-A", "Q-B"]:
        VoucherSeries.objects.create(
            fy=FY, store_code=code, doc_type="DMG", prefix=f"{code}/DMG/{FY}/", next_seq=1
        )

    return {"gstin": gstin, "store": store, "other": other, "user": user}


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _total_qty(barcode: str) -> int:
    """Conservation probe: every piece is free-to-sell or quarantined."""
    on_hand = sum(StockOnHand.objects.filter(sku_code=barcode).values_list("net_qty", flat=True))
    quar = sum(QuarantineStock.objects.filter(sku_code=barcode).values_list("qty", flat=True))
    return on_hand + quar


# ---------------------------------------------------------------------------
# Mark damaged → quarantine (the ledger state)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_mark_damaged_moves_stock_into_quarantine(quar_scaffold):
    """Marking 3 pieces damaged drops free-to-sell by 3 and puts 3 in the
    quarantine bucket at the same store — a document, a ledger state change,
    excluded from sellable."""
    s = quar_scaffold
    c = _client(s["user"])

    assert _total_qty("QC001") == 10
    resp = c.post(
        "/api/outbound/mark-damaged",
        {"store": s["store"].id, "scans": [{"barcode": "QC001", "qty": 3}]},
        format="json",
    )
    assert resp.status_code == 201, resp.data

    # A posted DMG document backs the action (Rule 1) with an actor (Rule 10)
    assert resp.data["docstatus"] == DocStatus.SUBMITTED
    assert resp.data["doc_number"] is not None
    mark = MarkDamaged.objects.get(doc_number=resp.data["doc_number"])
    assert mark.created_by_id == s["user"].id

    # Free-to-sell dropped; the pieces are in quarantine at the same store
    assert StockOnHand.objects.get(store=s["store"], sku_code="QC001").net_qty == 7
    q = QuarantineStock.objects.get(store=s["store"], sku_code="QC001")
    assert q.qty == 3
    assert q.marked_by_id == s["user"].id
    assert q.marked_at is not None
    assert q.value_paise == 3 * 45000

    # Ledger legs: −3 out of sellable + 3 into quarantine, value conserved
    out = StockLedgerEntry.objects.get(doc_number=mark.doc_number, kind="damage_out")
    qin = StockLedgerEntry.objects.get(doc_number=mark.doc_number, kind="quarantine_in")
    assert out.qty == -3 and out.amount == -3 * 45000
    assert qin.qty == 3 and qin.amount == 3 * 45000
    assert _total_qty("QC001") == 10


@pytest.mark.django_db(transaction=True)
def test_quarantine_excluded_from_free_to_sell_view(quar_scaffold):
    """Quarantined stock is not in the on-hand (free-to-sell) view but is in the
    quarantine filter, with who marked it and when."""
    s = quar_scaffold
    c = _client(s["user"])
    c.post(
        "/api/outbound/mark-damaged",
        {"store": s["store"].id, "scans": [{"barcode": "QC001", "qty": 4}]},
        format="json",
    )

    on_hand = c.get("/api/stockledger/on-hand?group_by=sku")
    row = next(r for r in on_hand.data["rows"] if r["sku_code"] == "QC001")
    assert row["net_qty"] == 6  # only free-to-sell

    quar = c.get("/api/stockledger/quarantine")
    assert quar.status_code == 200
    assert quar.data["summary"]["units_quarantined"] == 4
    qrow = quar.data["rows"][0]
    assert qrow["sku_code"] == "QC001"
    assert qrow["qty"] == 4
    assert qrow["marked_by"] == s["user"].username
    assert qrow["marked_at"] is not None


@pytest.mark.django_db(transaction=True)
def test_mark_damaged_insufficient_stock_rejected(quar_scaffold):
    """You cannot quarantine stock that isn't sellable at the store → 400,
    nothing quarantined, no orphan draft left behind."""
    s = quar_scaffold
    c = _client(s["user"])
    resp = c.post(
        "/api/outbound/mark-damaged",
        {"store": s["store"].id, "scans": [{"barcode": "QC001", "qty": 99}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "Insufficient" in str(resp.data)
    assert not QuarantineStock.objects.exists()
    assert not MarkDamaged.objects.exists()  # draft rolled back
    assert StockOnHand.objects.get(store=s["store"], sku_code="QC001").net_qty == 10


@pytest.mark.django_db(transaction=True)
def test_mark_damaged_unknown_barcode_rejected(quar_scaffold):
    """A barcode with no stock at the store beeps wrong → 400, draft rolled back."""
    s = quar_scaffold
    c = _client(s["user"])
    resp = c.post(
        "/api/outbound/mark-damaged",
        {"store": s["store"].id, "scans": [{"barcode": "NO-SUCH", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "NO-SUCH" in str(resp.data)
    assert not MarkDamaged.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_mark_damaged_is_store_scoped(quar_scaffold):
    """A store-scoped user cannot mark damaged at a store outside their scope."""
    s = quar_scaffold
    role = make_role("store_manager", "SM (quar test)")
    sm = User.objects.create_user(
        username="quar_sm", password="Test@123", role=role, scope_type=ScopeType.STORE
    )
    sm.stores.add(s["other"])  # scoped to Q-B, NOT Q-A where the stock is
    c = _client(sm)
    resp = c.post(
        "/api/outbound/mark-damaged",
        {"store": s["store"].id, "scans": [{"barcode": "QC001", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 403
    assert not QuarantineStock.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_quarantine_filter_is_store_scoped_fail_closed(quar_scaffold):
    """A store-scoped user sees only their own stores' quarantine (ADR-0003)."""
    s = quar_scaffold
    _client(s["user"]).post(
        "/api/outbound/mark-damaged",
        {"store": s["store"].id, "scans": [{"barcode": "QC001", "qty": 2}]},
        format="json",
    )
    role = make_role("store_manager", "SM2 (quar test)")
    sm = User.objects.create_user(
        username="quar_sm2", password="Test@123", role=role, scope_type=ScopeType.STORE
    )
    sm.stores.add(s["other"])  # not the store holding the quarantine
    resp = _client(sm).get("/api/stockledger/quarantine")
    assert resp.status_code == 200
    assert resp.data["summary"]["units_quarantined"] == 0
    assert resp.data["rows"] == []


# ---------------------------------------------------------------------------
# Rebuildability — the projections are caches of the append-only ledger
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_rebuild_reproduces_quarantine_from_ledger(quar_scaffold):
    """Wiping and rebuilding from the ledger reproduces StockOnHand AND the
    quarantine bucket (qty, value, who, when) exactly."""
    from django.core.management import call_command

    s = quar_scaffold
    c = _client(s["user"])
    c.post(
        "/api/outbound/mark-damaged",
        {"store": s["store"].id, "scans": [{"barcode": "QC001", "qty": 3}]},
        format="json",
    )

    before_oh = sorted(StockOnHand.objects.values_list("store_id", "sku_code", "net_qty"))
    before_q = sorted(
        QuarantineStock.objects.values_list(
            "store_id", "sku_code", "qty", "value_paise", "marked_by_id"
        )
    )
    assert before_q == [(s["store"].id, "QC001", 3, 3 * 45000, s["user"].id)]

    StockOnHand.objects.all().delete()
    QuarantineStock.objects.all().delete()
    call_command("rebuild_stock_on_hand")

    after_oh = sorted(StockOnHand.objects.values_list("store_id", "sku_code", "net_qty"))
    after_q = sorted(
        QuarantineStock.objects.values_list(
            "store_id", "sku_code", "qty", "value_paise", "marked_by_id"
        )
    )
    assert after_oh == before_oh
    assert after_q == before_q


# ---------------------------------------------------------------------------
# Seeder guard — mark-damaged needs a DMG VoucherSeries at every store
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_seed_outbound_demo_emits_dmg_series():
    """Regression guard for #69 gap #1.

    ``seed_outbound_demo`` must mint a ``DMG`` VoucherSeries for every store —
    without it ``mark_damaged`` can't allocate a doc number, so the whole
    action silently rolls back on a freshly-seeded demo. The other seam tests
    hand-create their own DMG series (see ``quar_scaffold``), so only running
    the real seeders end-to-end catches the omission.
    """
    from django.core.management import call_command

    call_command("seed_foundation")
    call_command("seed_outbound_demo")

    stores = list(Store.objects.values_list("code", flat=True))
    assert stores, "seed_foundation should have created stores"
    missing = [
        code
        for code in stores
        if not VoucherSeries.objects.filter(store_code=code, doc_type="DMG").exists()
    ]
    assert not missing, f"no DMG VoucherSeries seeded for stores: {missing}"


@pytest.mark.django_db(transaction=True)
def test_mark_damaged_list_rejects_non_integer_docstatus(quar_scaffold):
    """A malformed ``?docstatus=`` is a client error (400), not an uncaught
    500 from ``int()`` — the list filter validates its input."""
    s = quar_scaffold
    resp = _client(s["user"]).get("/api/outbound/mark-damaged?docstatus=abc")
    assert resp.status_code == 400
    assert "docstatus" in str(resp.data)
