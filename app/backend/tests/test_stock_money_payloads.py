"""Money read contracts for the Stock screens (#155).

The browser formats integer paise with Indian grouping.  These read endpoints
also keep their older rupee strings for compatibility, so callers receive both
representations of the same amount rather than having to parse display text.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from masters.models import Gstin, LegalEntity, Store
from stockledger.models import QuarantineStock, StockLedgerEntry, StockOnHand


@pytest.mark.django_db
def test_stock_reads_carry_paise_beside_legacy_rupee_strings():
    entity = LegalEntity.objects.create(code="stock-money", name="Stock Money", pan="AAACS1550A")
    gstin = Gstin.objects.create(
        legal_entity=entity,
        gstin="20AAACS1550A1Z7",
        state_code="20",
        state_name="Jharkhand",
    )
    store = Store.objects.create(code="SM155", name="Stock Money Store", gstin=gstin)
    user = User.objects.create_user(
        username="stock_money_reader",
        scope_type=ScopeType.ALL,
        entity=entity,
    )
    amount_paise = 12_595_000
    dimensions = {
        "store": store,
        "gstin": gstin,
        "sku_code": "SM155-BAR",
        "design": "SHIRT155",
        "color": "Blue",
        "size": "M",
        "brand": "StockBrand",
        "season": "SS26",
        "item": "shirt",
        "hsn": "6205",
    }
    StockLedgerEntry.objects.create(
        **dimensions,
        qty=1,
        amount=amount_paise,
        kind=StockLedgerEntry.Kind.PT_INWARD,
        doc_number="26-27/SM155/PT/1",
        line_no=1,
    )
    StockOnHand.objects.create(**dimensions, net_qty=1, net_value_paise=amount_paise)
    QuarantineStock.objects.create(**dimensions, qty=1, value_paise=amount_paise)

    client = APIClient()
    client.force_authenticate(user=user)

    ledger = client.get("/api/stockledger/summary").json()
    assert (ledger["net_value_paise"], ledger["net_value_rupees"]) == (
        amount_paise,
        "125950.00",
    )

    on_hand = client.get("/api/stockledger/on-hand?group_by=sku").json()
    assert (on_hand["summary"]["value_paise"], on_hand["summary"]["value_rupees"]) == (
        amount_paise,
        "125950.00",
    )
    assert (on_hand["rows"][0]["net_value_paise"], on_hand["rows"][0]["net_value_rupees"]) == (
        amount_paise,
        "125950.00",
    )

    quarantine = client.get("/api/stockledger/quarantine").json()
    assert (
        quarantine["summary"]["value_paise"],
        quarantine["summary"]["value_rupees"],
    ) == (amount_paise, "125950.00")
    assert (
        quarantine["rows"][0]["value_paise"],
        quarantine["rows"][0]["value_rupees"],
    ) == (amount_paise, "125950.00")
