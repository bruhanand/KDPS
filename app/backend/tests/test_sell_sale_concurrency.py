"""Two of the same bill arriving at once (#177).

The single-threaded replay test proves the *sequential* case: sync, then sync
again. This proves the case that actually breaks systems — the till's queue
retrying while the first attempt is still in flight, two tabs, a proxy that
double-delivers. Both requests reach the pipeline before either has committed,
so nothing either of them *reads* can tell them apart. What separates them is the
unique index: the loser blocks on it until the winner commits, wakes to an
integrity error, and reads back what the winner wrote.

These need real transactions and real threads, so they run against the database
rather than inside a test transaction, and they are worth the seconds they cost:
a double-billed customer is the exact defect this project exists to kill.

The projections are checked here too, against the ledger they are a cache of.
`rebuild_stock_on_hand` recomputes them from scratch, so making it agree with
what the sale wrote is how "the cache did not drift" becomes a test rather than
a hope.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from _sell import (
    SALES_URL,
    bill_payload,
    build_cashier,
    build_piece,
    build_salesman,
    build_store,
    client_for,
    stock_in,
)
from django.core.management import call_command
from django.db import connection

from sell.models import Sale, SaleLine
from stockledger.models import QuarantineStock, StockLedgerEntry, StockOnHand


def _fresh_counter():
    store = build_store()
    build_piece()
    cashier = build_cashier(store)
    return store, cashier, build_salesman(store)


def _post_in_thread(user, payload):
    """One request on its own connection, closed after — a thread that leaves a
    connection open holds a transaction the other thread is waiting on."""
    try:
        return client_for(user).post(SALES_URL, payload, format="json")
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_the_same_bill_arriving_twice_at_once_is_billed_once():
    store, cashier, salesman = _fresh_counter()
    stock_in(store, 5)
    payload = bill_payload(store, salesman, till_seq=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: _post_in_thread(cashier, payload), range(2)))

    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 201], [r.status_code for r in responses]
    # Both callers were told the same thing about the same bill.
    assert responses[0].json() == responses[1].json()
    assert Sale.objects.count() == 1
    assert SaleLine.objects.count() == 1
    # And the customer's stock moved exactly once.
    assert StockLedgerEntry.objects.filter(kind=StockLedgerEntry.Kind.SALE_OUT).count() == 1
    assert StockOnHand.objects.get(store=store, sku_code="8901000000011").net_qty == 4


@pytest.mark.django_db(transaction=True)
def test_two_different_bills_claiming_one_number_at_once_leave_only_one():
    """A mis-handover: a replacement till resumes at a number the dead one had
    already used. One bill lands, the other is refused with the contract's code -
    never two documents on one printed number."""
    store, cashier, salesman = _fresh_counter()
    stock_in(store, 5)
    payloads = [
        bill_payload(store, salesman, till_seq=9, idempotency_uuid=str(uuid.uuid4()))
        for _ in range(2)
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda p: _post_in_thread(cashier, p), payloads))

    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409], [r.status_code for r in responses]
    refused = next(r for r in responses if r.status_code == 409)
    assert refused.json()["code"] == "BILL_NO_TAKEN"
    assert Sale.objects.count() == 1
    assert StockLedgerEntry.objects.filter(kind=StockLedgerEntry.Kind.SALE_OUT).count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_projections_say_what_a_rebuild_from_the_ledger_would_say():
    """`StockOnHand` and `QuarantineStock` are caches of the append-only ledger.
    Recomputing them from scratch must not change a number."""
    store, cashier, salesman = _fresh_counter()
    stock_in(store, 5)
    client = client_for(cashier)
    first = client.post(SALES_URL, bill_payload(store, salesman, till_seq=1), format="json")
    assert first.status_code == 201
    original = Sale.objects.get(pk=first.json()["id"])

    # Give the piece back damaged, inside a second bill.
    refund = original.lines.get().net_paise
    exchange = bill_payload(store, salesman, till_seq=2)
    exchange["exchange"] = {
        "original": {"store": store.code, "fy": original.fy, "till_seq": 1},
        "lines": [
            {
                "line_no": 2,
                "barcode": "8901000000011",
                "qty": 1,
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": original.lines.get().gst_paise,
                "condition": "damaged",
                "reason": "defect",
                "original_line": 1,
            }
        ],
    }
    exchange["totals"]["net_paise"] = exchange["totals"]["net_paise"] - refund
    exchange["totals"]["gst_paise"] = (
        exchange["totals"]["gst_paise"] - original.lines.get().gst_paise
    )
    exchange["tenders"] = [{"mode": "cash", "amount_paise": exchange["totals"]["net_paise"]}]
    assert client.post(SALES_URL, exchange, format="json").status_code == 201

    before_shelf = StockOnHand.objects.get(store=store, sku_code="8901000000011").net_qty
    before_quarantine = QuarantineStock.objects.get(store=store, sku_code="8901000000011").qty

    call_command("rebuild_stock_on_hand")

    assert StockOnHand.objects.get(store=store, sku_code="8901000000011").net_qty == before_shelf
    assert (
        QuarantineStock.objects.get(store=store, sku_code="8901000000011").qty == before_quarantine
    )
    assert before_shelf == 3  # five, less two sold
    assert before_quarantine == 1
