"""Unit tests for masters.scoping — covering visible_store_ids, scoped_stores,
and scope_by_store with various user scope types."""

from __future__ import annotations

import pytest

from accounts.models import ScopeType, User
from masters.models import Gstin, LegalEntity, Store
from masters.scoping import scope_by_store, scoped_stores, visible_store_ids
from stockledger.models import StockLedgerEntry


@pytest.fixture
def _hierarchy(db):
    """Two entities, two GSTINs, four stores."""
    entity1 = LegalEntity.objects.create(code="kdps", name="KDPS Lifestyle")
    entity2 = LegalEntity.objects.create(code="other", name="Other Co")
    gstin_bihar = Gstin.objects.create(
        legal_entity=entity1, gstin="10AABCK1234A1Z5", state_code="10", state_name="Bihar"
    )
    gstin_jhk = Gstin.objects.create(
        legal_entity=entity1, gstin="20AABCK1234A1Z1", state_code="20", state_name="Jharkhand"
    )
    gstin_other = Gstin.objects.create(
        legal_entity=entity2, gstin="07BBBBB9999B9Z9", state_code="07", state_name="Delhi"
    )
    store_deo = Store.objects.create(code="DEO", name="Deoghar", gstin=gstin_bihar)
    store_pat = Store.objects.create(code="PAT", name="Patna", gstin=gstin_bihar)
    store_ran = Store.objects.create(code="RAN", name="Ranchi", gstin=gstin_jhk)
    store_del = Store.objects.create(code="DEL", name="Delhi", gstin=gstin_other)
    return {
        "entity1": entity1,
        "entity2": entity2,
        "gstin_bihar": gstin_bihar,
        "gstin_jhk": gstin_jhk,
        "gstin_other": gstin_other,
        "store_deo": store_deo,
        "store_pat": store_pat,
        "store_ran": store_ran,
        "store_del": store_del,
    }


@pytest.mark.django_db
class TestVisibleStoreIds:
    def test_superuser_sees_all(self, _hierarchy):
        user = User.objects.create_superuser(username="su", password="Su@12345")
        assert visible_store_ids(user) is None

    def test_all_scope_sees_all(self, _hierarchy):
        user = User.objects.create_user(username="all_u", password="All@12345")
        user.scope_type = ScopeType.ALL
        user.save()
        assert visible_store_ids(user) is None

    def test_entity_scope(self, _hierarchy):
        user = User.objects.create_user(username="entity_u", password="Entity@12345")
        user.scope_type = ScopeType.ENTITY
        user.entity = _hierarchy["entity1"]
        user.save()
        ids = visible_store_ids(user)
        # entity1 has stores in Bihar (DEO, PAT) and Jharkhand (RAN)
        assert set(ids) == {
            _hierarchy["store_deo"].pk,
            _hierarchy["store_pat"].pk,
            _hierarchy["store_ran"].pk,
        }

    def test_store_scope(self, _hierarchy):
        user = User.objects.create_user(username="store_u", password="Store@12345")
        user.scope_type = ScopeType.STORE
        user.save()
        user.stores.add(_hierarchy["store_deo"])
        ids = visible_store_ids(user)
        assert ids == [_hierarchy["store_deo"].pk]

    def test_store_scope_no_stores_assigned(self, _hierarchy):
        user = User.objects.create_user(username="empty_u", password="Empty@12345")
        user.scope_type = ScopeType.STORE
        user.save()
        ids = visible_store_ids(user)
        assert ids == []


@pytest.mark.django_db
class TestScopedStores:
    def test_all_scope_returns_all_active(self, _hierarchy):
        user = User.objects.create_user(username="all_s", password="All@12345")
        user.scope_type = ScopeType.ALL
        user.save()
        qs = scoped_stores(user)
        assert qs.count() == 4

    def test_store_scope_returns_assigned(self, _hierarchy):
        user = User.objects.create_user(username="sc_s", password="Sc@12345")
        user.scope_type = ScopeType.STORE
        user.save()
        user.stores.add(_hierarchy["store_deo"], _hierarchy["store_ran"])
        qs = scoped_stores(user)
        codes = set(qs.values_list("code", flat=True))
        assert codes == {"DEO", "RAN"}


@pytest.mark.django_db(transaction=True)
class TestScopeByStore:
    def test_filters_queryset(self, _hierarchy):
        user = User.objects.create_user(username="fb_u", password="Fb@12345")
        user.scope_type = ScopeType.STORE
        user.save()
        user.stores.add(_hierarchy["store_deo"])
        # Create entries in two stores
        StockLedgerEntry.objects.create(
            store=_hierarchy["store_deo"],
            gstin=_hierarchy["gstin_bihar"],
            sku_code="X1",
            qty=1,
            amount=100,
            kind="pt_inward",
            doc_number="D1",
        )
        StockLedgerEntry.objects.create(
            store=_hierarchy["store_pat"],
            gstin=_hierarchy["gstin_bihar"],
            sku_code="X2",
            qty=1,
            amount=100,
            kind="pt_inward",
            doc_number="D2",
        )
        filtered = scope_by_store(StockLedgerEntry.objects.all(), user, "store_id")
        assert filtered.count() == 1
        assert filtered.first().sku_code == "X1"

    def test_superuser_gets_all(self, _hierarchy):
        user = User.objects.create_superuser(username="su2", password="Su@12345")
        StockLedgerEntry.objects.create(
            store=_hierarchy["store_deo"],
            gstin=_hierarchy["gstin_bihar"],
            sku_code="Y1",
            qty=1,
            amount=100,
            kind="pt_inward",
            doc_number="E1",
        )
        StockLedgerEntry.objects.create(
            store=_hierarchy["store_ran"],
            gstin=_hierarchy["gstin_jhk"],
            sku_code="Y2",
            qty=1,
            amount=100,
            kind="pt_inward",
            doc_number="E2",
        )
        filtered = scope_by_store(StockLedgerEntry.objects.all(), user, "store_id")
        assert filtered.count() == 2
