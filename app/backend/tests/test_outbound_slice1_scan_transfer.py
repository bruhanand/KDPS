"""Outbound slice 1 — scanned transfer core + in-transit stock bucket (#68).

Seams (agreed in the PRD, issue #67/#68):
- **API seam**: dispatch/receive round-trip through the DRF views with scanned
  payloads only — typed quantities can no longer dispatch a transfer.
- **Stock-ledger seam**: after dispatch the pieces sit *in transit under the
  transfer* — not at source, not at destination, never in no location.
  Free-to-sell (``StockOnHand``) excludes in-transit throughout.

Scan-is-truth rulings (Anand, 23 Jul):
- Dispatch posts exactly what was scanned; a scanned-vs-plan mismatch is
  flagged, never blocked (Rule 5).  A barcode NOT on the plan is rejected.
- Receive posts what was scanned; a short receive leaves the remainder
  in-transit and flags the receipt (gap *closure* is a later slice).
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _transfers import approve_transfer
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from core.documents import DocStatus, VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import StoreTransfer, StoreTransferLine, TransferReceipt
from stockledger.models import InTransitStock, StockLedgerEntry, StockOnHand

FY = "26-27"


@pytest.fixture()
def scan_scaffold(db):
    """Warehouse + two stores (same state), seeded stock + cohort costs."""
    entity = LegalEntity.objects.create(code="scan-ent", name="Scan Entity", pan="AAACT1234C")
    gstin_jh = Gstin.objects.create(
        gstin="20AAACT1234C1ZS",
        state_code="20",
        state_name="Jharkhand",
        legal_entity=entity,
    )
    warehouse = Store.objects.create(
        code="SN-WH", name="Scan Warehouse", gstin=gstin_jh, store_type="warehouse"
    )
    store_a = Store.objects.create(code="SN-A", name="Scan Store A", gstin=gstin_jh)
    store_b = Store.objects.create(code="SN-B", name="Scan Store B", gstin=gstin_jh)

    Brand.objects.create(
        code="scan-br",
        name="ScanBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    role = make_role("ho_ops", "HO Ops (scan test)")
    user = User.objects.create_user(
        username="scan_ops",
        password=TEST_PASSWORD,
        role=role,
        entity=entity,
        scope_type=ScopeType.ALL,
    )

    # SKU registry + cohort (frozen P-RATE cost) for BC001; BC002 has stock
    # but no cohort so cost falls back to the on-hand average.
    sku1 = Sku.objects.create(
        barcode="BC001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="ScanBrand",
        item="shirt",
        hsn="6205",
        mrp_paise=99900,
    )
    Cohort.objects.create(
        sku=sku1, barcode="BC001", season="SS26", unit_cost_paise=45000, mrp_paise=99900
    )

    seed = [
        ("BC001", "Shirt", "Blue", "M", 10, 45000),
        ("BC002", "Jeans", "Black", "L", 6, 30000),
    ]
    for barcode, design, color, size, qty, unit_cost in seed:
        StockOnHand.objects.create(
            store=warehouse,
            gstin=gstin_jh,
            sku_code=barcode,
            design=design,
            color=color,
            size=size,
            brand="ScanBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
            net_qty=qty,
            net_value_paise=qty * unit_cost,
        )
        StockLedgerEntry.objects.create(
            store=warehouse,
            gstin=gstin_jh,
            sku_code=barcode,
            design=design,
            color=color,
            size=size,
            brand="ScanBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
            qty=qty,
            amount=qty * unit_cost,
            kind="pt_inward",
            doc_number="SCAN-SEED",
            line_no=1,
        )

    for code in ["SN-WH", "SN-A", "SN-B"]:
        VoucherSeries.objects.create(
            fy=FY,
            store_code=code,
            doc_type="STO",
            prefix=f"{code}/STO/{FY}/",
            next_seq=1,
        )

    return {
        "gstin_jh": gstin_jh,
        "warehouse": warehouse,
        "store_a": store_a,
        "store_b": store_b,
        "user": user,
    }


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _make_planned_transfer(s, plan=(("BC001", 3),)) -> StoreTransfer:
    """Draft warehouse→store transfer with plan lines (the grid stand-in)."""
    transfer = StoreTransfer.objects.create(
        source_store=s["warehouse"],
        destination_store=s["store_a"],
        transfer_type="store_split",
        created_by=s["user"],
    )
    for barcode, qty in plan:
        StoreTransferLine.objects.create(
            transfer=transfer, sku_code=barcode, qty_planned=qty, qty_dispatched=0
        )
    approve_transfer(transfer)  # nothing leaves without the Operations Head (#137)
    return transfer


def _total_qty(barcode: str) -> int:
    """Conservation probe: every piece is at a location or in transit."""
    on_hand = sum(StockOnHand.objects.filter(sku_code=barcode).values_list("net_qty", flat=True))
    in_transit = sum(InTransitStock.objects.filter(sku_code=barcode).values_list("qty", flat=True))
    return on_hand + in_transit


# ---------------------------------------------------------------------------
# Dispatch — scanned lines only
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_dispatch_without_scans_rejected(scan_scaffold):
    """A transfer cannot be dispatched with typed quantities — scans required."""
    s = scan_scaffold
    transfer = _make_planned_transfer(s)
    c = _client(s["user"])

    # Old-style empty payload (typed lines used to carry the qty) → 400
    resp = c.post(f"/api/outbound/transfers/{transfer.pk}/dispatch", {}, format="json")
    assert resp.status_code == 400

    transfer.refresh_from_db()
    assert transfer.docstatus == DocStatus.DRAFT
    assert not StockLedgerEntry.objects.filter(kind="transfer_out").exists()


@pytest.mark.django_db(transaction=True)
def test_dispatch_moves_stock_into_in_transit_bucket(scan_scaffold):
    """After dispatch the pieces are in-transit under the transfer — not at
    source, not at destination, never in no location."""
    s = scan_scaffold
    transfer = _make_planned_transfer(s, plan=(("BC001", 3),))
    c = _client(s["user"])

    assert _total_qty("BC001") == 10
    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/dispatch",
        {"scans": [{"barcode": "BC001", "qty": 3}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    transfer.refresh_from_db()
    assert transfer.docstatus == DocStatus.SUBMITTED

    # Source lost the pieces (free-to-sell excludes in-transit)
    assert StockOnHand.objects.get(store=s["warehouse"], sku_code="BC001").net_qty == 7
    # Destination has nothing yet
    assert not StockOnHand.objects.filter(store=s["store_a"], sku_code="BC001").exists()
    # The pieces are in-transit UNDER THIS TRANSFER
    bucket = InTransitStock.objects.get(transfer_doc_number=transfer.doc_number)
    assert bucket.sku_code == "BC001"
    assert bucket.qty == 3
    # Ledger legs: −3 at source + 3 into transit, at the frozen cohort cost
    out = StockLedgerEntry.objects.get(doc_number=transfer.doc_number, kind="transfer_out")
    tin = StockLedgerEntry.objects.get(doc_number=transfer.doc_number, kind="transit_in")
    assert out.qty == -3 and out.store_id == s["warehouse"].id
    assert tin.qty == 3
    assert out.amount == -3 * 45000 and tin.amount == 3 * 45000
    # Conservation: no piece vanished
    assert _total_qty("BC001") == 10


@pytest.mark.django_db(transaction=True)
def test_dispatch_scan_not_on_plan_rejected(scan_scaffold):
    """A barcode outside the transfer's plan is the wrong-piece beep → 400."""
    s = scan_scaffold
    transfer = _make_planned_transfer(s, plan=(("BC001", 3),))
    c = _client(s["user"])

    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/dispatch",
        {"scans": [{"barcode": "BC002", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "BC002" in str(resp.data)
    transfer.refresh_from_db()
    assert transfer.docstatus == DocStatus.DRAFT
    assert not InTransitStock.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_dispatch_partial_scan_flags_never_blocks(scan_scaffold):
    """Scan-is-truth: plan 5, scan 3 → dispatch 3, mismatch flagged (Rule 5)."""
    s = scan_scaffold
    transfer = _make_planned_transfer(s, plan=(("BC001", 5),))
    c = _client(s["user"])

    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/dispatch",
        {"scans": [{"barcode": "BC001", "qty": 3}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["dispatch_mismatch"] is True
    line = resp.data["lines"][0]
    assert line["qty_planned"] == 5
    assert line["qty_dispatched"] == 3
    assert InTransitStock.objects.get(transfer_doc_number=resp.data["doc_number"]).qty == 3


@pytest.mark.django_db(transaction=True)
def test_dispatch_insufficient_stock_rejected(scan_scaffold):
    s = scan_scaffold
    transfer = _make_planned_transfer(s, plan=(("BC001", 99),))
    c = _client(s["user"])

    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/dispatch",
        {"scans": [{"barcode": "BC001", "qty": 99}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "Insufficient" in str(resp.data)


# ---------------------------------------------------------------------------
# Store→store — lines built by scanning (no plan)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_store_to_store_builds_lines_by_scanning(scan_scaffold):
    """A transfer created with no lines gets its lines from what was scanned,
    enriched from the source stock (dims) + cohort (frozen cost)."""
    s = scan_scaffold
    c = _client(s["user"])

    resp = c.post(
        "/api/outbound/transfers",
        {
            "source_store": s["warehouse"].id,
            "destination_store": s["store_b"].id,
            "transfer_type": "inter_store",
            "transport_mode": "public_bus",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["lines"] == []
    tid = resp.data["id"]
    approve_transfer(StoreTransfer.objects.get(pk=tid))

    resp = c.post(
        f"/api/outbound/transfers/{tid}/dispatch",
        {"scans": [{"barcode": "BC001", "qty": 2}, {"barcode": "BC002", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    lines = {ln["sku_code"]: ln for ln in resp.data["lines"]}
    assert lines["BC001"]["qty_dispatched"] == 2
    assert lines["BC001"]["qty_planned"] is None
    assert lines["BC001"]["design"] == "Shirt"  # enriched from stock, not typed
    assert lines["BC001"]["unit_cost_paise"] == 45000  # frozen cohort cost
    assert lines["BC002"]["qty_dispatched"] == 1
    assert lines["BC002"]["unit_cost_paise"] == 30000  # on-hand average fallback
    assert resp.data["dispatch_mismatch"] is False

    assert InTransitStock.objects.filter(transfer_doc_number=resp.data["doc_number"]).count() == 2


@pytest.mark.django_db(transaction=True)
def test_scan_to_build_unknown_barcode_rejected(scan_scaffold):
    """Scanning a piece the source has no stock of beeps wrong → 400."""
    s = scan_scaffold
    c = _client(s["user"])
    transfer = StoreTransfer.objects.create(
        source_store=s["warehouse"],
        destination_store=s["store_b"],
        transfer_type="inter_store",
        created_by=s["user"],
    )
    approve_transfer(transfer)
    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/dispatch",
        {"scans": [{"barcode": "NO-SUCH", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "NO-SUCH" in str(resp.data)


# ---------------------------------------------------------------------------
# Receive — scan in, in-transit → destination
# ---------------------------------------------------------------------------


def _dispatched(s, qty=3):
    transfer = _make_planned_transfer(s, plan=(("BC001", qty),))
    c = _client(s["user"])
    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/dispatch",
        {"scans": [{"barcode": "BC001", "qty": qty}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    transfer.refresh_from_db()
    return transfer, c


@pytest.mark.django_db(transaction=True)
def test_receive_full_round_trip(scan_scaffold):
    """Scan-receive everything → pieces at destination, in-transit empty."""
    s = scan_scaffold
    transfer, c = _dispatched(s, qty=3)

    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "BC001", "qty": 3}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    # In-transit bucket for this transfer is empty
    assert not InTransitStock.objects.filter(
        transfer_doc_number=transfer.doc_number, qty__gt=0
    ).exists()
    # Pieces are at the destination
    assert StockOnHand.objects.get(store=s["store_a"], sku_code="BC001").net_qty == 3
    # Ledger legs for the receive side
    tout = StockLedgerEntry.objects.get(doc_number=transfer.doc_number, kind="transit_out")
    tin = StockLedgerEntry.objects.get(doc_number=transfer.doc_number, kind="transfer_in")
    assert tout.qty == -3
    assert tin.qty == 3 and tin.store_id == s["store_a"].id
    # Receipt companion is complete; line shows received
    receipt = TransferReceipt.objects.get(transfer=transfer)
    assert receipt.receipt_status == "complete"
    line = transfer.lines.get()
    assert line.qty_received == 3
    # Conservation held throughout
    assert _total_qty("BC001") == 10


@pytest.mark.django_db(transaction=True)
def test_partial_receive_leaves_remainder_in_transit_flagged(scan_scaffold):
    """Short receive: scanned pieces land, the rest stays in-transit, flagged."""
    s = scan_scaffold
    transfer, c = _dispatched(s, qty=4)

    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "BC001", "qty": 3}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    assert StockOnHand.objects.get(store=s["store_a"], sku_code="BC001").net_qty == 3
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 1
    receipt = TransferReceipt.objects.get(transfer=transfer)
    assert receipt.receipt_status == "shortfall"
    assert _total_qty("BC001") == 10


@pytest.mark.django_db(transaction=True)
def test_receive_without_scans_rejected(scan_scaffold):
    s = scan_scaffold
    transfer, c = _dispatched(s, qty=3)
    resp = c.post(f"/api/outbound/transfers/{transfer.pk}/receive", {}, format="json")
    assert resp.status_code == 400
    assert not TransferReceipt.objects.filter(transfer=transfer).exists()


@pytest.mark.django_db(transaction=True)
def test_receive_over_scan_rejected(scan_scaffold):
    """Scanning more than was sent is the wrong-piece beep → 400."""
    s = scan_scaffold
    transfer, c = _dispatched(s, qty=3)
    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "BC001", "qty": 4}]},
        format="json",
    )
    assert resp.status_code == 400
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 3


@pytest.mark.django_db(transaction=True)
def test_receive_unknown_barcode_rejected(scan_scaffold):
    s = scan_scaffold
    transfer, c = _dispatched(s, qty=3)
    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "BC002", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "BC002" in str(resp.data)


# ---------------------------------------------------------------------------
# Projections: the in-transit read side + rebuildability
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_in_transit_endpoint_reports_the_third_number(scan_scaffold):
    """/api/stockledger/in-transit shows the pieces held under open transfers."""
    s = scan_scaffold
    transfer, c = _dispatched(s, qty=3)

    resp = c.get("/api/stockledger/in-transit")
    assert resp.status_code == 200
    assert resp.data["summary"]["units_in_transit"] == 3
    assert resp.data["summary"]["transfers"] == 1
    row = resp.data["rows"][0]
    assert row["transfer_doc_number"] == transfer.doc_number
    assert row["sku_code"] == "BC001"
    assert row["qty"] == 3


@pytest.mark.django_db(transaction=True)
def test_rebuild_reproduces_projections_from_ledger(scan_scaffold):
    """The projections are caches: wiping and rebuilding from the append-only
    ledger reproduces both StockOnHand and the in-transit bucket exactly."""
    from django.core.management import call_command

    s = scan_scaffold
    transfer, c = _dispatched(s, qty=4)
    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "BC001", "qty": 3}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    before_oh = sorted(
        StockOnHand.objects.values_list("store_id", "sku_code", "net_qty", "net_value_paise")
    )
    before_transit = sorted(
        InTransitStock.objects.values_list("transfer_doc_number", "sku_code", "qty")
    )
    assert before_transit == [(transfer.doc_number, "BC001", 1)]

    StockOnHand.objects.all().delete()
    InTransitStock.objects.all().delete()
    call_command("rebuild_stock_on_hand")

    after_oh = sorted(
        StockOnHand.objects.values_list("store_id", "sku_code", "net_qty", "net_value_paise")
    )
    after_transit = sorted(
        InTransitStock.objects.values_list("transfer_doc_number", "sku_code", "qty")
    )
    assert after_oh == before_oh
    assert after_transit == before_transit


# ---------------------------------------------------------------------------
# Scan lookup (per-scan validation for scan-to-build)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_scan_lookup_returns_stock_identity(scan_scaffold):
    s = scan_scaffold
    c = _client(s["user"])
    resp = c.get(f"/api/outbound/scan-lookup?store={s['warehouse'].id}&barcode=BC001")
    assert resp.status_code == 200
    assert resp.data["barcode"] == "BC001"
    assert resp.data["available_qty"] == 10
    assert resp.data["design"] == "Shirt"

    resp = c.get(f"/api/outbound/scan-lookup?store={s['warehouse'].id}&barcode=NOPE")
    assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_scan_lookup_is_store_scoped_fail_closed(scan_scaffold):
    """A store-scoped user cannot probe another store's stock — an
    out-of-scope store looks identical to no stock (ADR-0003)."""
    s = scan_scaffold
    role = make_role("store_manager", "SM (scan test)")
    sm = User.objects.create_user(
        username="scan_sm",
        password=TEST_PASSWORD,
        role=role,
        scope_type=ScopeType.STORE,
    )
    sm.stores.add(s["store_a"])  # scoped to store A only — NOT the warehouse
    c = _client(sm)

    resp = c.get(f"/api/outbound/scan-lookup?store={s['warehouse'].id}&barcode=BC001")
    assert resp.status_code == 404
