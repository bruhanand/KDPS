"""Store-scope enforcement tests for outbound write endpoints.

Verifies that store-scoped roles (store_manager) can only create/submit
outbound documents against their assigned stores, while network-scoped
roles (admin) are unrestricted.

Uses DRF's APIClient to hit the actual views (not just posting functions),
since enforce_store_scope runs in the view layer.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import Role, ScopeType, User
from core.documents import VoucherSeries
from masters.models import Brand, Gstin, LegalEntity, Store
from outbound.models import (
    ReturnToVendor,
    ReturnToVendorLine,
    StoreTransfer,
    StoreTransferLine,
)
from outbound.posting import (
    post_transfer_dispatch,
)
from stockledger.models import StockLedgerEntry, StockOnHand
from vendors.models import Vendor


@pytest.fixture()
def scope_scaffold(db):
    """Scaffold with a store-scoped manager and an all-scope admin."""
    entity = LegalEntity.objects.create(code="sc-ent", name="Scope Entity", pan="AAACS1234B")
    gstin_jh = Gstin.objects.create(
        gstin="20AAACS1234B1ZQ",
        state_code="20",
        state_name="Jharkhand",
        legal_entity=entity,
    )
    gstin_bh = Gstin.objects.create(
        gstin="10AAACS1234B1ZQ",
        state_code="10",
        state_name="Bihar",
        legal_entity=entity,
    )
    store_deo = Store.objects.create(code="SC-DEO", name="Scope DEO", gstin=gstin_jh)
    store_banka = Store.objects.create(code="SC-BNK", name="Scope Banka", gstin=gstin_bh)

    brand_owned = Brand.objects.create(
        code="sc-own",
        name="ScopeOwned",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    brand_sor = Brand.objects.create(
        code="sc-sor",
        name="ScopeSOR",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    vendor = Vendor.objects.create(name="Scope Vendor", code="scvnd")

    # Store manager: scoped to DEO only
    sm_role = make_role("store_manager", "Store Manager (scope test)")
    sm_user = User.objects.create_user(
        username="scope_sm",
        password=TEST_PASSWORD,
        role=sm_role,
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    sm_user.stores.add(store_deo)

    # Admin: all scope
    admin_role = make_role("owner", "Owner (scope test)")
    admin_user = User.objects.create_user(
        username="scope_admin",
        password=TEST_PASSWORD,
        role=admin_role,
        entity=entity,
        scope_type=ScopeType.ALL,
    )

    # Seed stock at both stores
    for store, gstin in [(store_deo, gstin_jh), (store_banka, gstin_bh)]:
        StockOnHand.objects.create(
            store=store,
            gstin=gstin,
            sku_code="SC-SKU1",
            design="Test",
            color="Red",
            size="M",
            brand="ScopeOwned",
            season="SS26",
            item="shirt",
            hsn="6205",
            net_qty=20,
            net_value_paise=20 * 10000,
        )
        StockLedgerEntry.objects.create(
            store=store,
            gstin=gstin,
            sku_code="SC-SKU1",
            design="Test",
            color="Red",
            size="M",
            brand="ScopeOwned",
            season="SS26",
            item="shirt",
            hsn="6205",
            qty=20,
            amount=20 * 10000,
            kind="pt_inward",
            doc_number="SC-SEED",
            line_no=1,
        )
        # SOR stock for V-flip tests
        StockOnHand.objects.create(
            store=store,
            gstin=gstin,
            sku_code="SC-SKU2",
            design="Tee",
            color="White",
            size="L",
            brand="ScopeSOR",
            season="SS26",
            item="tee",
            hsn="6106",
            net_qty=10,
            net_value_paise=10 * 5000,
        )
        StockLedgerEntry.objects.create(
            store=store,
            gstin=gstin,
            sku_code="SC-SKU2",
            design="Tee",
            color="White",
            size="L",
            brand="ScopeSOR",
            season="SS26",
            item="tee",
            hsn="6106",
            qty=10,
            amount=10 * 5000,
            kind="pt_inward",
            doc_number="SC-SEED2",
            line_no=1,
        )

    # VoucherSeries
    fy = "26-27"
    for code in ["SC-DEO", "SC-BNK"]:
        for dt in ["STO", "RTV", "ADJ", "WRO", "VFL"]:
            VoucherSeries.objects.create(
                fy=fy,
                store_code=code,
                doc_type=dt,
                prefix=f"{code}/{dt}/{fy}/",
                next_seq=1,
            )
    VoucherSeries.objects.get_or_create(
        fy=fy,
        store_code="HO",
        doc_type="VEND",
        defaults={"prefix": f"HO/VEND/{fy}/", "next_seq": 1},
    )

    return {
        "entity": entity,
        "gstin_jh": gstin_jh,
        "gstin_bh": gstin_bh,
        "store_deo": store_deo,
        "store_banka": store_banka,
        "brand_owned": brand_owned,
        "brand_sor": brand_sor,
        "vendor": vendor,
        "sm_user": sm_user,
        "admin_user": admin_user,
    }


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


# ---------------------------------------------------------------------------
# RTV scope tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_sm_cannot_create_rtv_outside_scope(scope_scaffold):
    """Store manager for DEO cannot create RTV against Banka."""
    s = scope_scaffold
    c = _client(s["sm_user"])
    resp = c.post(
        "/api/outbound/rtvs",
        {
            "store": s["store_banka"].id,
            "vendor": s["vendor"].id,
            "brand": s["brand_owned"].id,
            "return_type": "defective",
            "logistics_route": "warehouse",
            "lines": [{"sku_code": "SC-SKU1", "qty": 1, "unit_cost_paise": 10000}],
        },
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_sm_can_create_rtv_in_scope(scope_scaffold):
    """Store manager for DEO can create RTV against DEO."""
    s = scope_scaffold
    c = _client(s["sm_user"])
    resp = c.post(
        "/api/outbound/rtvs",
        {
            "store": s["store_deo"].id,
            "vendor": s["vendor"].id,
            "brand": s["brand_owned"].id,
            "return_type": "defective",
            "logistics_route": "warehouse",
            "lines": [{"sku_code": "SC-SKU1", "qty": 1, "unit_cost_paise": 10000}],
        },
        format="json",
    )
    assert resp.status_code == 201


@pytest.mark.django_db(transaction=True)
def test_admin_can_create_rtv_any_store(scope_scaffold):
    """Admin (all scope) can create RTV against any store."""
    s = scope_scaffold
    c = _client(s["admin_user"])
    resp = c.post(
        "/api/outbound/rtvs",
        {
            "store": s["store_banka"].id,
            "vendor": s["vendor"].id,
            "brand": s["brand_owned"].id,
            "return_type": "defective",
            "logistics_route": "warehouse",
            "lines": [{"sku_code": "SC-SKU1", "qty": 1, "unit_cost_paise": 10000}],
        },
        format="json",
    )
    assert resp.status_code == 201


@pytest.mark.django_db(transaction=True)
def test_sm_cannot_submit_rtv_outside_scope(scope_scaffold):
    """Store manager for DEO cannot submit an RTV created against Banka."""
    s = scope_scaffold
    # Admin creates draft at Banka
    rtv = ReturnToVendor.objects.create(
        store=s["store_banka"],
        vendor=s["vendor"],
        brand=s["brand_owned"],
        return_type="defective",
        created_by=s["admin_user"],
    )
    ReturnToVendorLine.objects.create(
        rtv=rtv,
        sku_code="SC-SKU1",
        qty=1,
        unit_cost_paise=10000,
    )
    c = _client(s["sm_user"])
    resp = c.post(f"/api/outbound/rtvs/{rtv.id}/submit")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Transfer scope tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_sm_cannot_create_transfer_from_outside_scope(scope_scaffold):
    """Store manager for DEO cannot create transfer FROM Banka."""
    s = scope_scaffold
    c = _client(s["sm_user"])
    resp = c.post(
        "/api/outbound/transfers",
        {
            "source_store": s["store_banka"].id,
            "destination_store": s["store_deo"].id,
            "transfer_type": "inter_store",
            "lines": [{"sku_code": "SC-SKU1", "qty_planned": 1}],
        },
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_sm_can_create_transfer_from_own_store(scope_scaffold):
    """Store manager for DEO can create transfer FROM DEO."""
    s = scope_scaffold
    c = _client(s["sm_user"])
    resp = c.post(
        "/api/outbound/transfers",
        {
            "source_store": s["store_deo"].id,
            "destination_store": s["store_banka"].id,
            "transfer_type": "inter_store",
            "lines": [{"sku_code": "SC-SKU1", "qty_planned": 1}],
        },
        format="json",
    )
    assert resp.status_code == 201


@pytest.mark.django_db(transaction=True)
def test_sm_cannot_receive_transfer_at_outside_store(scope_scaffold):
    """Store manager for DEO cannot receive transfer at Banka."""
    s = scope_scaffold
    # Create + dispatch transfer from DEO to Banka (by admin)
    transfer = StoreTransfer.objects.create(
        source_store=s["store_deo"],
        destination_store=s["store_banka"],
        transfer_type="inter_store",
        created_by=s["admin_user"],
    )
    StoreTransferLine.objects.create(
        transfer=transfer,
        sku_code="SC-SKU1",
        qty_planned=1,
    )
    post_transfer_dispatch(transfer, {"SC-SKU1": 1}, user=s["admin_user"])

    c = _client(s["sm_user"])
    resp = c.post(
        f"/api/outbound/transfers/{transfer.id}/receive",
        {"scans": [{"barcode": "SC-SKU1", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Adjustment scope tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_sm_cannot_create_adjustment_outside_scope(scope_scaffold):
    """Store manager for DEO cannot create adjustment at Banka."""
    s = scope_scaffold
    c = _client(s["sm_user"])
    resp = c.post(
        "/api/outbound/adjustments",
        {
            "store": s["store_banka"].id,
            "reason": "miscount",
            "lines": [
                {
                    "sku_code": "SC-SKU1",
                    "book_qty": 20,
                    "counted_qty": 19,
                    "adj_qty": -1,
                    "unit_cost_paise": 10000,
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# WriteOff scope tests (admin-only role, but scope still applies)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_cannot_writeoff_outside_assigned_stores(scope_scaffold):
    """If an admin-role user were store-scoped, scope blocks them.
    (In practice admins are all-scope, but the gate should still enforce.)"""
    s = scope_scaffold
    # Create a store-scoped 'owner' role user (hypothetical)
    scoped_admin = User.objects.create_user(
        username="scope_owner",
        password=TEST_PASSWORD,
        role=Role.objects.get(code="owner"),
        entity=s["entity"],
        scope_type=ScopeType.STORE,
    )
    scoped_admin.stores.add(s["store_deo"])

    c = _client(scoped_admin)
    resp = c.post(
        "/api/outbound/writeoffs",
        {
            "store": s["store_banka"].id,
            "reason": "dead_stock",
            "approved_by": scoped_admin.id,
            "lines": [{"sku_code": "SC-SKU1", "qty": 1, "unit_cost_paise": 10000}],
        },
        format="json",
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# V-Flip scope tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_can_vflip_any_store(scope_scaffold):
    """Admin (all-scope) can V-flip at any store."""
    s = scope_scaffold
    c = _client(s["admin_user"])
    resp = c.post(
        "/api/outbound/vflips",
        {
            "store": s["store_banka"].id,
            "original_brand": s["brand_sor"].id,
            "season": "SS26",
            "authorized_by": s["admin_user"].id,
            "lines": [{"sku_code": "SC-SKU2", "qty": 1, "unit_cost_paise": 5000}],
        },
        format="json",
    )
    assert resp.status_code == 201
