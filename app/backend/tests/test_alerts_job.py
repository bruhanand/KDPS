"""Outbound slice 9 — the alerts job: in-transit aging + return-window 30/15/7
(#77).

Seams:

- **Check seam** (``alerts.checks``): a dispatched transfer not received past
  the configured aging threshold; a season-end holding inside a brand's
  negotiated window at 30/15/7 days left. Confirmed-damage never has a window
  and an Outright brand never has a pool, so neither ever fires this alert.
- **Sync seam**: the daily job is idempotent — re-running it the same day
  never doubles an alert still open, and it resolves an alert the moment its
  condition stops being true (received; stock leaves the pool).
- **API seam**: ``GET /api/alerts`` is scoped exactly like the approvals inbox
  (ADR-0003) — a store-scoped user sees their own store's, a brand-scoped user
  sees their own brands', HO sees the network.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _transfers import approve_transfer
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from alerts.checks import check_in_transit_aging, check_return_window, run_alert_checks
from alerts.models import Alert, AlertKind, AlertStatus
from core.documents import VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import StoreTransfer, StoreTransferLine
from stockledger.models import QuarantineStock, StockLedgerEntry, StockOnHand

FY = "26-27"
UNIT_COST = 40_000

pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# Scaffold
# ---------------------------------------------------------------------------


@contextmanager
def _days_ago(days: int):
    """Insert a row as though it was born ``days`` ago — the arrival ledger is
    append-only, so an arrival cannot be aged after the fact."""
    with mock.patch("django.utils.timezone.now", return_value=timezone.now() - timedelta(days)):
        yield


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture()
def alerts_scaffold(db):
    entity = LegalEntity.objects.create(code="al-ent", name="Alerts Entity", pan="AAACA1234C")
    gstin = Gstin.objects.create(
        gstin="10AAACA1234C1ZS", state_code="10", state_name="Bihar", legal_entity=entity
    )
    warehouse = Store.objects.create(
        code="AL-WH", name="Alerts Warehouse", store_type=Store.StoreType.WAREHOUSE, gstin=gstin
    )
    store = Store.objects.create(code="AL-A", name="Alerts Store A", gstin=gstin)
    other_store = Store.objects.create(code="AL-B", name="Alerts Store B", gstin=gstin)

    for code in ["AL-WH", "AL-A", "AL-B"]:
        VoucherSeries.objects.create(
            fy=FY, store_code=code, doc_type="STO", prefix=f"{code}/STO/{FY}/"
        )

    ho = make_role("ho_ops", "HO Ops (alerts test)")
    manager = make_role("store_manager", "Store manager (alerts test)")
    brand_manager_role = make_role("brand_manager", "Brand manager (alerts test)")

    def _user(username, role, scope=ScopeType.ALL, stores=(), brands=()):
        u = User.objects.create_user(
            username=username, password=TEST_PASSWORD, role=role, entity=entity, scope_type=scope
        )
        for s in stores:
            u.stores.add(s)
        for b in brands:
            u.brands.add(b)
        return u

    maker = _user("al_maker", ho)
    ho_user = _user("al_ho", ho)
    store_user = _user("al_store_user", manager, ScopeType.STORE, [store])
    other_store_user = _user("al_other_store_user", manager, ScopeType.STORE, [other_store])

    sor_brand = Brand.objects.create(
        code="al-sor",
        name="AlSorBrand",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
        return_window_days=40,
    )
    outright_brand = Brand.objects.create(
        code="al-out",
        name="AlOutrightBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
        return_window_days=40,
    )
    brand_manager = _user(
        "al_brand_manager", brand_manager_role, ScopeType.BRAND, brands=[sor_brand]
    )

    # A plain owned-brand item at the warehouse, to dispatch on the aging tests
    # — its own commercial model plays no part in that check.
    transit_brand = Brand.objects.create(
        code="al-transit",
        name="AlTransitBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    sku = Sku.objects.create(
        barcode="AL001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="AlTransitBrand",
        item="shirt",
        hsn="6205",
        mrp_paise=99900,
    )
    Cohort.objects.create(
        sku=sku, barcode="AL001", season="SS26", unit_cost_paise=UNIT_COST, mrp_paise=99900
    )
    StockOnHand.objects.create(
        store=warehouse,
        gstin=gstin,
        sku_code="AL001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="AlTransitBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        net_qty=20,
        net_value_paise=20 * UNIT_COST,
    )
    StockLedgerEntry.objects.create(
        store=warehouse,
        gstin=gstin,
        sku_code="AL001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="AlTransitBrand",
        season="SS26",
        item="shirt",
        hsn="6205",
        qty=20,
        amount=20 * UNIT_COST,
        kind=StockLedgerEntry.Kind.PT_INWARD,
        doc_number="AL-SEED",
        line_no=1,
    )

    return {
        "transit_brand": transit_brand,
        "entity": entity,
        "gstin": gstin,
        "warehouse": warehouse,
        "store": store,
        "other_store": other_store,
        "maker": maker,
        "ho_user": ho_user,
        "store_user": store_user,
        "other_store_user": other_store_user,
        "sor_brand": sor_brand,
        "outright_brand": outright_brand,
        "brand_manager": brand_manager,
    }


def _dispatch(s, *, destination=None, plan=(("AL001", 4),), dispatched_days_ago: int = 0):
    """A submitted warehouse→store transfer with everything scanned out,
    dispatched ``dispatched_days_ago`` days ago.

    A submitted document is DB-immutable (the ``kdps_document_fsm`` trigger
    refuses any further update), so ``dispatch_date`` cannot be backdated after
    the fact — it has to be born old, the same way ``_days_ago`` backdates a
    ledger arrival: mock the clock for the dispatch call itself.
    """
    transfer = StoreTransfer.objects.create(
        source_store=s["warehouse"],
        destination_store=destination or s["store"],
        transfer_type="store_split",
        created_by=s["maker"],
    )
    for barcode, qty in plan:
        StoreTransferLine.objects.create(transfer=transfer, sku_code=barcode, qty_planned=qty)
    approve_transfer(transfer)
    with _days_ago(dispatched_days_ago):
        resp = _client(s["maker"]).post(
            f"/api/outbound/transfers/{transfer.pk}/dispatch",
            {"scans": [{"barcode": b, "qty": q} for b, q in plan]},
            format="json",
        )
    assert resp.status_code == 200, resp.data
    transfer.refresh_from_db()
    return transfer


def _receive(s, transfer, plan=(("AL001", 4),)):
    resp = _client(s["store_user"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": b, "qty": q} for b, q in plan], "notes": ""},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    return resp


def _stock(store, gstin, barcode, brand, qty, *, days_ago=0):
    """Free-to-sell season-end stock, plus the arrival leg the window counts
    from — mirrors the returnable-pool fixture in test_outbound_return_to_brand."""
    StockOnHand.objects.update_or_create(
        store=store,
        sku_code=barcode,
        defaults={
            "gstin": gstin,
            "design": "Blazer",
            "color": "Grey",
            "size": "40",
            "brand": brand,
            "season": "SS26",
            "item": "blazer",
            "hsn": "6203",
            "net_qty": qty,
            "net_value_paise": qty * UNIT_COST,
        },
    )
    with _days_ago(days_ago):
        StockLedgerEntry.objects.create(
            store=store,
            gstin=gstin,
            sku_code=barcode,
            design="Blazer",
            color="Grey",
            size="40",
            brand=brand,
            season="SS26",
            item="blazer",
            hsn="6203",
            qty=qty,
            amount=qty * UNIT_COST,
            kind=StockLedgerEntry.Kind.PT_INWARD,
            doc_number=f"SEED-{barcode}",
            line_no=1,
        )


# ---------------------------------------------------------------------------
# In-transit aging
# ---------------------------------------------------------------------------


def test_overdue_transfer_is_flagged(alerts_scaffold):
    s = alerts_scaffold
    transfer = _dispatch(s, dispatched_days_ago=5)  # policy default is 3 days

    hits = check_in_transit_aging(timezone.localdate())

    assert len(hits) == 1
    assert hits[0].dedupe_key == f"transfer:{transfer.id}"
    assert hits[0].store_id == s["store"].id
    assert hits[0].object_id == transfer.id


def test_transfer_within_the_window_is_not_flagged(alerts_scaffold):
    s = alerts_scaffold
    _dispatch(s, dispatched_days_ago=1)  # under the 3-day default

    assert check_in_transit_aging(timezone.localdate()) == []


def test_received_transfer_is_never_flagged(alerts_scaffold):
    s = alerts_scaffold
    transfer = _dispatch(s, dispatched_days_ago=5)
    _receive(s, transfer)

    assert check_in_transit_aging(timezone.localdate()) == []


def test_aging_job_is_idempotent_and_resolves_on_receipt(alerts_scaffold):
    s = alerts_scaffold
    transfer = _dispatch(s, dispatched_days_ago=5)

    run_alert_checks()
    run_alert_checks()  # a same-day re-run must not double the alert

    open_alerts = Alert.objects.filter(kind=AlertKind.IN_TRANSIT_AGING, status=AlertStatus.OPEN)
    assert open_alerts.count() == 1
    alert = open_alerts.get()
    assert alert.dedupe_key == f"transfer:{transfer.id}"
    assert alert.store_id == s["store"].id

    _receive(s, transfer)
    run_alert_checks()

    alert.refresh_from_db()
    assert alert.status == AlertStatus.RESOLVED
    assert alert.resolved_at is not None
    still_open = Alert.objects.filter(kind=AlertKind.IN_TRANSIT_AGING, status=AlertStatus.OPEN)
    assert not still_open.exists()


# ---------------------------------------------------------------------------
# Return-window countdown
# ---------------------------------------------------------------------------


def test_no_alert_before_any_threshold(alerts_scaffold):
    s = alerts_scaffold
    # 40-day window, arrived 5 days ago → 35 days left, below no threshold.
    _stock(s["warehouse"], s["gstin"], "AL-SOR-1", "AlSorBrand", 6, days_ago=5)

    assert check_return_window(timezone.localdate()) == []


def test_crossing_a_threshold_fires_exactly_that_alert(alerts_scaffold):
    s = alerts_scaffold
    # 40-day window, arrived 10 days ago → 30 days left, crossing only the
    # loosest threshold.
    _stock(s["warehouse"], s["gstin"], "AL-SOR-1", "AlSorBrand", 6, days_ago=10)

    hits = check_return_window(timezone.localdate())

    assert len(hits) == 1
    assert hits[0].threshold_days == 30
    assert hits[0].store_id == s["warehouse"].id
    assert hits[0].brand == "AlSorBrand"


def test_catching_up_fires_every_threshold_already_crossed(alerts_scaffold):
    s = alerts_scaffold
    # 40-day window, arrived 33 days ago → 7 days left: 30, 15 and 7 are all
    # already crossed (a first-ever run, or a job that missed a few days).
    _stock(s["warehouse"], s["gstin"], "AL-SOR-1", "AlSorBrand", 6, days_ago=33)

    hits = check_return_window(timezone.localdate())

    assert sorted(h.threshold_days for h in hits) == [7, 15, 30]


def test_quarantine_and_outright_never_fire_this_alert(alerts_scaffold):
    s = alerts_scaffold
    # Confirmed-damage stock: no window, so it never crosses a threshold.
    QuarantineStock.objects.create(
        store=s["warehouse"],
        gstin=s["gstin"],
        sku_code="AL-SOR-DMG",
        design="Blazer",
        color="Grey",
        size="40",
        brand="AlSorBrand",
        season="SS26",
        qty=3,
        value_paise=3 * UNIT_COST,
    )
    # Outright stock: no pool at all, however old.
    _stock(s["warehouse"], s["gstin"], "AL-OUT-1", "AlOutrightBrand", 6, days_ago=39)

    assert check_return_window(timezone.localdate()) == []


def test_return_window_job_is_idempotent_and_resolves_when_stock_leaves_the_pool(alerts_scaffold):
    s = alerts_scaffold
    _stock(s["warehouse"], s["gstin"], "AL-SOR-1", "AlSorBrand", 6, days_ago=10)  # 30 left

    run_alert_checks()
    run_alert_checks()  # same-day re-run

    open_alerts = Alert.objects.filter(kind=AlertKind.RETURN_WINDOW, status=AlertStatus.OPEN)
    assert open_alerts.count() == 1
    alert = open_alerts.get()
    assert alert.threshold_days == 30
    assert alert.brand == "AlSorBrand"

    # The holding leaves the pool (sold off, or returned) — nothing left to warn about.
    StockOnHand.objects.filter(store=s["warehouse"], sku_code="AL-SOR-1").update(net_qty=0)
    run_alert_checks()

    alert.refresh_from_db()
    assert alert.status == AlertStatus.RESOLVED


# ---------------------------------------------------------------------------
# API scoping
# ---------------------------------------------------------------------------


def test_inbox_scopes_aging_alert_to_the_destination_store(alerts_scaffold):
    s = alerts_scaffold
    _dispatch(s, dispatched_days_ago=5)
    run_alert_checks()

    mine = _client(s["store_user"]).get("/api/alerts")
    assert mine.status_code == 200
    assert len(mine.data) == 1

    not_mine = _client(s["other_store_user"]).get("/api/alerts")
    assert not_mine.status_code == 200
    assert len(not_mine.data) == 0

    everyone = _client(s["ho_user"]).get("/api/alerts")
    assert everyone.status_code == 200
    assert len(everyone.data) == 1


def test_inbox_scopes_return_window_alert_to_its_brand_manager(alerts_scaffold):
    s = alerts_scaffold
    _stock(s["warehouse"], s["gstin"], "AL-SOR-1", "AlSorBrand", 6, days_ago=10)
    run_alert_checks()

    mine = _client(s["brand_manager"]).get("/api/alerts")
    assert mine.status_code == 200
    assert len(mine.data) == 1
    assert mine.data[0]["brand"] == "AlSorBrand"

    # An aging alert carries no brand, so a brand-scoped user never sees one —
    # "stores are the wrong question for them" (masters.scoping), never read
    # as "so show them everything".
    _dispatch(s, dispatched_days_ago=5)
    run_alert_checks()
    still_mine = _client(s["brand_manager"]).get("/api/alerts")
    assert len(still_mine.data) == 1
