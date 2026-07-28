"""Outbound slice 8 — the returnable pool, the live cap, and the return (#75).

Seams, one per acceptance criterion:

- **Pool seam** (``outbound.returnable``): what a brand will take back —
  confirmed quarantine plus in-window season-end stock, and never a piece of an
  Outright brand. An unconfirmed damage flag is not in it, which is the property
  that stops a store putting stock into a brand return by flagging it (#138).
- **Cap seam**: the Correction allowance, computed from the ledger, warning as
  it fills and flagging when it is crossed — never blocking (Rule 5).
- **API seam**: the return is built by scanning against the pool; an out-of-pool
  barcode is refused; the three routes are captured and the consolidated one
  must name a real, arrived transfer.
- **Ledger seam**: a quarantine line drains ``QuarantineStock``, a season-end
  line drains ``StockOnHand``, both at a cost read from the books and never zero.
- **Actor seam**: a store may not create or execute a return; the brand manager
  approves inside the band and the owner above it; a brand manager cannot touch
  another brand's return.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalStatus
from core.documents import DocStatus, VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import LogisticsRoute, ReturnSource, ReturnToVendor, ReturnType
from outbound.returnable import cap_for, returnable_pool
from stockledger.models import QuarantineStock, StockLedgerEntry, StockOnHand
from vendors.models import Vendor

FY = "26-27"

#: Everything this suite prices, in paise. One cost, so a total is readable.
UNIT_COST = 40_000

pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# Scaffold
# ---------------------------------------------------------------------------


def _brand(code: str, name: str, ownership: str, terms: str, **kwargs) -> Brand:
    return Brand.objects.create(
        code=code, name=name, ownership=ownership, return_terms=terms, **kwargs
    )


@contextmanager
def _arriving_days_ago(days: int):
    """Insert ledger rows as though they arrived ``days`` ago.

    The ledger is append-only at the database, so an arrival cannot be aged after
    the fact — the row has to be *born* old. ``created_at`` is ``auto_now_add``,
    so the only lever is the clock it reads.
    """
    with mock.patch("django.utils.timezone.now", return_value=timezone.now() - timedelta(days)):
        yield


def _stock(store, gstin, barcode, brand, qty, *, days_ago=0):
    """Seed free-to-sell stock and the arrival leg the window counts from."""
    StockOnHand.objects.update_or_create(
        store=store,
        sku_code=barcode,
        defaults={
            "gstin": gstin,
            "design": "Shirt",
            "color": "Blue",
            "size": "M",
            "brand": brand,
            "season": "SS26",
            "item": "shirt",
            "hsn": "6205",
            "net_qty": qty,
            "net_value_paise": qty * UNIT_COST,
        },
    )
    with _arriving_days_ago(days_ago):
        StockLedgerEntry.objects.create(
            store=store,
            gstin=gstin,
            sku_code=barcode,
            design="Shirt",
            color="Blue",
            size="M",
            brand=brand,
            season="SS26",
            item="shirt",
            hsn="6205",
            qty=qty,
            amount=qty * UNIT_COST,
            kind=StockLedgerEntry.Kind.PT_INWARD,
            doc_number=f"SEED-{barcode}",
            line_no=1,
        )


@pytest.fixture()
def rtb(db):
    """A warehouse holding four brands' stock: one of each commercial model."""
    entity = LegalEntity.objects.create(code="rtb-ent", name="RTB Entity", pan="AAACR1234C")
    gstin = Gstin.objects.create(
        gstin="10AAACR1234C1ZS", state_code="10", state_name="Bihar", legal_entity=entity
    )
    warehouse = Store.objects.create(
        code="RTB-WH", name="RTB Warehouse", store_type=Store.StoreType.WAREHOUSE, gstin=gstin
    )
    store = Store.objects.create(code="RTB-ST", name="RTB Store", gstin=gstin)

    brands = {
        # Correction: owned + capped → the one with an allowance.
        "correction": _brand(
            "rtb-cor",
            "CorrectionBrand",
            Brand.Ownership.OWNED,
            Brand.ReturnTerms.CAPPED,
            return_window_days=90,
            return_cap_percent=Decimal("10.00"),
        ),
        # Outright: owned, uncapped → nothing ever goes back.
        "outright": _brand(
            "rtb-out",
            "OutrightBrand",
            Brand.Ownership.OWNED,
            Brand.ReturnTerms.UNCAPPED,
            return_window_days=90,
        ),
        # SOR: brand-owned, no cap.
        "sor": _brand(
            "rtb-sor",
            "SorBrand",
            Brand.Ownership.BRAND_OWNED,
            Brand.ReturnTerms.UNCAPPED,
            return_window_days=60,
        ),
    }
    vendor = Vendor.objects.create(code="rtb-vend", name="RTB Vendor")

    for barcode, brand_name in [
        ("RTB-COR-1", "CorrectionBrand"),
        ("RTB-OUT-1", "OutrightBrand"),
        ("RTB-SOR-1", "SorBrand"),
    ]:
        sku = Sku.objects.create(
            barcode=barcode,
            design="Shirt",
            color="Blue",
            size="M",
            brand=brand_name,
            item="shirt",
            hsn="6205",
            mrp_paise=99_900,
        )
        Cohort.objects.create(
            sku=sku, barcode=barcode, season="SS26", unit_cost_paise=UNIT_COST, mrp_paise=99_900
        )
        _stock(warehouse, gstin, barcode, brand_name, 10, days_ago=10)

    for code in ["RTB-WH", "RTB-ST"]:
        for doc_type in ["RTV", "DMG", "STO"]:
            VoucherSeries.objects.create(
                fy=FY,
                store_code=code,
                doc_type=doc_type,
                prefix=f"{code}/{doc_type}/{FY}/",
                next_seq=1,
            )

    people = {
        key: User.objects.create_user(
            username=f"rtb_{role_code}",
            password=TEST_PASSWORD,
            role=make_role(role_code, role_code.title()),
            entity=entity,
            scope_type=ScopeType.ALL,
        )
        for key, role_code in [
            ("wh_user", "warehouse"),
            ("owner_user", "owner"),
            ("store_staff_user", "store_staff"),
        ]
    }
    manager = User.objects.create_user(
        username="rtb_bm",
        password=TEST_PASSWORD,
        role=make_role("brand_manager", "Brand Manager"),
        entity=entity,
        scope_type=ScopeType.BRAND,
    )
    manager.brands.set([brands["correction"], brands["sor"]])
    people["brand_manager_user"] = manager

    return {
        "gstin": gstin,
        "wh": warehouse,
        "store": store,
        "brands": brands,
        "vendor": vendor,
        **people,
    }


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _mark_damaged(rtb, barcode: str, qty: int, *, actor=None, store=None):
    store = store or rtb["wh"]
    response = _client(actor or rtb["wh_user"]).post(
        "/api/outbound/mark-damaged",
        {"store": store.id, "scans": [{"barcode": barcode, "qty": qty}]},
        format="json",
    )
    return response


def _create_return(rtb, *, actor=None, brand=None, return_type=ReturnType.DEFECTIVE, **overrides):
    payload = {
        "store": rtb["wh"].id,
        "vendor": rtb["vendor"].id,
        "brand": (brand or rtb["brands"]["correction"]).id,
        "return_type": return_type,
        "logistics_route": LogisticsRoute.STORE_PICKUP,
        "scans": [{"barcode": "RTB-COR-1", "qty": 2}],
    }
    payload.update(overrides)
    return _client(actor or rtb["wh_user"]).post("/api/outbound/rtvs", payload, format="json")


def _approve(rtb, rtv_id: int, *, actor=None):
    """Clear the return through the inbox, as the policy's approver."""
    approval = Approval.objects.filter(kind="return_to_brand", object_id=rtv_id).first()
    assert approval is not None, "a return is born asking for approval"
    response = _client(actor or rtb["owner_user"]).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    assert response.status_code == 200, response.data
    return approval


# ---------------------------------------------------------------------------
# 1. The pool — what a brand will take back
# ---------------------------------------------------------------------------


def test_pool_holds_confirmed_quarantine_and_in_window_season_end(rtb):
    """Both sources, side by side, for a brand that takes returns."""
    _mark_damaged(rtb, "RTB-COR-1", 3)

    rows = returnable_pool(rtb["wh_user"], rtb["brands"]["correction"])

    by_source = {row.source: row for row in rows}
    assert by_source[ReturnSource.QUARANTINE].qty == 3
    assert by_source[ReturnSource.SEASON_END].qty == 7  # the three left the shelf
    assert by_source[ReturnSource.QUARANTINE].unit_cost_paise == UNIT_COST
    # 90-day window, arrived 10 days ago → 80 days left, counted from arrival.
    assert by_source[ReturnSource.SEASON_END].days_left == 80


def test_outright_stock_never_appears_in_the_pool(rtb):
    """Excluded at the source, not filtered out later — even its damaged pieces.

    KDPS bought Outright stock outright; there is nothing to send back, so the
    brand has no pool at all rather than one that happens to come out empty.
    """
    _mark_damaged(rtb, "RTB-OUT-1", 2)

    assert returnable_pool(rtb["wh_user"], rtb["brands"]["outright"]) == []


def test_an_unconfirmed_damage_flag_is_not_returnable(rtb):
    """A store's report leaves the piece on the shelf, so it is not in the pool.

    This is the whole reason the pool reads ``QuarantineStock``: otherwise a
    store could put a piece into a brand return by flagging it (#138).
    """
    flagged = _mark_damaged(rtb, "RTB-COR-1", 3, actor=rtb["store_staff_user"])
    assert flagged.status_code == 201, flagged.data
    assert flagged.data["docstatus"] == DocStatus.DRAFT

    rows = returnable_pool(rtb["wh_user"], rtb["brands"]["correction"])

    assert not [row for row in rows if row.source == ReturnSource.QUARANTINE]
    assert QuarantineStock.objects.filter(sku_code="RTB-COR-1").count() == 0


def test_season_end_stock_past_its_window_is_not_offered(rtb):
    """Past the deadline the brand will not take it, so the screen never does."""
    brand = rtb["brands"]["sor"]
    brand.return_window_days = 5  # the fixture's stock arrived 10 days ago
    brand.save(update_fields=["return_window_days"])

    assert returnable_pool(rtb["wh_user"], brand) == []


def test_a_brand_with_no_negotiated_window_still_shows_its_stock(rtb):
    """Unknown is shown as unknown. Hiding the pool because nobody has typed a
    number would read as "this brand takes nothing back", a different answer."""
    brand = rtb["brands"]["sor"]
    brand.return_window_days = 0
    brand.save(update_fields=["return_window_days"])

    rows = returnable_pool(rtb["wh_user"], brand)

    assert [row.days_left for row in rows] == [None]
    assert [row.window_date for row in rows] == [None]


def test_the_pool_endpoint_says_why_an_outright_brand_is_empty(rtb):
    response = _client(rtb["wh_user"]).get(
        f"/api/outbound/returnable-pool?brand={rtb['brands']['outright'].id}"
    )

    assert response.status_code == 200, response.data
    assert response.data["rows"] == []
    assert "Outright" in response.data["excluded_reason"]
    assert response.data["brand"]["takes_returns"] is False


# ---------------------------------------------------------------------------
# 2. The cap
# ---------------------------------------------------------------------------


def test_the_cap_is_a_percentage_of_what_the_books_took_delivery_of(rtb):
    """10% of ₹4,000 delivered = ₹400 of return room, read off the ledger."""
    cap = cap_for(rtb["brands"]["correction"])

    assert cap.applies is True
    assert cap.delivered_paise == 10 * UNIT_COST
    assert cap.allowance_paise == 10 * UNIT_COST // 10
    assert cap.used_paise == 0
    assert cap.remaining_paise == 10 * UNIT_COST // 10


@pytest.mark.parametrize(
    ("commercial_model", "applies"),
    [("correction", True), ("sor", False), ("outright", False)],
)
def test_only_correction_brands_carry_a_cap(rtb, commercial_model, applies):
    """SOR and Consignment return everything unsold, so a percentage of anything
    would be an invention."""
    assert cap_for(rtb["brands"][commercial_model]).applies is applies


def test_the_cap_warns_as_it_fills_and_flags_when_it_is_crossed(rtb):
    cap = cap_for(rtb["brands"]["correction"])
    allowance = cap.allowance_paise

    assert cap.warns_at(allowance // 2) is False
    assert cap.warns_at(int(allowance * 0.9)) is True
    assert cap.exceeded_by(allowance) == 0
    assert cap.exceeded_by(allowance + 5_000) == 5_000
    # Once it is crossed the answer is the flag, not a warning about it.
    assert cap.warns_at(allowance + 5_000) is False


def test_crossing_the_cap_flags_the_return_and_never_blocks_it(rtb):
    """Rule 5. The pieces are already defective; refusing the document would only
    mean nobody records where they went."""
    brand = rtb["brands"]["correction"]
    brand.return_cap_percent = Decimal("5.00")  # ₹200 of room against a ₹800 return
    brand.save(update_fields=["return_cap_percent"])
    _mark_damaged(rtb, "RTB-COR-1", 5)

    response = _create_return(rtb, scans=[{"barcode": "RTB-COR-1", "qty": 5}])

    assert response.status_code == 201, response.data
    assert response.data["cap_exceeded_by_paise"] == 5 * UNIT_COST - (10 * UNIT_COST // 20)


def test_the_cap_is_snapshotted_onto_the_return(rtb):
    """Rule 2. The allowance moves with every arrival, so what the approver was
    shown has to be frozen, not recomputed months later."""
    _mark_damaged(rtb, "RTB-COR-1", 2)

    response = _create_return(rtb)

    assert response.data["cap_percent"] == "10.00"
    assert response.data["cap_allowance_paise"] == 10 * UNIT_COST // 10
    assert response.data["cap_used_before_paise"] == 0


# ---------------------------------------------------------------------------
# 3. Building the return by scanning
# ---------------------------------------------------------------------------


def test_a_return_is_built_from_scans_priced_by_the_server(rtb):
    _mark_damaged(rtb, "RTB-COR-1", 4)

    response = _create_return(rtb, scans=[{"barcode": "RTB-COR-1", "qty": 2}])

    assert response.status_code == 201, response.data
    line = response.data["lines"][0]
    assert line["source"] == ReturnSource.QUARANTINE
    assert line["qty"] == 2
    assert line["unit_cost_paise"] == UNIT_COST
    assert line["brand"] == "CorrectionBrand"  # dims enriched from the pool row


def test_a_piece_outside_the_pool_is_refused(rtb):
    """The wrong-piece beep, server-side. Another brand's barcode is not this
    brand's to send back, whatever the scanner did."""
    _mark_damaged(rtb, "RTB-COR-1", 2)

    response = _create_return(rtb, scans=[{"barcode": "RTB-SOR-1", "qty": 1}])

    assert response.status_code == 400
    assert "not in this brand's returnable pool" in response.data["error"]
    assert ReturnToVendor.objects.count() == 0


def test_more_pieces_than_the_pool_holds_are_refused(rtb):
    _mark_damaged(rtb, "RTB-COR-1", 2)

    response = _create_return(rtb, scans=[{"barcode": "RTB-COR-1", "qty": 3}])

    assert response.status_code == 400
    assert "the pool holds 2" in response.data["error"]


def test_a_defective_return_cannot_reach_season_end_stock(rtb):
    """The return type narrows the pool before a barcode is matched: a defect
    claim and a season-end sweep are two documents to the brand."""
    response = _create_return(rtb, scans=[{"barcode": "RTB-COR-1", "qty": 1}])

    assert response.status_code == 400
    assert "not in this brand's returnable pool" in response.data["error"]


def test_a_seasonal_return_draws_on_free_to_sell_stock(rtb):
    response = _create_return(
        rtb,
        return_type=ReturnType.SEASONAL,
        brand=rtb["brands"]["sor"],
        scans=[{"barcode": "RTB-SOR-1", "qty": 3}],
    )

    assert response.status_code == 201, response.data
    assert response.data["lines"][0]["source"] == ReturnSource.SEASON_END
    assert response.data["days_to_window"] == 50  # 60-day window, arrived 10 days ago


def test_a_return_to_an_outright_brand_is_refused_outright(rtb):
    _mark_damaged(rtb, "RTB-OUT-1", 2)

    response = _create_return(
        rtb, brand=rtb["brands"]["outright"], scans=[{"barcode": "RTB-OUT-1", "qty": 1}]
    )

    assert response.status_code == 400
    assert "outright" in response.data["error"].lower()


# ---------------------------------------------------------------------------
# 4. The three routes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", [LogisticsRoute.STORE_PICKUP, LogisticsRoute.STORE_DISPATCH])
def test_the_two_direct_routes_need_no_transfer(rtb, route):
    _mark_damaged(rtb, "RTB-COR-1", 2)

    response = _create_return(rtb, logistics_route=route)

    assert response.status_code == 201, response.data
    assert response.data["logistics_route"] == route
    assert response.data["via_transfer"] is None


def test_a_consolidated_return_must_name_the_transfer_that_brought_the_pieces(rtb):
    _mark_damaged(rtb, "RTB-COR-1", 2)

    response = _create_return(rtb, logistics_route=LogisticsRoute.WAREHOUSE_CONSOLIDATION)

    assert response.status_code == 400
    assert "store-to-warehouse transfer" in response.data["error"]


def test_a_consolidated_return_refuses_a_transfer_that_went_somewhere_else(rtb):
    """A claim with nothing behind it is how stock goes missing between two
    documents — so the transfer must actually have ended here."""
    from outbound.models import StoreTransfer

    _mark_damaged(rtb, "RTB-COR-1", 2)
    elsewhere = StoreTransfer.objects.create(
        source_store=rtb["wh"], destination_store=rtb["store"], created_by=rtb["wh_user"]
    )

    response = _create_return(
        rtb,
        logistics_route=LogisticsRoute.WAREHOUSE_CONSOLIDATION,
        via_transfer=elsewhere.id,
    )

    assert response.status_code == 400
    assert "did not arrive at RTB-WH" in response.data["error"]


# ---------------------------------------------------------------------------
# 5. The ledger — where the pieces come out of
# ---------------------------------------------------------------------------


def test_a_quarantine_line_drains_the_quarantine_bucket_not_the_shelf(rtb):
    """The pieces already left free-to-sell when the damage was confirmed;
    taking them off the shelf again would destroy stock that is not there."""
    _mark_damaged(rtb, "RTB-COR-1", 4)
    created = _create_return(rtb, scans=[{"barcode": "RTB-COR-1", "qty": 3}])
    rtv_id = created.data["id"]
    _approve(rtb, rtv_id)

    response = _client(rtb["wh_user"]).post(f"/api/outbound/rtvs/{rtv_id}/submit", {})

    assert response.status_code == 200, response.data
    assert response.data["docstatus"] == DocStatus.SUBMITTED
    # Free-to-sell untouched by the return: 10 − 4 damaged = 6.
    assert StockOnHand.objects.get(store=rtb["wh"], sku_code="RTB-COR-1").net_qty == 6
    assert QuarantineStock.objects.get(store=rtb["wh"], sku_code="RTB-COR-1").qty == 1
    leg = StockLedgerEntry.objects.get(
        doc_number=response.data["doc_number"], kind="quarantine_out"
    )
    assert leg.qty == -3
    assert leg.amount == -3 * UNIT_COST  # never zero-value (#103)


def test_returning_the_whole_bucket_clears_the_quarantine_row(rtb):
    _mark_damaged(rtb, "RTB-COR-1", 2)
    created = _create_return(rtb, scans=[{"barcode": "RTB-COR-1", "qty": 2}])
    _approve(rtb, created.data["id"])

    _client(rtb["wh_user"]).post(f"/api/outbound/rtvs/{created.data['id']}/submit", {})

    assert not QuarantineStock.objects.filter(sku_code="RTB-COR-1").exists()


def test_a_season_end_line_drains_free_to_sell(rtb):
    created = _create_return(
        rtb,
        return_type=ReturnType.SEASONAL,
        brand=rtb["brands"]["sor"],
        scans=[{"barcode": "RTB-SOR-1", "qty": 4}],
    )
    _approve(rtb, created.data["id"])

    response = _client(rtb["wh_user"]).post(f"/api/outbound/rtvs/{created.data['id']}/submit", {})

    assert response.status_code == 200, response.data
    assert StockOnHand.objects.get(store=rtb["wh"], sku_code="RTB-SOR-1").net_qty == 6
    leg = StockLedgerEntry.objects.get(doc_number=response.data["doc_number"], kind="seasonal_ret")
    assert leg.amount == -4 * UNIT_COST


def test_a_return_cannot_post_before_a_second_person_clears_it(rtb):
    """The gate is in the posting engine, so the API, a shell and a management
    command all hit the same wall."""
    _mark_damaged(rtb, "RTB-COR-1", 2)
    created = _create_return(rtb)

    response = _client(rtb["wh_user"]).post(f"/api/outbound/rtvs/{created.data['id']}/submit", {})

    assert response.status_code == 400
    assert "approval" in response.data["error"].lower()
    assert ReturnToVendor.objects.get(pk=created.data["id"]).docstatus == DocStatus.DRAFT


def test_the_used_allowance_grows_by_what_actually_posted(rtb):
    """The cap is measured against the ledger, so a draft costs nothing and a
    posted return costs exactly its value."""
    _mark_damaged(rtb, "RTB-COR-1", 2)
    created = _create_return(rtb)
    assert cap_for(rtb["brands"]["correction"]).used_paise == 0

    _approve(rtb, created.data["id"])
    _client(rtb["wh_user"]).post(f"/api/outbound/rtvs/{created.data['id']}/submit", {})

    assert cap_for(rtb["brands"]["correction"]).used_paise == 2 * UNIT_COST


# ---------------------------------------------------------------------------
# 6. Who may do what
# ---------------------------------------------------------------------------


def test_a_store_person_cannot_create_a_return(rtb):
    """The matrix puts a store and the warehouse on the same rung of this
    section — "Mark damage only" against "Create & execute" — so the refusal is
    the stored actor policy, not the capability."""
    _mark_damaged(rtb, "RTB-COR-1", 2)

    response = _create_return(rtb, actor=rtb["store_staff_user"])

    assert response.status_code == 403
    assert ReturnToVendor.objects.count() == 0


def test_a_store_person_cannot_execute_a_return_somebody_else_made(rtb):
    _mark_damaged(rtb, "RTB-COR-1", 2)
    created = _create_return(rtb)
    _approve(rtb, created.data["id"])

    response = _client(rtb["store_staff_user"]).post(
        f"/api/outbound/rtvs/{created.data['id']}/submit", {}
    )

    assert response.status_code == 403
    assert ReturnToVendor.objects.get(pk=created.data["id"]).docstatus == DocStatus.DRAFT


def test_a_brand_manager_approves_their_own_brand_inside_the_band(rtb):
    """The whole point of the brand column on the approval: without it the
    store gate scopes a brand-scoped user out of every row in the inbox."""
    _mark_damaged(rtb, "RTB-COR-1", 2)
    created = _create_return(rtb)

    inbox = _client(rtb["brand_manager_user"]).get("/api/approvals/inbox")

    assert [row["object_id"] for row in inbox.data] == [created.data["id"]]
    approval_id = inbox.data[0]["id"]
    decided = _client(rtb["brand_manager_user"]).post(
        f"/api/approvals/{approval_id}/decide", {"action": "approve"}, format="json"
    )
    assert decided.status_code == 200, decided.data
    assert decided.data["status"] == ApprovalStatus.APPROVED


def test_a_brand_manager_cannot_approve_another_brands_return(rtb):
    """Out of scope answers 404, never 403 — a 403 would confirm it exists."""
    outsider = User.objects.create_user(
        username="rtb_bm_other",
        password=TEST_PASSWORD,
        role=rtb["brand_manager_user"].role,  # the same role, a different brand
        scope_type=ScopeType.BRAND,
    )
    outsider.brands.set([rtb["brands"]["outright"]])
    _mark_damaged(rtb, "RTB-COR-1", 2)
    created = _create_return(rtb)
    approval = Approval.objects.get(kind="return_to_brand", object_id=created.data["id"])

    assert _client(outsider).get("/api/approvals/inbox").data == []
    refused = _client(outsider).post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )

    assert refused.status_code == 404


def test_a_return_above_the_band_goes_to_the_owner_alone(rtb):
    """Bands are configuration (Rule 12) — the policy row decides, not the code."""
    from approvals.models import ApprovalPolicy

    policy = ApprovalPolicy.objects.get(kind="return_to_brand")
    policy.band_paise = 1_000  # ₹10, so a ₹800 return is above it
    policy.save(update_fields=["band_paise"])
    _mark_damaged(rtb, "RTB-COR-1", 2)

    created = _create_return(rtb)

    approval = Approval.objects.get(kind="return_to_brand", object_id=created.data["id"])
    assert approval.approver_roles == ["owner"]
    assert _client(rtb["brand_manager_user"]).get("/api/approvals/inbox").data == []


# ---------------------------------------------------------------------------
# 7. The credit note
# ---------------------------------------------------------------------------


def test_the_credit_note_is_recorded_against_a_posted_return(rtb):
    _mark_damaged(rtb, "RTB-COR-1", 2)
    created = _create_return(rtb)
    _approve(rtb, created.data["id"])
    _client(rtb["wh_user"]).post(f"/api/outbound/rtvs/{created.data['id']}/submit", {})

    response = _client(rtb["wh_user"]).post(
        f"/api/outbound/rtvs/{created.data['id']}/credit-note",
        {"received_on": "2026-08-01", "reference": "CN-7"},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["credit_note"]["received_on"] == "2026-08-01"
    assert response.data["credit_note"]["reference"] == "CN-7"
    # Recorded against the frozen document without touching it (Rule 1).
    assert response.data["docstatus"] == DocStatus.SUBMITTED


def test_a_credit_note_cannot_be_recorded_against_a_draft(rtb):
    """A credit note answers a return that has actually gone back."""
    _mark_damaged(rtb, "RTB-COR-1", 2)
    created = _create_return(rtb)

    response = _client(rtb["wh_user"]).post(
        f"/api/outbound/rtvs/{created.data['id']}/credit-note",
        {"received_on": "2026-08-01"},
        format="json",
    )

    assert response.status_code == 400
