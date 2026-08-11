"""Distribution grid: confirm bulk-creates per-store draft transfers (#73).

The grid itself is client-side allocation — nothing here posts to the ledger,
so the API seam that matters is the same one "Send Stock" already uses one
store at a time: a POST per destination that lands in the Operations Head's
inbox, per #137. These tests prove the bulk case behaves like N of the single
case, plus the suggestion service the grid's pre-fill reads from.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _transfers import approve_transfer
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalStatus
from core.documents import DocStatus, VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.distribution import DEFAULT_KEY, suggest_split
from outbound.models import StoreTransfer, StoreTransferLine, TransferReason
from stockledger.models import StockOnHand

FY = "26-27"


@pytest.fixture()
def grid(db):
    """A warehouse, three same-state stores, and the warehouse person who runs
    the grid. Two SKUs of one brand, both in stock at the warehouse."""
    entity = LegalEntity.objects.create(code="dg-ent", name="Grid Entity", pan="AAACD1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACD1234C1ZQ", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    warehouse = Store.objects.create(
        code="DG-WH", name="Grid Warehouse", gstin=gstin, store_type="warehouse"
    )
    store_a = Store.objects.create(code="DG-A", name="Grid Store A", gstin=gstin)
    store_b = Store.objects.create(code="DG-B", name="Grid Store B", gstin=gstin)
    store_c = Store.objects.create(code="DG-C", name="Grid Store C", gstin=gstin)

    Brand.objects.create(
        code="dg-br",
        name="GridBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    def _seed_sku(barcode, size, qty, unit_cost=45000):
        sku = Sku.objects.create(
            barcode=barcode,
            design="Kurta",
            color="Red",
            size=size,
            brand="GridBrand",
            item="kurta",
            hsn="6204",
            mrp_paise=99900,
        )
        Cohort.objects.create(
            sku=sku, barcode=barcode, season="SS26", unit_cost_paise=unit_cost, mrp_paise=99900
        )
        StockOnHand.objects.create(
            store=warehouse,
            gstin=gstin,
            sku_code=barcode,
            design="Kurta",
            color="Red",
            size=size,
            brand="GridBrand",
            season="SS26",
            item="kurta",
            hsn="6204",
            net_qty=qty,
            net_value_paise=qty * unit_cost,
        )

    _seed_sku("DG001", "S", 100)
    _seed_sku("DG002", "M", 50)

    def _user(username, role_code, stores=()):
        u = User.objects.create_user(
            username=username,
            password=TEST_PASSWORD,
            role=make_role(role_code),
            entity=entity,
            scope_type=ScopeType.ALL,
        )
        for s in stores:
            u.stores.add(s)
        return u

    sender = _user("dg_sender", "warehouse")

    for code in ["DG-WH", "DG-A", "DG-B", "DG-C"]:
        VoucherSeries.objects.create(
            fy=FY, store_code=code, doc_type="STO", prefix=f"{code}/STO/{FY}/", next_seq=1
        )

    return {
        "warehouse": warehouse,
        "store_a": store_a,
        "store_b": store_b,
        "store_c": store_c,
        "sender": sender,
    }


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _confirm(g, plan_by_store):
    """Mirror what the grid's Confirm button does: one POST per destination
    store with that store's lines, exactly as `DistributionGrid.tsx` sends."""
    results = []
    for store, lines in plan_by_store.items():
        resp = _client(g["sender"]).post(
            "/api/outbound/transfers",
            {
                "source_store": g["warehouse"].id,
                "destination_store": store.id,
                "transfer_type": "store_split",
                "reason": "warehouse_allocation",
                "lines": [{"sku_code": b, "qty_planned": q} for b, q in lines],
            },
            format="json",
        )
        results.append(resp)
    return results


def _confirm_dispatched(g, plan_by_store):
    """Same as `_confirm`, but taken all the way to a dispatched transfer —
    the `suggest_split` history a *completed* allocation leaves behind, since
    dims are only stamped onto a line at dispatch (see `distribution.py`)."""
    responses = _confirm(g, plan_by_store)
    for resp, lines in zip(responses, plan_by_store.values(), strict=True):
        assert resp.status_code == 201, resp.data
        transfer_id = resp.data["id"]
        approve_transfer(StoreTransfer.objects.get(pk=transfer_id))
        dispatch_resp = _client(g["sender"]).post(
            f"/api/outbound/transfers/{transfer_id}/dispatch",
            {"scans": [{"barcode": b, "qty": q} for b, q in lines]},
            format="json",
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.data


@pytest.mark.django_db(transaction=True)
def test_confirm_creates_one_draft_transfer_per_destination_store_unapproved(grid):
    g = grid
    responses = _confirm(
        g,
        {
            g["store_a"]: [("DG001", 10), ("DG002", 5)],
            g["store_b"]: [("DG001", 8)],
        },
    )
    for resp in responses:
        assert resp.status_code == 201, resp.data

    transfers = StoreTransfer.objects.filter(reason=TransferReason.WAREHOUSE_ALLOCATION).order_by(
        "destination_store__code"
    )
    assert transfers.count() == 2
    assert list(transfers.values_list("destination_store__code", flat=True)) == ["DG-A", "DG-B"]

    for transfer in transfers:
        # Correct lines: still just the plan, and still unapproved.
        assert transfer.docstatus == DocStatus.DRAFT
        assert not transfer.doc_number
        approval = Approval.objects.get(kind="transfer", object_id=transfer.id)
        assert approval.status == ApprovalStatus.PENDING

    a_lines = {
        (line.sku_code, line.qty_planned)
        for line in StoreTransferLine.objects.filter(transfer__destination_store=g["store_a"])
    }
    assert a_lines == {("DG001", 10), ("DG002", 5)}
    b_lines = {
        (line.sku_code, line.qty_planned)
        for line in StoreTransferLine.objects.filter(transfer__destination_store=g["store_b"])
    }
    assert b_lines == {("DG001", 8)}

    # Nothing moved: the grid posts nothing to the ledger.
    assert StockOnHand.objects.get(store=g["warehouse"], sku_code="DG001").net_qty == 100
    assert StockOnHand.objects.get(store=g["warehouse"], sku_code="DG002").net_qty == 50


@pytest.mark.django_db(transaction=True)
def test_a_bad_destination_leaves_the_good_ones_drafted(grid):
    """One store rejected (e.g. missing e-way bill on a cross-state leg) never
    rolls back the others — each POST is its own transaction, same as the
    grid firing N independent requests."""
    g = grid
    responses = _confirm(
        g,
        {
            g["store_a"]: [("DG001", 5)],
            g["warehouse"]: [("DG001", 5)],  # source == destination: refused
        },
    )
    assert responses[0].status_code == 201
    assert responses[1].status_code == 400
    assert StoreTransfer.objects.filter(destination_store=g["store_a"]).exists()


@pytest.mark.django_db(transaction=True)
def test_suggest_split_falls_back_to_equal_with_no_history(grid):
    g = grid
    weights = suggest_split(
        warehouse_id=g["warehouse"].id,
        brand="GridBrand",
        store_ids=[g["store_a"].id, g["store_b"].id],
    )
    assert weights[DEFAULT_KEY] == {str(g["store_a"].id): 0.5, str(g["store_b"].id): 0.5}


@pytest.mark.django_db(transaction=True)
def test_suggest_split_weights_by_each_store_s_last_split(grid):
    """A's last allocation of size S ran 3:1 against B — the suggestion should
    carry that forward, not reset to even."""
    g = grid
    _confirm_dispatched(g, {g["store_a"]: [("DG001", 30)], g["store_b"]: [("DG001", 10)]})

    weights = suggest_split(
        warehouse_id=g["warehouse"].id,
        brand="GridBrand",
        store_ids=[g["store_a"].id, g["store_b"].id],
    )
    assert weights["S"] == {str(g["store_a"].id): 0.75, str(g["store_b"].id): 0.25}
    # Size M has never been dispatched at all — absent, not a key with a
    # fabricated answer; the caller falls back to DEFAULT_KEY (still 3:1
    # here, S being the only size seen so far).
    assert "M" not in weights
    assert weights[DEFAULT_KEY] == {str(g["store_a"].id): 0.75, str(g["store_b"].id): 0.25}


@pytest.mark.django_db(transaction=True)
def test_suggest_split_only_counts_the_most_recent_batch_per_store_and_size(grid):
    """ "Last" split, not "every" split: a store's older allocation of a size
    must not still be dragging the weight once a newer one exists."""
    g = grid
    _confirm_dispatched(g, {g["store_a"]: [("DG001", 20)], g["store_b"]: [("DG001", 20)]})
    # A's most recent ask for size S was small.
    _confirm_dispatched(g, {g["store_a"]: [("DG001", 5)]})

    weights = suggest_split(
        warehouse_id=g["warehouse"].id,
        brand="GridBrand",
        store_ids=[g["store_a"].id, g["store_b"].id],
    )
    assert weights["S"] == {str(g["store_a"].id): 5 / 25, str(g["store_b"].id): 20 / 25}


@pytest.mark.django_db(transaction=True)
def test_suggested_split_endpoint_is_scoped_like_raising_a_transfer(grid):
    g = grid
    resp = _client(g["sender"]).get(
        "/api/outbound/distribution/suggested-split",
        {
            "warehouse": g["warehouse"].id,
            "brand": "GridBrand",
            "stores": f"{g['store_a'].id},{g['store_b'].id}",
        },
    )
    assert resp.status_code == 200
    assert set(resp.data["weights"][DEFAULT_KEY]) == {str(g["store_a"].id), str(g["store_b"].id)}

    other_entity = LegalEntity.objects.create(code="og-ent", name="Other Entity", pan="AAACO4321C")
    other_gstin = Gstin.objects.create(
        gstin="10AAACO4321C1ZR", state_code="10", state_name="Bihar", legal_entity=other_entity
    )
    outside_warehouse = Store.objects.create(
        code="OG-WH", name="Outside Warehouse", gstin=other_gstin, store_type="warehouse"
    )
    scoped_user = User.objects.create_user(
        username="dg_scoped",
        password=TEST_PASSWORD,
        role=make_role("warehouse"),
        entity=g["warehouse"].gstin.legal_entity,
        scope_type=ScopeType.STORE,
    )
    scoped_user.stores.add(g["warehouse"])
    resp = _client(scoped_user).get(
        "/api/outbound/distribution/suggested-split",
        {"warehouse": outside_warehouse.id, "brand": "GridBrand", "stores": str(g["store_a"].id)},
    )
    assert resp.status_code == 403
