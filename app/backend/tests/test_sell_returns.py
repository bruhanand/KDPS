"""The plain return (#184, grill Q7, api-contract step 5).

The in-bill exchange is tested next door (`test_sell_sale_accept`, and its money
in `test_sell_sale_postings`). What this suite is about is the other flow: a
piece brought back with nothing bought in its place.

Four properties carry the whole of it, and each has a test whose name is the
sentence:

* **No cash ever leaves the drawer.** Asserted twice over - once on the value
  ledger, where a `Return` posts no leg to any tender account, and once on the
  cash ledger, where there is no receipt row against its number at all. Both,
  because the two books are written by two different functions and only one of
  them would notice if the other grew a leg.
* **Every return takes a manager of this store.** Not a value band, not a rung
  the cashier might hold.
* **The window is data**, and past it the manager's *second*, explicit answer is
  required and the return lands flagged.
* **The books unwind what the sale actually posted** - out of the book named on
  the original line, at the cost frozen on it.

Beside those, the one property no single flow can state: the exchange and the
plain return share one ceiling, so a piece given back by either route cannot be
given back again by the other.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from _sell import (
    COST_PAISE,
    FY,
    MRP_PAISE,
    SALES_URL,
    bill_payload,
    build_brand,
    build_cashier,
    build_manager,
    build_salesman,
    build_store,
    build_supplier,
    client_for,
    gst_on,
    stock_in,
)
from django.utils import timezone

from core.documents import DocStatus, DocumentEditError
from core.gl import GLAccount, GLEntry, trial_balance
from finledger.models import CashLedgerEntry
from sell.models import ContinuityFlag, CreditNote, Return, ReturnLine, Sale, SellPolicy
from sell.services.returns import returns_by_employee
from stockledger.models import QuarantineStock, StockLedgerEntry, StockOnHand

RETURNS_URL = "/api/sell/returns"
BARCODE = "8901000000011"

#: The accounts that would mean money left the drawer. Named here rather than in
#: one test, because "a return never pays cash" is the ticket's own acceptance
#: criterion and the assertion has to be able to state it as a set.
TENDER_ACCOUNTS = {GLAccount.CASH, GLAccount.CARD_CLEARING, GLAccount.UPI_CLEARING}


@pytest.fixture
def counter(db):
    """A store that can sell, its cashier, and the manager they call over."""
    store = build_store()
    cashier = build_cashier(store)
    return {
        "store": store,
        "cashier": cashier,
        "manager": build_manager(store),
        "salesman": build_salesman(store),
        "client": client_for(cashier),
    }


# --- helpers ---------------------------------------------------------------


def _sell(
    counter, *, till_seq=1, qty=1, model="Outright", on_shelf=5, days_ago=0, **kwargs
) -> Sale:
    """One bill this store made, so there is something to give back.

    `days_ago` is how old the bill is, and it is dated **relative to now** rather
    than to a fixed day. The return window is measured against the clock, so a
    fixture pinned to a calendar date would quietly start failing every test in
    this file once the wall clock passed the window - which is a suite that goes
    red one morning for no reason anybody changed.

    A posted bill cannot be aged afterwards either: the FSM trigger refuses every
    column change on a submitted row, including a bare UPDATE. Dating it at the
    counter is the only honest way, and it is what a paper re-entry does anyway.
    """
    stock_in(counter["store"], on_shelf, model=model)
    if model in {"SOR", "Consignment"}:
        build_supplier(build_brand(model))
    kwargs.setdefault("billed_at", (timezone.now() - timedelta(days=days_ago)).isoformat())
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=till_seq, qty=qty, **kwargs
    )
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    return Sale.objects.get(pk=response.json()["id"])


def _return_payload(counter, original: Sale, *, qty=1, condition="good", **overrides):
    payload = {
        "idempotency_uuid": str(uuid.uuid4()),
        "store": counter["store"].code,
        "original": {"fy": FY, "till_seq": original.till_seq},
        "lines": [{"original_line": 1, "qty": qty, "reason": "defect", "condition": condition}],
        "override": {"user_id": counter["manager"].id},
    }
    payload.update(overrides)
    return payload


def _take_back(counter, payload):
    return counter["client"].post(RETURNS_URL, payload, format="json")


def _legs(doc_number: str):
    return list(GLEntry.objects.filter(doc_number=doc_number).order_by("id"))


def _events(doc_number: str) -> list[list[GLEntry]]:
    """The document's legs, split into the vouchers they were posted as.

    `post_entries` numbers each voucher's legs from 1, so a `line_no` of 1 is
    where the next event starts - the same reading `test_sell_sale_postings`
    does, and the only one the ledger actually supports: it stores no event
    label.
    """
    events: list[list[GLEntry]] = []
    for leg in _legs(doc_number):
        if leg.line_no == 1:
            events.append([])
        events[-1].append(leg)
    return events


# --- the ordinary return ---------------------------------------------------


def test_a_returned_piece_becomes_a_credit_note_for_what_was_paid(counter):
    original = _sell(counter)

    response = _take_back(counter, _return_payload(counter, original))

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["doc_number"] == f"{FY}/{counter['store'].code}/SRT/1"
    assert body["value_paise"] == MRP_PAISE
    note = CreditNote.objects.get(doc_number=body["credit_note"])
    assert note.value_paise == MRP_PAISE
    assert note.remaining_paise == MRP_PAISE
    assert note.store == counter["store"]
    assert note.source_return.doc_number == body["doc_number"]


def test_the_note_expires_on_the_policy_and_not_on_a_constant(counter):
    """Validity is data (grill Q7): moving the dial moves the note's own date."""
    policy = SellPolicy.current()
    policy.credit_note_validity_days = 45
    policy.save(update_fields=["credit_note_validity_days"])
    original = _sell(counter)

    body = _take_back(counter, _return_payload(counter, original)).json()

    note = CreditNote.objects.get(doc_number=body["credit_note"])
    assert note.expires_on == timezone.localdate(note.created_at) + timedelta(days=45)
    assert body["expires_on"] == str(note.expires_on)


def test_the_note_the_return_issued_spends_at_the_store_that_issued_it(counter):
    """The whole point of a credit note: the money stays inside the system until
    it is spent on a real bill, and it is spendable where the customer is."""
    original = _sell(counter, till_seq=1)
    note_number = _take_back(counter, _return_payload(counter, original)).json()["credit_note"]

    payload = bill_payload(counter["store"], counter["salesman"], till_seq=2)
    payload["tenders"] = [
        {"mode": "credit_note", "amount_paise": MRP_PAISE, "credit_note": note_number}
    ]
    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    assert CreditNote.objects.get(doc_number=note_number).remaining_paise == 0


# --- the manager's tap -----------------------------------------------------


def test_a_return_without_a_manager_is_refused(counter):
    original = _sell(counter)
    payload = _return_payload(counter, original)
    payload.pop("override")

    response = _take_back(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"
    assert not Return.objects.exists()
    assert not CreditNote.objects.exists()


def test_a_cashier_cannot_be_their_own_manager(counter):
    original = _sell(counter)
    payload = _return_payload(counter, original)
    payload["override"] = {"user_id": counter["cashier"].id}

    response = _take_back(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"


def test_a_manager_from_another_store_is_not_a_manager_at_this_counter(counter):
    original = _sell(counter)
    elsewhere = build_store(code="SEL-GAY")
    payload = _return_payload(counter, original)
    payload["override"] = {"user_id": build_manager(elsewhere, "other_manager").id}

    response = _take_back(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"


def test_the_manager_who_approved_it_is_named_on_the_document(counter):
    original = _sell(counter)

    body = _take_back(counter, _return_payload(counter, original)).json()

    ret = Return.objects.get(pk=body["id"])
    assert ret.override_by == counter["manager"]
    assert ret.created_by == counter["cashier"]


# --- the window ------------------------------------------------------------


def test_a_return_past_the_window_needs_the_manager_to_say_so(counter):
    original = _sell(counter, days_ago=SellPolicy.current().return_window_days + 5)

    response = _take_back(counter, _return_payload(counter, original))

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"
    assert "days old" in response.json()["error"]


def test_a_late_return_with_the_override_lands_and_is_flagged(counter):
    original = _sell(counter, days_ago=SellPolicy.current().return_window_days + 5)

    response = _take_back(counter, _return_payload(counter, original, window_override=True))

    assert response.status_code == 201
    assert response.json()["flags"] == [ContinuityFlag.Kind.RETURN_LATE]
    ret = Return.objects.get(pk=response.json()["id"])
    assert ret.window_override is True
    flag = ContinuityFlag.objects.get(kind=ContinuityFlag.Kind.RETURN_LATE)
    assert flag.sale == original
    assert flag.details["return"] == ret.doc_number


def test_the_window_is_data_and_widening_it_takes_the_flag_away(counter):
    """Rule 12: head office moves the dial, nobody moves the code."""
    original = _sell(counter, days_ago=40)
    policy = SellPolicy.current()
    policy.return_window_days = 90
    policy.save(update_fields=["return_window_days"])

    response = _take_back(counter, _return_payload(counter, original))

    assert response.status_code == 201
    assert response.json()["flags"] == []
    assert Return.objects.get(pk=response.json()["id"]).window_override is False


# --- what the piece does to the shelf --------------------------------------


def test_a_good_piece_goes_back_on_the_shelf(counter):
    original = _sell(counter)
    before = StockOnHand.objects.get(store=counter["store"], sku_code=BARCODE).net_qty

    _take_back(counter, _return_payload(counter, original))

    leg = StockLedgerEntry.objects.get(kind=StockLedgerEntry.Kind.SALE_RETURN_IN)
    assert leg.qty == 1 and leg.amount == COST_PAISE
    assert StockOnHand.objects.get(store=counter["store"], sku_code=BARCODE).net_qty == before + 1


def test_a_damaged_piece_goes_to_quarantine_and_never_back_to_the_shelf(counter):
    original = _sell(counter)
    before = StockOnHand.objects.get(store=counter["store"], sku_code=BARCODE).net_qty

    _take_back(counter, _return_payload(counter, original, condition="damaged"))

    assert QuarantineStock.objects.get(store=counter["store"], sku_code=BARCODE).qty == 1
    assert not StockLedgerEntry.objects.filter(kind=StockLedgerEntry.Kind.SALE_RETURN_IN).exists()
    assert StockOnHand.objects.get(store=counter["store"], sku_code=BARCODE).net_qty == before


# --- the money -------------------------------------------------------------


def test_no_cash_leg_exists_on_a_return(counter):
    """The acceptance criterion, stated as a property of the whole document.

    Not "the cash leg is nought" - there is no leg at all, in either book, and
    both are checked because they are written by two different functions.
    """
    original = _sell(counter)

    body = _take_back(counter, _return_payload(counter, original)).json()

    accounts = {leg.account for leg in _legs(body["doc_number"])}
    assert accounts & TENDER_ACCOUNTS == set()
    assert not CashLedgerEntry.objects.filter(doc_number=body["doc_number"]).exists()


def test_the_money_event_gives_back_revenue_and_its_tax_as_a_liability(counter):
    original = _sell(counter)

    body = _take_back(counter, _return_payload(counter, original)).json()

    money = _events(body["doc_number"])[0]
    gst = gst_on(MRP_PAISE)
    assert [(leg.account, leg.amount) for leg in money] == [
        (GLAccount.SALES_REVENUE, MRP_PAISE - gst),
        (GLAccount.OUTPUT_GST, gst),
        (GLAccount.CREDIT_NOTE_LIABILITY, -MRP_PAISE),
    ]


def test_owned_stock_comes_back_into_our_own_inventory(counter):
    original = _sell(counter, model="Outright")

    body = _take_back(counter, _return_payload(counter, original)).json()

    cost = [
        (leg.account, leg.amount)
        for leg in _legs(body["doc_number"])
        if leg.account in {GLAccount.COGS, GLAccount.INVENTORY}
    ]
    assert cost == [(GLAccount.COGS, -COST_PAISE), (GLAccount.INVENTORY, COST_PAISE)]


def test_brand_owned_stock_reverses_what_the_brand_was_owed(counter):
    original = _sell(counter, model="SOR")

    body = _take_back(counter, _return_payload(counter, original)).json()

    cost = {
        leg.account: leg.amount
        for leg in _legs(body["doc_number"])
        if leg.account
        in {
            GLAccount.COGS,
            GLAccount.VENDOR_PAYABLE,
            GLAccount.SOR_STOCK,
            GLAccount.SOR_CONTRA,
        }
    }
    assert cost == {
        GLAccount.COGS: -COST_PAISE,
        GLAccount.VENDOR_PAYABLE: COST_PAISE,
        GLAccount.SOR_CONTRA: -COST_PAISE,
        GLAccount.SOR_STOCK: COST_PAISE,
    }
    payable = next(
        leg for leg in _legs(body["doc_number"]) if leg.account == GLAccount.VENDOR_PAYABLE
    )
    assert payable.party_type == "vendor" and payable.party_code == "ARVIND"


def test_a_return_unwinds_the_model_the_sale_posted_not_todays(counter):
    """A brand flipped from SOR to Outright between the sale and the return would
    otherwise reverse a brand-owned piece into our own inventory and leave the
    brand still owed for it - with the trial balance at nought throughout."""
    original = _sell(counter, model="SOR")
    build_brand("Outright")  # head office edits the master the next morning

    body = _take_back(counter, _return_payload(counter, original)).json()

    accounts = {leg.account for leg in _legs(body["doc_number"])}
    assert GLAccount.VENDOR_PAYABLE in accounts
    assert GLAccount.INVENTORY not in accounts


def test_the_books_tie_after_a_return(counter):
    original = _sell(counter)

    _take_back(counter, _return_payload(counter, original))

    assert trial_balance() == 0


def test_a_piece_the_books_never_priced_reverses_its_money_and_is_flagged(counter):
    """Sold before its paperwork arrived (#186), and back before the PT landed.

    The money reverses because the customer really paid it; nothing costs,
    because nothing was ever costed. The row that would ordinarily carry that
    wait (`DeferredCosting`) hangs off a `SaleLine` and a plain return has none,
    so a human is told instead of a guess being posted.
    """
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=1, barcode="9999999999999"
    )
    payload["lines"][0]["manual_desc"] = "Blue kurta off the tag"
    sold = counter["client"].post(SALES_URL, payload, format="json")
    assert sold.status_code == 201
    original = Sale.objects.get(pk=sold.json()["id"])

    response = _take_back(counter, _return_payload(counter, original))

    assert response.status_code == 201
    assert response.json()["flags"] == [ContinuityFlag.Kind.RETURN_UNCOSTED]
    accounts = {leg.account for leg in _legs(response.json()["doc_number"])}
    assert accounts == {
        GLAccount.SALES_REVENUE,
        GLAccount.OUTPUT_GST,
        GLAccount.CREDIT_NOTE_LIABILITY,
    }
    assert not StockLedgerEntry.objects.filter(
        kind__in=(StockLedgerEntry.Kind.SALE_RETURN_IN, StockLedgerEntry.Kind.QUARANTINE_IN)
    ).exists()


# --- what may be given back, and how much ----------------------------------


def test_a_part_return_gives_back_the_share_that_was_paid(counter):
    """Three pieces on a line that does not divide by three (D2).

    ₹29.99 over three pieces is 999.67 paise each. Each share is rounded half-up
    - never Python's `round()`, which is banker's rounding and would pay 999 -
    and the *last* piece settles the remainder, so the three refunds come to
    exactly what the customer paid and no paisa is stranded in the books.
    """
    # The one paisa that makes the line indivisible has to be a *discount*, and
    # the cap ships at nought - so the dial is opened for this bill. Head office
    # widens it exactly this way (Rule 12); nothing widens itself.
    policy = SellPolicy.current()
    policy.manual_discount_cap_percent = 100
    policy.save(update_fields=["manual_discount_cap_percent"])
    original = _sell(counter, qty=3, mrp_paise=1000, disc_paise=1)

    first = _take_back(counter, _return_payload(counter, original, qty=1)).json()
    second = _take_back(counter, _return_payload(counter, original, qty=1)).json()
    third = _take_back(counter, _return_payload(counter, original, qty=1)).json()

    assert [first["value_paise"], second["value_paise"], third["value_paise"]] == [1000, 1000, 999]
    assert sum(x["value_paise"] for x in (first, second, third)) == 2999


def test_a_piece_cannot_be_given_back_twice(counter):
    original = _sell(counter)
    assert _take_back(counter, _return_payload(counter, original)).status_code == 201

    again = _take_back(counter, _return_payload(counter, original))

    assert again.status_code == 422
    assert again.json()["code"] == "ALREADY_RETURNED"


def test_a_piece_already_exchanged_cannot_also_be_returned(counter):
    """The two paths share one ceiling. Without it each would count only its own
    table, and a customer could be refunded twice for one piece with every
    document individually valid."""
    original = _sell(counter)
    exchange = bill_payload(counter["store"], counter["salesman"], till_seq=2)
    refund = original.lines.get().net_paise
    exchange["exchange"] = {
        "original": {"fy": FY, "till_seq": original.till_seq},
        "lines": [
            {
                "line_no": 2,
                "barcode": BARCODE,
                "qty": 1,
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": gst_on(refund),
                "condition": "good",
                "reason": "size",
                "original_line": 1,
            }
        ],
    }
    exchange["totals"]["net_paise"] = MRP_PAISE - refund
    exchange["totals"]["gst_paise"] = gst_on(MRP_PAISE) - gst_on(refund)
    exchange["tenders"] = [{"mode": "cash", "amount_paise": MRP_PAISE - refund}]
    assert counter["client"].post(SALES_URL, exchange, format="json").status_code == 201

    response = _take_back(counter, _return_payload(counter, original))

    assert response.status_code == 422
    assert response.json()["code"] == "ALREADY_RETURNED"


def test_a_piece_already_returned_cannot_also_be_exchanged(counter):
    """The same ceiling, the other way round."""
    original = _sell(counter)
    assert _take_back(counter, _return_payload(counter, original)).status_code == 201

    exchange = bill_payload(counter["store"], counter["salesman"], till_seq=2)
    refund = original.lines.get().net_paise
    exchange["exchange"] = {
        "original": {"fy": FY, "till_seq": original.till_seq},
        "lines": [
            {
                "line_no": 2,
                "barcode": BARCODE,
                "qty": 1,
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": gst_on(refund),
                "condition": "good",
                "reason": "size",
                "original_line": 1,
            }
        ],
    }
    exchange["totals"]["net_paise"] = MRP_PAISE - refund
    exchange["totals"]["gst_paise"] = gst_on(MRP_PAISE) - gst_on(refund)
    exchange["tenders"] = [{"mode": "cash", "amount_paise": MRP_PAISE - refund}]

    response = counter["client"].post(SALES_URL, exchange, format="json")

    assert response.status_code == 422
    assert response.json()["code"] == "ALREADY_RETURNED"


def test_a_line_the_bill_does_not_have_is_refused(counter):
    original = _sell(counter)
    payload = _return_payload(counter, original)
    payload["lines"][0]["original_line"] = 9

    response = _take_back(counter, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"


def test_one_line_may_only_appear_once_in_a_return(counter):
    original = _sell(counter, qty=2)
    payload = _return_payload(counter, original)
    payload["lines"].append({"original_line": 1, "qty": 1, "reason": "", "condition": "good"})

    response = _take_back(counter, payload)

    assert response.status_code == 400
    assert "quantities together" in response.json()["error"]


# --- which bill, and whose -------------------------------------------------


def test_a_bill_this_store_does_not_hold_is_not_returnable(counter):
    original = _sell(counter)
    payload = _return_payload(counter, original)
    payload["original"]["till_seq"] = 99

    response = _take_back(counter, payload)

    assert response.status_code == 404
    assert response.json()["code"] == "ORIGINAL_NOT_FOUND"


def test_another_stores_bill_is_not_returnable_here(counter):
    """`till_seq` is a small counting number, so another shop's bill is a guess
    anybody could make - and honouring one would read back what their customer
    paid and spend that line's returnable quantity."""
    elsewhere = build_store(code="SEL-GAY")
    stock_in(elsewhere, 3)
    their_cashier = build_cashier(elsewhere, "gay_cashier")
    their_bill = bill_payload(elsewhere, build_salesman(elsewhere, "GAYA"), till_seq=1)
    assert client_for(their_cashier).post(SALES_URL, their_bill, format="json").status_code == 201

    response = _take_back(
        counter,
        {
            "idempotency_uuid": str(uuid.uuid4()),
            "store": counter["store"].code,
            "original": {"fy": FY, "till_seq": 1},
            "lines": [{"original_line": 1, "qty": 1, "reason": "", "condition": "good"}],
            "override": {"user_id": counter["manager"].id},
        },
    )

    assert response.status_code == 404


def test_a_cancelled_bill_is_not_returnable(counter):
    original = _sell(counter)
    original.cancel()

    response = _take_back(counter, _return_payload(counter, original))

    assert response.status_code == 404


def test_a_store_may_not_take_a_return_at_a_store_it_does_not_hold(counter):
    original = _sell(counter)
    build_store(code="SEL-GAY")
    payload = _return_payload(counter, original)
    payload["store"] = "SEL-GAY"

    response = _take_back(counter, payload)

    assert response.status_code == 403
    assert response.json()["code"] == "SCOPE_DENIED"


# --- replay ----------------------------------------------------------------


def test_a_replayed_return_answers_the_same_and_writes_nothing(counter):
    original = _sell(counter)
    payload = _return_payload(counter, original)
    first = _take_back(counter, payload)

    again = _take_back(counter, payload)

    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["doc_number"] == first.json()["doc_number"]
    assert again.json()["credit_note"] == first.json()["credit_note"]
    assert Return.objects.count() == 1
    assert CreditNote.objects.count() == 1
    assert ReturnLine.objects.count() == 1


# --- what the bill says about itself afterwards ----------------------------


def test_the_bill_reports_how_much_of_each_line_has_come_back(counter):
    original = _sell(counter, qty=3)
    _take_back(counter, _return_payload(counter, original, qty=2))

    detail = counter["client"].get(f"{SALES_URL}/{original.doc_number}").json()

    assert detail["lines"][0]["returned_qty"] == 2


def test_a_cancelled_return_gives_the_returnable_quantity_back(counter):
    """The books say that return never happened, and the customer is holding the
    piece and the receipt again."""
    original = _sell(counter)
    body = _take_back(counter, _return_payload(counter, original)).json()
    Return.objects.get(pk=body["id"]).cancel()

    detail = counter["client"].get(f"{SALES_URL}/{original.doc_number}").json()
    assert detail["lines"][0]["returned_qty"] == 0
    assert _take_back(counter, _return_payload(counter, original)).status_code == 201


# --- what the daily check reads --------------------------------------------


def test_returns_are_counted_per_employee(counter):
    """Grill Q7 asks for returns counted per employee in the daily check (#188).
    Both names are reported: whoever worked the counter, and the manager who
    stood behind it - the pattern the loss-prevention literature describes is one
    name recurring in either column."""
    first = _sell(counter, till_seq=1)
    second = _sell(counter, till_seq=2, on_shelf=0)
    _take_back(counter, _return_payload(counter, first))
    _take_back(counter, _return_payload(counter, second))

    counts = returns_by_employee(counter["store"], timezone.localdate())

    assert counts == [
        {
            "taken_by": counter["cashier"].username,
            "approved_by": counter["manager"].username,
            "returns": 2,
            "value_paise": MRP_PAISE * 2,
        }
    ]


def test_a_cancelled_return_stops_counting(counter):
    original = _sell(counter)
    body = _take_back(counter, _return_payload(counter, original)).json()
    Return.objects.get(pk=body["id"]).cancel()

    assert returns_by_employee(counter["store"], timezone.localdate()) == []


# --- the document itself ---------------------------------------------------


def test_a_posted_return_cannot_be_edited(counter):
    """The FSM trigger, on this table as on the sale and the credit note."""
    original = _sell(counter)
    ret = Return.objects.get(
        pk=_take_back(counter, _return_payload(counter, original)).json()["id"]
    )

    ret.window_override = True
    with pytest.raises(DocumentEditError):
        ret.save(update_fields=["window_override"])
    assert Return.objects.get(pk=ret.pk).docstatus == DocStatus.SUBMITTED
