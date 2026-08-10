"""Money read contracts for the Vendor and Cash ledger screens (#198).

The browser formats integer paise with Indian grouping via `<Money />`. These
read endpoints keep their older rupee strings for compatibility, so callers
receive both representations of the same amount rather than having to parse
display text — sibling of `test_stock_money_payloads.py` (#155).
"""

from __future__ import annotations

import pytest
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from vendors.models import Vendor

TEST_PASSWORD = "vcmp-test-pw-1"  # noqa: S105 - test fixture only


def _books_keeper() -> User:
    return User.objects.create_user(
        username="vcmp_reader",
        password=TEST_PASSWORD,
        role=make_role("owner", "Owner (vendor/cash money payload test)"),
        scope_type=ScopeType.ALL,
    )


@pytest.mark.django_db
def test_vendor_reads_carry_paise_beside_legacy_rupee_strings():
    vendor = Vendor.objects.create(code="VCMP1", name="VCMP Vendor")
    VendorLedgerEntry.objects.create(
        vendor=vendor, amount=76_950_00, kind=VendorLedgerEntry.Kind.BILL
    )
    user = _books_keeper()

    client = APIClient()
    client.force_authenticate(user=user)

    balances = client.get("/api/finledger/vendor/balances").json()
    assert (balances["total_payable_paise"], balances["total_payable_rupees"]) == (
        76_950_00,
        "76950.00",
    )
    row = next(r for r in balances["rows"] if r["vendor_id"] == vendor.id)
    assert (row["outstanding_paise"], row["outstanding_rupees"]) == (76_950_00, "76950.00")

    ageing = client.get("/api/finledger/vendor/ageing").json()
    assert (ageing["bucket_0_30_paise"], ageing["bucket_0_30_rupees"]) == (76_950_00, "76950.00")
    ageing_row = next(r for r in ageing["rows"] if r["vendor_id"] == vendor.id)
    assert (ageing_row["bucket_0_30_paise"], ageing_row["bucket_0_30_rupees"]) == (
        76_950_00,
        "76950.00",
    )
    assert (ageing_row["total_due_paise"], ageing_row["total_due_rupees"]) == (
        76_950_00,
        "76950.00",
    )

    entries = client.get("/api/finledger/vendor/entries").json()
    entry = next(e for e in entries["results"] if e["vendor"] == vendor.id)
    assert (entry["amount"], entry["amount_rupees"]) == (76_950_00, "76950.00")


@pytest.mark.django_db
def test_cash_reads_carry_paise_beside_legacy_rupee_strings():
    CashLedgerEntry.objects.create(
        amount=52_500_00,
        kind=CashLedgerEntry.Kind.RECEIPT,
        account=CashLedgerEntry.Account.CASH,
    )
    user = _books_keeper()

    client = APIClient()
    client.force_authenticate(user=user)

    summary = client.get("/api/finledger/cash/summary").json()
    assert (summary["total_paise"], summary["total_rupees"]) == (52_500_00, "52500.00")
    account_row = next(
        a for a in summary["accounts"] if a["account"] == CashLedgerEntry.Account.CASH
    )
    assert (account_row["balance_paise"], account_row["balance_rupees"]) == (52_500_00, "52500.00")

    entries = client.get("/api/finledger/cash/entries").json()
    entry = entries["results"][0]
    assert (entry["amount"], entry["amount_rupees"]) == (52_500_00, "52500.00")
