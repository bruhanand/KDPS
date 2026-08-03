"""Golden test: a vendor/cash ledger entry can be reversed at most once.

The review found that a bill/payment could be reversed twice — each reversal
appends another negative mirror, over-crediting the vendor. The reverse_*
services now refuse a second reversal via the `reverses` back-link. Hermetic
(db fixture), so it runs in CI's `pytest tests` step.
"""

from __future__ import annotations

import pytest
from django.db.models import Sum

from accounts.models import User
from finledger.models import VendorLedgerEntry
from finledger.posting import (
    AlreadyReversedError,
    post_vendor_bill,
    reverse_vendor_entry,
)
from vendors.models import Vendor


def _head_office_actor() -> User:
    return User.objects.create(
        username="reverse-head-office",
        full_name="Reverse Head Office",
        scope_type="all",
    )


def _balance(vendor: Vendor) -> int:
    agg = VendorLedgerEntry.objects.filter(vendor=vendor).aggregate(b=Sum("amount"))
    return agg["b"] or 0


def test_vendor_bill_reverses_once_then_refuses_a_second(db):
    vendor = Vendor.objects.create(code="v1", name="V1")
    actor = _head_office_actor()
    bill = post_vendor_bill(vendor, 10000, "bill", actor)
    assert _balance(vendor) == 10000

    rev = reverse_vendor_entry(bill, actor)
    assert rev.reverses_id == bill.id
    assert _balance(vendor) == 0  # bill + one reversal net to zero

    # A second reversal of the same bill must be refused — else balance → −10000.
    with pytest.raises(AlreadyReversedError):
        reverse_vendor_entry(bill, actor)
    assert _balance(vendor) == 0
    assert VendorLedgerEntry.objects.filter(vendor=vendor).count() == 2


def test_a_reversal_cannot_itself_be_reversed(db):
    vendor = Vendor.objects.create(code="v2", name="V2")
    actor = _head_office_actor()
    bill = post_vendor_bill(vendor, 5000, "bill", actor)
    rev = reverse_vendor_entry(bill, actor)
    with pytest.raises(AlreadyReversedError):
        reverse_vendor_entry(rev, actor)
