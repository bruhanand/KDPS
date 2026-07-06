"""Unit tests for stockledger.views — covering stock ledger list, summary, and
stock-on-hand views with store scoping."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, ScopeType, User
from masters.models import Gstin, LegalEntity, Store
from stockledger.models import StockLedgerEntry, StockOnHand


@pytest.fixture
def _store_tree(db):
    """Create legal entity → GSTIN → two stores."""
    entity = LegalEntity.objects.create(code="kdps", name="KDPS Lifestyle")
    gstin = Gstin.objects.create(
        legal_entity=entity, gstin="10AABCK1234A1Z5", state_code="10", state_name="Bihar"
    )
    store1 = Store.objects.create(code="DEO", name="Deoghar", gstin=gstin)
    store2 = Store.objects.create(code="BKR", name="Bokaro", gstin=gstin)
    return {"entity": entity, "gstin": gstin, "store1": store1, "store2": store2}


@pytest.fixture
def all_scope_user(db):
    """A user who can see all stores."""
    user = User.objects.create_user(username="alluser", password="All@Pass123")
    user.scope_type = ScopeType.ALL
    user.save()
    return user


@pytest.fixture
def store_scoped_user(db, _store_tree):
    """A user scoped to store1 only."""
    user = User.objects.create_user(username="storeuser", password="Store@Pass123")
    user.scope_type = ScopeType.STORE
    user.save()
    user.stores.add(_store_tree["store1"])
    return user


@pytest.fixture
def all_client(all_scope_user):
    client = APIClient()
    client.force_authenticate(user=all_scope_user)
    return client


@pytest.fixture
def store_client(store_scoped_user):
    client = APIClient()
    client.force_authenticate(user=store_scoped_user)
    return client


def _seed_stock_entries(store, gstin):
    """Insert stock ledger entries + stock-on-hand rows for testing."""
    StockLedgerEntry.objects.create(
        store=store,
        gstin=gstin,
        sku_code="BC001",
        design="Design-A",
        color="Red",
        size="M",
        brand="Mufti",
        season="SS26",
        item="Shirt",
        qty=10,
        amount=1500000,
        kind=StockLedgerEntry.Kind.PT_INWARD,
        doc_number="PT/DEO/26-27/0001",
    )
    StockLedgerEntry.objects.create(
        store=store,
        gstin=gstin,
        sku_code="BC002",
        design="Design-B",
        color="Blue",
        size="L",
        brand="Mufti",
        season="SS26",
        item="Jeans",
        qty=5,
        amount=1000000,
        kind=StockLedgerEntry.Kind.PT_INWARD,
        doc_number="PT/DEO/26-27/0002",
    )
    StockOnHand.objects.create(
        store=store,
        gstin=gstin,
        sku_code="BC001",
        design="Design-A",
        color="Red",
        size="M",
        brand="Mufti",
        season="SS26",
        item="Shirt",
        net_qty=10,
        net_value_paise=1500000,
    )
    StockOnHand.objects.create(
        store=store,
        gstin=gstin,
        sku_code="BC002",
        design="Design-B",
        color="Blue",
        size="L",
        brand="Mufti",
        season="SS26",
        item="Jeans",
        net_qty=5,
        net_value_paise=1000000,
    )


# --- StockLedgerListView -------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestStockLedgerListView:
    def test_list_entries(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/entries")
        assert resp.status_code == 200
        assert resp.data["count"] == 2

    def test_filter_by_doc_number(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/entries?doc_number=PT/DEO/26-27/0001")
        assert resp.status_code == 200
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["sku_code"] == "BC001"

    def test_store_scoping(self, store_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        _seed_stock_entries(_store_tree["store2"], _store_tree["gstin"])
        resp = store_client.get("/api/stockledger/entries")
        assert resp.status_code == 200
        # Store-scoped user sees only store1 entries
        assert resp.data["count"] == 2

    def test_unauthenticated_blocked(self, _store_tree):
        client = APIClient()
        resp = client.get("/api/stockledger/entries")
        assert resp.status_code == 401


# --- StockLedgerSummaryView ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestStockLedgerSummaryView:
    def test_empty_summary(self, all_client):
        resp = all_client.get("/api/stockledger/summary")
        assert resp.status_code == 200
        assert resp.data["entries"] == 0
        assert resp.data["net_qty"] == 0

    def test_summary_with_data(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/summary")
        assert resp.status_code == 200
        assert resp.data["entries"] == 2
        assert resp.data["net_qty"] == 15
        assert resp.data["net_value_paise"] == 2500000
        assert resp.data["distinct_skus"] == 2

    def test_scoped_summary(self, store_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        _seed_stock_entries(_store_tree["store2"], _store_tree["gstin"])
        resp = store_client.get("/api/stockledger/summary")
        assert resp.status_code == 200
        # Store-scoped user sees only store1
        assert resp.data["entries"] == 2
        assert resp.data["net_qty"] == 15


# --- StockOnHandView -----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestStockOnHandView:
    def test_default_sku_grouping(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/on-hand")
        assert resp.status_code == 200
        assert resp.data["group_by"] == "sku"
        assert resp.data["summary"]["units_on_hand"] == 15
        assert resp.data["summary"]["lines"] == 2
        assert len(resp.data["rows"]) == 2

    def test_brand_grouping(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/on-hand?group_by=brand")
        assert resp.status_code == 200
        assert resp.data["group_by"] == "brand"
        # Both SKUs are same brand so one group
        assert len(resp.data["rows"]) == 1
        assert resp.data["rows"][0]["brand"] == "Mufti"

    def test_store_grouping(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/on-hand?group_by=store")
        assert resp.status_code == 200
        assert resp.data["group_by"] == "store"
        assert len(resp.data["rows"]) == 1
        assert resp.data["rows"][0]["store_code"] == "DEO"

    def test_invalid_group_by_defaults_to_sku(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/on-hand?group_by=invalid")
        assert resp.status_code == 200
        assert resp.data["group_by"] == "sku"

    def test_filter_by_store(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        _seed_stock_entries(_store_tree["store2"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/on-hand?store=DEO")
        assert resp.status_code == 200
        assert resp.data["summary"]["units_on_hand"] == 15

    def test_filter_by_brand(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/on-hand?brand=Mufti")
        assert resp.status_code == 200
        assert resp.data["summary"]["units_on_hand"] == 15
        # Non-matching brand
        resp2 = all_client.get("/api/stockledger/on-hand?brand=NoSuchBrand")
        assert resp2.data["summary"]["units_on_hand"] == 0

    def test_store_scoping_on_hand(self, store_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        _seed_stock_entries(_store_tree["store2"], _store_tree["gstin"])
        resp = store_client.get("/api/stockledger/on-hand")
        assert resp.status_code == 200
        # Store-scoped user sees only store1
        assert resp.data["summary"]["units_on_hand"] == 15

    def test_truncation_flag(self, all_client, _store_tree):
        _seed_stock_entries(_store_tree["store1"], _store_tree["gstin"])
        resp = all_client.get("/api/stockledger/on-hand")
        assert resp.status_code == 200
        # 2 rows < MAX_LINES, so not truncated
        assert resp.data["summary"]["truncated"] is False
