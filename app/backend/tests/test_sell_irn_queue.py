"""Head office's IRN queue (#187, grill Q8, api-contract step 11).

Above the e-invoice threshold every GSTIN-bearing counter sale must carry an IRN
within thirty days or it is invalid and the customer loses their input credit.
The store cannot raise one, so the queue exists to make sure somebody at head
office does - which is what the suite is organised around:

  · **A B2B bill lands on it, at billed_at + 30 days, and a B2C bill does not.**
  · **It is head office's, not the shop's.** The gate is `money: manage`, so a
    cashier - who may bill all day - cannot reach it, and an accountant, who may
    not bill at all, can.
  · **A raised IRN is recorded once.** A second one silently replacing the first
    would leave two documents claiming to be this bill.
"""

from __future__ import annotations

import pytest
from _sell import (
    FY,
    SALES_URL,
    bill_payload,
    build_accountant,
    build_cashier,
    build_piece,
    build_salesman,
    build_store,
    client_for,
    stock_in,
)

from sell.models import IrnQueueItem, Sale

QUEUE_URL = "/api/sell/irn-queue"

#: Well formed, and Bihar - the same state the fixture store is registered in.
BIHAR_BUYER = "10AABCU9603R1Z2"


@pytest.fixture
def counter(db):
    store = build_store()
    build_piece()
    cashier = build_cashier(store)
    stock_in(store, qty=5)
    return {
        "store": store,
        "cashier": cashier,
        "salesman": build_salesman(store),
        "client": client_for(cashier),
    }


def _bill(counter, *, till_seq: int, gstin: str = BIHAR_BUYER, billed_at: str | None = None):
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq)
    payload["customer"]["gstin"] = gstin
    if billed_at:
        payload["billed_at"] = billed_at
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    return Sale.objects.get(till_seq=till_seq, fy=FY)


def _queue(user, **params):
    return client_for(user).get(QUEUE_URL, params)


# --- what lands on it ------------------------------------------------------


def test_a_b2b_bill_lands_on_the_queue_with_a_thirty_day_clock(counter):
    _bill(counter, till_seq=1, billed_at="2026-07-30T12:31:00Z")

    body = _queue(build_accountant()).json()

    assert body["pending_count"] == 1
    row = body["rows"][0]
    assert row["doc_number"] == "26-27/SEL-DEO/SAL/1"
    assert row["due_on"] == "2026-08-29"
    assert row["buyer_gstin"] == BIHAR_BUYER
    assert row["b2b_tax_kind"] == "cgst_sgst"
    assert row["status"] == "pending"


def test_a_b2c_bill_never_reaches_it(counter):
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    counter["client"].post(SALES_URL, payload, format="json")

    body = _queue(build_accountant()).json()

    assert body["rows"] == []
    assert body["pending_count"] == 0


def test_the_oldest_deadline_is_first(counter):
    """The whole point of the list: what runs out soonest is what to do next."""
    _bill(counter, till_seq=1, billed_at="2026-07-30T12:31:00Z")
    _bill(counter, till_seq=2, billed_at="2026-07-02T12:31:00Z")
    _bill(counter, till_seq=3, billed_at="2026-07-20T12:31:00Z")

    rows = _queue(build_accountant()).json()["rows"]

    assert [row["due_on"] for row in rows] == ["2026-08-01", "2026-08-19", "2026-08-29"]


def test_a_deadline_already_gone_by_is_counted_and_reads_negative(counter):
    """Rule 11: the deadline is data, so the clock is read rather than watched."""
    _bill(counter, till_seq=1, billed_at="2020-01-01T10:00:00Z")

    body = _queue(build_accountant()).json()

    assert body["overdue_count"] == 1
    assert body["rows"][0]["days_left"] < 0


# --- whose queue it is -----------------------------------------------------


def test_the_counter_that_billed_it_cannot_reach_the_queue(counter):
    """Raising an IRN is a statutory filing, not shop-floor work (grill Q8)."""
    _bill(counter, till_seq=1)

    assert _queue(counter["cashier"]).status_code == 403


def test_finance_reaches_it_without_holding_the_counter(counter):
    """`money: manage` is Owner and Accounts on the ratified sheet - and Accounts
    holds only `sell: view`, so the gate genuinely is the money one."""
    _bill(counter, till_seq=1)

    assert _queue(build_accountant()).status_code == 200


def test_a_queue_status_nothing_recognises_is_refused(counter):
    response = _queue(build_accountant(), status="nearly")

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"


# --- working it ------------------------------------------------------------


def test_recording_an_irn_takes_the_bill_off_the_pending_list(counter):
    sale = _bill(counter, till_seq=1)
    row = IrnQueueItem.objects.get(sale=sale)
    accountant = build_accountant()

    response = client_for(accountant).put(
        f"{QUEUE_URL}/{row.id}",
        {"status": "generated", "irn": "a" * 64},
        format="json",
    )

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.status == IrnQueueItem.Status.GENERATED
    assert row.irn == "a" * 64
    assert row.handled_by == accountant
    assert row.handled_at is not None
    assert _queue(accountant).json()["pending_count"] == 0


def test_a_generated_row_is_reported_on_the_bill_itself(counter):
    """The reprint has to be able to say the IRN; until then it says
    "IRN to follow", which is what the original said."""
    sale = _bill(counter, till_seq=1)
    accountant = build_accountant()
    client_for(accountant).put(
        f"{QUEUE_URL}/{IrnQueueItem.objects.get(sale=sale).id}",
        {"status": "generated", "irn": "IRN-2026-0001"},
        format="json",
    )

    body = client_for(accountant).get(f"{SALES_URL}/{sale.doc_number}").json()

    assert body["irn"] == "IRN-2026-0001"


def test_a_bill_with_no_irn_yet_reports_a_blank_one(counter):
    sale = _bill(counter, till_seq=1)

    body = client_for(build_accountant()).get(f"{SALES_URL}/{sale.doc_number}").json()

    assert body["irn"] == ""


def test_a_portal_refusal_is_recorded_so_it_can_be_chased(counter):
    sale = _bill(counter, till_seq=1)
    row = IrnQueueItem.objects.get(sale=sale)
    accountant = build_accountant()

    client_for(accountant).put(f"{QUEUE_URL}/{row.id}", {"status": "failed"}, format="json")

    row.refresh_from_db()
    assert row.status == IrnQueueItem.Status.FAILED
    assert _queue(accountant, status="failed").json()["rows"][0]["doc_number"] == sale.doc_number


def test_a_failed_row_may_be_retried(counter):
    sale = _bill(counter, till_seq=1)
    row = IrnQueueItem.objects.get(sale=sale)
    accountant = build_accountant()
    client_for(accountant).put(f"{QUEUE_URL}/{row.id}", {"status": "failed"}, format="json")

    response = client_for(accountant).put(
        f"{QUEUE_URL}/{row.id}", {"status": "generated", "irn": "IRN-2"}, format="json"
    )

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.irn == "IRN-2"


def test_an_irn_once_recorded_cannot_be_replaced(counter):
    """It is the invoice's identity at the GSTN. Two of them is two documents."""
    sale = _bill(counter, till_seq=1)
    row = IrnQueueItem.objects.get(sale=sale)
    accountant = build_accountant()
    client_for(accountant).put(
        f"{QUEUE_URL}/{row.id}", {"status": "generated", "irn": "IRN-FIRST"}, format="json"
    )

    response = client_for(accountant).put(
        f"{QUEUE_URL}/{row.id}", {"status": "generated", "irn": "IRN-SECOND"}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "IRN_ALREADY_RECORDED"
    row.refresh_from_db()
    assert row.irn == "IRN-FIRST"


def test_generated_with_no_reference_is_refused(counter):
    """A row that left the queue with nothing on it would be the queue lying."""
    sale = _bill(counter, till_seq=1)
    row = IrnQueueItem.objects.get(sale=sale)

    response = client_for(build_accountant()).put(
        f"{QUEUE_URL}/{row.id}", {"status": "generated", "irn": "  "}, format="json"
    )

    assert response.status_code == 400
    assert IrnQueueItem.objects.get().status == IrnQueueItem.Status.PENDING


def test_the_counter_cannot_record_an_irn_either(counter):
    sale = _bill(counter, till_seq=1)
    row = IrnQueueItem.objects.get(sale=sale)

    response = counter["client"].put(
        f"{QUEUE_URL}/{row.id}", {"status": "generated", "irn": "IRN-X"}, format="json"
    )

    assert response.status_code == 403


def test_a_row_outside_the_callers_stores_is_not_found_rather_than_forbidden(counter):
    """A 403 would confirm the bill exists - the same answer the sale detail gives."""
    sale = _bill(counter, till_seq=1)
    row = IrnQueueItem.objects.get(sale=sale)
    elsewhere = build_store(code="SEL-RAN", state="20")
    stranger = build_accountant(username="sell_accounts_ran")
    stranger.scope_type = "store"
    stranger.save(update_fields=["scope_type"])
    stranger.stores.add(elsewhere)

    assert _queue(stranger).json()["rows"] == []
    response = client_for(stranger).put(
        f"{QUEUE_URL}/{row.id}", {"status": "failed"}, format="json"
    )
    assert response.status_code == 404
