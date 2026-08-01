"""The server accept pipeline for a bill (#177, D10 api-contract steps 1-13).

The bill has already been printed. Everything worth asserting here follows from
that one fact, and the suite is organised by what it means:

  · **Exactly once.** A replay of the same idempotency key produces the same
    answer and writes nothing; a second writer on the same number is refused;
    the till's number is minted once and a gap in it is flagged, never blocked.
  · **The stock moves.** A sold piece leaves the shelf, a returned good one comes
    back to it, a damaged one goes to quarantine, and a piece the books cannot
    price waits instead of posting at zero.
  · **Every refusal in the contract, and every flag.** Six error codes and six
    flag kinds; each one is either produced here or named as belonging to a later
    slice, so nobody has to guess which.
  · **Nothing can edit a posted bill**, by any verb, from anywhere.

What the value events actually post is asserted in `test_sell_sale_postings`
(#178); all this suite pins about them is that a bill never leaves the books
untied.
"""

from __future__ import annotations

import uuid

import pytest
from _sell import (
    COST_PAISE,
    FY,
    MRP_PAISE,
    SALES_URL,
    bill_payload,
    build_cashier,
    build_manager,
    build_piece,
    build_salesman,
    build_store,
    client_for,
    gst_on,
    stock_in,
    upi_tender,
)

from core.documents import DocStatus, VoucherSeries
from core.gl import GLEntry, trial_balance
from masters.models import Cohort, Store
from sell.models import (
    ContinuityFlag,
    CreditNote,
    CreditNoteRedemption,
    DeferredCosting,
    IrnQueueItem,
    Sale,
    SaleLine,
    SaleTender,
    SellPolicy,
)
from stockledger.models import QuarantineStock, StockLedgerEntry, StockOnHand


@pytest.fixture
def counter(db):
    """A store that can sell: a till login, a salesman, and one priced piece."""
    store = build_store()
    build_piece()
    cashier = build_cashier(store)
    return {
        "store": store,
        "cashier": cashier,
        "manager": build_manager(store),
        "salesman": build_salesman(store),
        "client": client_for(cashier),
    }


def _shelf(store: Store, qty: int) -> None:
    """Opening stock, through the ledger - see `_sell.stock_in`."""
    stock_in(store, qty)


def _post(counter, payload):
    return counter["client"].post(SALES_URL, payload, format="json")


# --- the clean sale --------------------------------------------------------


def test_a_clean_cash_sale_is_accepted_and_numbered(counter):
    _shelf(counter["store"], 3)
    response = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))

    assert response.status_code == 201
    assert response.json()["doc_number"] == f"{FY}/{counter['store'].code}/SAL/1"
    assert response.json()["flags"] == []
    sale = Sale.objects.get(pk=response.json()["id"])
    assert sale.docstatus == DocStatus.SUBMITTED
    assert sale.net_paise == MRP_PAISE
    assert sale.created_by == counter["cashier"]


def test_the_piece_leaves_the_shelf_at_its_cost_of_record(counter):
    _shelf(counter["store"], 3)
    _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))

    leg = StockLedgerEntry.objects.get(kind=StockLedgerEntry.Kind.SALE_OUT)
    assert leg.qty == -1
    # The cost the books hold for that cohort, never the price it sold at.
    assert leg.amount == -COST_PAISE
    assert leg.brand == "MUFTI" and leg.size == "M"
    assert StockOnHand.objects.get(store=counter["store"], sku_code="8901000000011").net_qty == 2


def test_a_bill_posts_a_balanced_value_ledger(counter):
    """The value side landed with #178; what it posts is asserted there.

    Pinned here as the one thing this pipeline promises about it: whatever the
    events contain, a bill never leaves the books untied - the accept transaction
    either writes a balanced set or writes no bill.
    """
    _shelf(counter["store"], 3)
    _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))

    assert GLEntry.objects.filter(doc_type="SAL").exists()
    assert trial_balance() == 0


def test_a_store_may_not_bill_at_a_store_it_does_not_hold(counter):
    other = build_store(code="SEL-RAN", state="20")
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["store"] = other.code

    response = _post(counter, payload)

    assert response.status_code == 403
    assert response.json()["code"] == "SCOPE_DENIED"
    assert not Sale.objects.exists()


# --- exactly once ----------------------------------------------------------


def test_a_replayed_bill_returns_the_same_answer_and_writes_nothing(counter):
    """The till replays from a durable queue, so this is the ordinary case, not
    an edge one: the second POST must be a read."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)

    first = _post(counter, payload)
    legs_after_first = StockLedgerEntry.objects.count()
    second = _post(counter, payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert Sale.objects.count() == 1
    assert SaleLine.objects.count() == 1
    assert StockLedgerEntry.objects.count() == legs_after_first
    assert StockOnHand.objects.get(store=counter["store"], sku_code="8901000000011").net_qty == 2


def test_a_second_writer_on_the_same_number_is_refused(counter):
    """Two tills numbering one series is a human problem - a mis-handover - and
    the server says so rather than quietly renumbering somebody's printed bill."""
    _shelf(counter["store"], 3)
    _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=7))

    clash = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=7))

    assert clash.status_code == 409
    assert clash.json()["code"] == "BILL_NO_TAKEN"
    assert Sale.objects.count() == 1


def test_a_hole_in_the_numbering_is_flagged_and_the_bill_still_lands(counter):
    """Bills 1-3 are still queued on the till and bill 4 syncs first. Refusing
    would stop the store selling because an *older* bill is stuck."""
    _shelf(counter["store"], 3)

    response = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=4))

    assert response.status_code == 201
    assert response.json()["flags"] == [ContinuityFlag.Kind.NUMBER_HOLE]
    flag = ContinuityFlag.objects.get(kind=ContinuityFlag.Kind.NUMBER_HOLE)
    assert flag.details["from_seq"] == 1
    assert flag.details["count"] == 3
    assert flag.store == counter["store"]
    assert flag.status == ContinuityFlag.Status.OPEN
    # The counter moved past the hole, so the next bill is 5 and not 2.
    series = VoucherSeries.objects.get(fy=FY, store_code=counter["store"].code, doc_type="SAL")
    assert series.next_seq == 5


def test_a_late_bill_filling_a_hole_is_taken_without_moving_the_counter(counter):
    _shelf(counter["store"], 5)
    _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=4))

    late = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=2))

    assert late.status_code == 201
    assert late.json()["doc_number"].endswith("/SAL/2")
    series = VoucherSeries.objects.get(fy=FY, store_code=counter["store"].code, doc_type="SAL")
    assert series.next_seq == 5


# --- the bill has to add up ------------------------------------------------


def test_tenders_that_do_not_come_to_the_bill_are_refused(counter):
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [{"mode": "cash", "amount_paise": 100}]

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "TENDER_MISMATCH"
    assert not Sale.objects.exists()


def test_a_line_whose_own_arithmetic_is_wrong_is_refused(counter):
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["lines"][0]["disc_paise"] = 5000  # never subtracted from net

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "TENDER_MISMATCH"


def test_tax_that_is_not_the_tax_inside_the_line_is_refused(counter):
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["lines"][0]["gst_paise"] += 1

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "TENDER_MISMATCH"


def test_a_bill_with_no_lines_is_not_a_bill(counter):
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["lines"] = []

    response = _post(counter, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"


# --- the UPI stamp (#241) ---------------------------------------------------


def test_a_upi_tender_with_no_stamp_is_refused(counter):
    _shelf(counter["store"], 1)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [{"mode": "upi", "amount_paise": MRP_PAISE}]

    response = _post(counter, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"
    assert not Sale.objects.exists()


def test_a_stamp_on_a_non_upi_tender_is_refused(counter):
    _shelf(counter["store"], 1)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [{"mode": "cash", "amount_paise": MRP_PAISE, "upi_state": "manual"}]

    response = _post(counter, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"
    assert not Sale.objects.exists()


def test_a_confirmed_upi_tender_with_no_reference_is_refused(counter):
    _shelf(counter["store"], 1)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [{"mode": "upi", "amount_paise": MRP_PAISE, "upi_state": "confirmed"}]

    response = _post(counter, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"
    assert not Sale.objects.exists()


def test_a_manual_upi_tender_carrying_a_reference_is_refused(counter):
    _shelf(counter["store"], 1)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [
        {
            "mode": "upi",
            "amount_paise": MRP_PAISE,
            "upi_state": "manual",
            "upi_reference": "AXL123456",
        }
    ]

    response = _post(counter, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"
    assert not Sale.objects.exists()


def test_a_well_stamped_manual_upi_tender_is_accepted_and_reads_back(counter):
    _shelf(counter["store"], 1)
    payload = bill_payload(
        counter["store"],
        counter["salesman"],
        till_seq=1,
        tenders=[upi_tender(MRP_PAISE)],
    )

    response = _post(counter, payload)

    assert response.status_code == 201, response.json()
    tender = SaleTender.objects.get(sale_id=response.json()["id"])
    assert tender.mode == "upi"
    assert tender.upi_state == "manual"
    assert tender.upi_reference == ""


# --- resolving what was scanned --------------------------------------------


def test_a_scan_with_no_cohort_and_no_description_has_nothing_to_sell(counter):
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, barcode="0000")
    payload["lines"][0]["season"] = ""

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "LINE_UNRESOLVED"


def test_a_piece_sold_before_its_paperwork_bills_and_waits_to_be_costed(counter):
    """Rule 5 (nothing posts at zero) and Rule 8 (nothing blocks a sale) both
    hold, because the line waits in the queue instead of posting."""
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, barcode="8909999999")
    payload["lines"][0]["season"] = ""
    payload["lines"][0]["manual_desc"] = "Blue check shirt, tag says 1499"

    response = _post(counter, payload)

    assert response.status_code == 201
    line = SaleLine.objects.get()
    assert line.sold_before_inward is True
    assert line.costing_status == SaleLine.CostingStatus.DEFERRED
    assert line.unit_cost_paise == 0
    waiting = DeferredCosting.objects.get()
    assert waiting.status == DeferredCosting.Status.WAITING
    assert waiting.barcode == "8909999999"
    # Nothing may move at zero value, so no stock leg was written at all.
    assert not StockLedgerEntry.objects.filter(kind=StockLedgerEntry.Kind.SALE_OUT).exists()


def test_a_bill_sells_the_oldest_live_season_when_the_till_does_not_say(counter):
    """A2 - a re-ordered style sits in two seasons; the store sells the old one
    first, and the cost of record follows the season, not the barcode."""
    build_piece(season="SS26", cost_paise=90000)
    Cohort.objects.filter(season="FW25").update(unit_cost_paise=COST_PAISE)
    from masters.models import Season

    Season.objects.get_or_create(
        code="SS26", defaults={"name": "Spring/Summer 2026", "status": "open", "sort_order": 3}
    )
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["lines"][0]["season"] = ""

    response = _post(counter, payload)

    assert response.status_code == 201
    assert SaleLine.objects.get().season == "FW25"
    sold = StockLedgerEntry.objects.get(kind=StockLedgerEntry.Kind.SALE_OUT)
    assert sold.amount == -COST_PAISE


def test_a_store_whose_count_says_zero_still_sells_the_piece_in_its_hand(counter):
    """Grill Q5 - the local count going negative is a stocktake's problem, and a
    customer standing at the counter is not."""
    _shelf(counter["store"], 0)

    response = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))

    assert response.status_code == 201
    assert StockOnHand.objects.get(store=counter["store"], sku_code="8901000000011").net_qty == -1


# --- the manager's tap -----------------------------------------------------


def test_a_discount_the_rulebook_did_not_produce_needs_a_manager(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"
    assert not Sale.objects.exists()


def test_the_manager_who_approved_it_is_recorded_on_the_line(counter):
    """H3 - an override is evidence, so it names a person and stays on the bill."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    payload["override"] = {"user_id": counter["manager"].id, "kind": "over_cap_discount"}

    response = _post(counter, payload)

    assert response.status_code == 201
    assert SaleLine.objects.get().override_by == counter["manager"]
    # And on the bill, which is where an override with no line of its own lands.
    assert Sale.objects.get().override_by == counter["manager"]


def test_a_cashier_cannot_be_their_own_manager(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    payload["override"] = {"user_id": counter["cashier"].id}

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"


def test_a_manager_from_another_store_is_not_a_manager_at_this_counter(counter):
    elsewhere = build_store(code="SEL-RAN", state="20")
    stranger = build_manager(elsewhere, username="sell_other_manager")
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    payload["override"] = {"user_id": stranger.id}

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"


def test_a_discount_inside_the_cap_needs_nobody(counter):
    """The dial is data: head office widens it and the same bill goes through."""
    policy = SellPolicy.current()
    policy.manual_discount_cap_percent = 20
    policy.save()
    _shelf(counter["store"], 3)

    response = _post(
        counter, bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    )

    assert response.status_code == 201
    assert SaleLine.objects.get().override_by is None


def test_a_till_cannot_lift_its_own_cap_by_calling_a_discount_an_offer(counter):
    """The cap exists to constrain the till, so the till's own word cannot lift it.

    `offer_evidence.saved_paise` arrives in the payload. If the cap subtracted it,
    a till - or anything posting as one - would set it to the whole discount and
    OVERRIDE_REQUIRED could never fire again. Since #183 the cap subtracts the
    *server's* own resolution instead, and there is no rulebook here at all, so
    the claim buys nothing and the cap covers the whole discount.
    """
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    payload["lines"][0]["offer_evidence"] = {"layer": "brand", "id": 1, "saved_paise": 20000}

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"


def test_the_evidence_is_still_kept_on_the_line_for_the_daily_check(counter):
    """It gets no vote on the cap, but it is what the applied-vs-rulebook check
    will audit, so it is stored exactly as the till sent it."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    evidence = {"layer": "brand", "id": 1, "saved_paise": 20000}
    payload["lines"][0]["offer_evidence"] = evidence
    payload["override"] = {"user_id": counter["manager"].id}

    response = _post(counter, payload)

    assert response.status_code == 201
    assert SaleLine.objects.get().offer_evidence == evidence


# --- credit notes ----------------------------------------------------------


def _issue_note(store, value_paise: int = 50000) -> CreditNote:
    note = CreditNote.objects.create(
        store=store,
        fy=FY,
        value_paise=value_paise,
        expires_on="2027-01-30",
    )
    note.post()
    return note


def test_a_credit_note_pays_part_of_a_bill_and_is_drawn_down(counter):
    _shelf(counter["store"], 3)
    note = _issue_note(counter["store"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [
        {"mode": "credit_note", "amount_paise": 50000, "credit_note": note.doc_number},
        {"mode": "cash", "amount_paise": MRP_PAISE - 50000},
    ]

    response = _post(counter, payload)

    assert response.status_code == 201
    note.refresh_from_db()
    assert note.remaining_paise == 0
    assert note.status == CreditNote.Status.SPENT
    assert CreditNoteRedemption.objects.get().amount_paise == 50000


def test_a_note_this_store_does_not_recognise_is_refused_without_a_manager(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [
        {"mode": "credit_note", "amount_paise": 50000, "credit_note": "26-27/XXX/CRN/9"},
        {"mode": "cash", "amount_paise": MRP_PAISE - 50000},
    ]

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "CREDIT_NOTE_INVALID"


def test_a_manager_may_take_an_unrecognised_note_and_it_is_flagged(counter):
    """Grill Q4 - the note may be genuine and simply unsynced, and the customer
    is standing there. The daily check gets it, not the queue."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [
        {"mode": "credit_note", "amount_paise": 50000, "credit_note": "26-27/XXX/CRN/9"},
        {"mode": "cash", "amount_paise": MRP_PAISE - 50000},
    ]
    payload["override"] = {"user_id": counter["manager"].id}

    response = _post(counter, payload)

    assert response.status_code == 201
    assert response.json()["flags"] == [ContinuityFlag.Kind.CN_UNVERIFIED]
    assert not CreditNoteRedemption.objects.exists()


def test_the_manager_who_took_an_unrecognised_note_is_named_on_the_bill(counter):
    """#182 - the override is the only evidence such a bill has.

    A credit-note override has no line to hang the manager off: the tender is a
    bill-level fact and the line it helped pay for is an ordinary line. Without
    the bill carrying it, the daily check sees "somebody took an unknown note"
    with no name against it, which is the exact evidence the counter's second eye
    exists to leave.
    """
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [
        {"mode": "credit_note", "amount_paise": 50000, "credit_note": "26-27/XXX/CRN/9"},
        {"mode": "cash", "amount_paise": MRP_PAISE - 50000},
    ]
    payload["override"] = {
        "user_id": counter["manager"].id,
        "kind": "credit_note",
        "at": "2026-07-30T12:29:00Z",
    }

    response = _post(counter, payload)

    assert response.status_code == 201
    sale = Sale.objects.get()
    assert sale.override_by == counter["manager"]
    assert sale.override_kind == "credit_note"
    assert sale.override_at.isoformat() == "2026-07-30T12:29:00+00:00"


def test_a_bill_that_needed_two_things_approving_says_so_in_one_word(counter):
    """The daily check groups on this value, so the pair has one spelling."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    payload["tenders"] = [
        {"mode": "credit_note", "amount_paise": 50000, "credit_note": "26-27/XXX/CRN/9"},
        {"mode": "cash", "amount_paise": MRP_PAISE - 20000 - 50000},
    ]
    payload["override"] = {
        "user_id": counter["manager"].id,
        "kind": "over_cap_discount+credit_note",
    }

    response = _post(counter, payload)

    assert response.status_code == 201
    assert Sale.objects.get().override_kind == "over_cap_discount+credit_note"


def test_a_kind_nothing_recognises_is_refused(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    payload["override"] = {"user_id": counter["manager"].id, "kind": "because I said so"}

    response = _post(counter, payload)

    assert response.status_code == 400
    assert not Sale.objects.exists()


def test_what_was_authorised_is_what_the_server_found_not_what_the_till_said(counter):
    """The daily check groups on this field, and the till is the party the
    override constrains - so a bill cannot file an over-cap discount under
    "credit_note" and have neither counted honestly."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    payload["override"] = {"user_id": counter["manager"].id, "kind": "credit_note"}

    response = _post(counter, payload)

    assert response.status_code == 201
    assert Sale.objects.get().override_kind == "over_cap_discount"


def test_a_bill_nobody_had_to_authorise_names_nobody(counter):
    _shelf(counter["store"], 3)

    response = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))

    assert response.status_code == 201
    sale = Sale.objects.get()
    assert sale.override_by is None
    assert sale.override_kind == ""
    assert sale.override_at is None


def test_an_override_naming_somebody_who_is_not_a_manager_leaves_no_evidence(counter):
    """A refused override is not evidence of anything - and the bill that carried
    it does not exist, because the discount it was offered for is refused."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=20000)
    payload["override"] = {"user_id": counter["cashier"].id, "kind": "over_cap_discount"}

    response = _post(counter, payload)

    assert response.status_code == 422
    assert not Sale.objects.exists()


def test_one_note_cannot_be_tendered_twice_on_one_bill(counter):
    """Both rows would be checked against the same untouched balance and both
    would pass, then collide on the redemption key. The honest answer is to say
    how much of the note is being spent, once."""
    _shelf(counter["store"], 3)
    note = _issue_note(counter["store"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [
        {"mode": "credit_note", "amount_paise": 25000, "credit_note": note.doc_number},
        {"mode": "credit_note", "amount_paise": 25000, "credit_note": note.doc_number},
        {"mode": "cash", "amount_paise": MRP_PAISE - 50000},
    ]

    response = _post(counter, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"
    assert not CreditNoteRedemption.objects.exists()


def test_a_bill_cannot_take_less_than_its_lines_by_inventing_rounding(counter):
    """Rounding to the nearest rupee moves a bill by at most 50 paise. Unbounded,
    this one line would let a bill collect hundreds of rupees less and still add
    up, because it sits inside the net-versus-tenders check."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["totals"]["round_paise"] = -50000
    payload["totals"]["net_paise"] = MRP_PAISE - 50000
    payload["tenders"] = [{"mode": "cash", "amount_paise": MRP_PAISE - 50000}]

    response = _post(counter, payload)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"
    assert not Sale.objects.exists()


def test_another_stores_note_is_not_spendable_here(counter):
    """Same-store only in v1 - one till per store is what makes offline
    redemption safe, and that guarantee stops at the shop door."""
    elsewhere = build_store(code="SEL-RAN", state="20")
    note = _issue_note(elsewhere)
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["tenders"] = [
        {"mode": "credit_note", "amount_paise": 50000, "credit_note": note.doc_number},
        {"mode": "cash", "amount_paise": MRP_PAISE - 50000},
    ]

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "CREDIT_NOTE_INVALID"


# --- exchange --------------------------------------------------------------


def _original_bill(counter, till_seq: int = 1):
    _shelf(counter["store"], 5)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq)
    response = _post(counter, payload)
    assert response.status_code == 201
    return Sale.objects.get(pk=response.json()["id"])


def _exchange_payload(counter, original, *, till_seq: int, condition: str = "good"):
    refund = original.lines.get().net_paise
    new_net = MRP_PAISE
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq)
    payload["exchange"] = {
        "original": {"store": counter["store"].code, "fy": FY, "till_seq": original.till_seq},
        "lines": [
            {
                "line_no": 2,
                "barcode": "8901000000011",
                "qty": 1,
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": gst_on(refund),
                "condition": condition,
                "reason": "size",
                "original_line": 1,
            }
        ],
    }
    payload["totals"]["net_paise"] = new_net - refund
    payload["totals"]["gst_paise"] = gst_on(new_net) - gst_on(refund)
    payload["tenders"] = [{"mode": "cash", "amount_paise": new_net - refund}]
    return payload


def test_a_good_piece_given_back_returns_to_the_shelf(counter):
    original = _original_bill(counter)
    before = StockOnHand.objects.get(store=counter["store"], sku_code="8901000000011").net_qty

    response = _post(counter, _exchange_payload(counter, original, till_seq=2))

    assert response.status_code == 201
    leg = StockLedgerEntry.objects.get(kind=StockLedgerEntry.Kind.SALE_RETURN_IN)
    assert leg.qty == 1 and leg.amount == COST_PAISE
    after = StockOnHand.objects.get(store=counter["store"], sku_code="8901000000011").net_qty
    assert after == before  # one out, one back in


def test_a_damaged_piece_given_back_goes_to_quarantine_not_the_shelf(counter):
    """D3 - a damaged return is not sellable stock, and putting it back on the
    shelf is how a customer ends up buying it twice."""
    original = _original_bill(counter)
    before = StockOnHand.objects.get(store=counter["store"], sku_code="8901000000011").net_qty

    response = _post(counter, _exchange_payload(counter, original, till_seq=2, condition="damaged"))

    assert response.status_code == 201
    assert StockLedgerEntry.objects.filter(kind=StockLedgerEntry.Kind.QUARANTINE_IN).count() == 1
    assert not StockLedgerEntry.objects.filter(kind=StockLedgerEntry.Kind.SALE_RETURN_IN).exists()
    bucket = QuarantineStock.objects.get(store=counter["store"], sku_code="8901000000011")
    assert bucket.qty == 1
    after = StockOnHand.objects.get(store=counter["store"], sku_code="8901000000011").net_qty
    assert after == before - 1  # the new piece left; the damaged one did not return


def test_a_refund_that_is_not_what_the_customer_paid_is_refused(counter):
    """D2 - what comes back is what was paid, never today's price."""
    original = _original_bill(counter)
    payload = _exchange_payload(counter, original, till_seq=2)
    payload["exchange"]["lines"][0]["refund_paise"] += 10000

    response = _post(counter, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "TENDER_MISMATCH"


def test_a_piece_cannot_be_given_back_twice(counter):
    original = _original_bill(counter)
    first = _post(counter, _exchange_payload(counter, original, till_seq=2))
    assert first.status_code == 201

    again = _post(counter, _exchange_payload(counter, original, till_seq=3))

    assert again.status_code == 422
    assert again.json()["code"] == "ALREADY_RETURNED"


def test_a_bill_at_another_store_cannot_be_returned_against(counter):
    """`till_seq` is a small counting number, so naming another store's bill is a
    guess anybody can make. Honouring it would read back what that shop's customer
    paid, pull its cost of record into this shop's ledger, and spend a returnable
    quantity nobody here has seen."""
    elsewhere = build_store(code="SEL-RAN", state="20")
    their_seller = build_cashier(elsewhere, username="sell_ran")
    their_salesman = build_salesman(elsewhere, code="RANI")
    stock_in(elsewhere, 5)
    theirs = client_for(their_seller).post(
        SALES_URL, bill_payload(elsewhere, their_salesman, till_seq=1), format="json"
    )
    assert theirs.status_code == 201

    _shelf(counter["store"], 5)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    refund = MRP_PAISE
    payload["exchange"] = {
        "original": {"store": elsewhere.code, "fy": FY, "till_seq": 1},
        "lines": [
            {
                "line_no": 2,
                "barcode": "8901000000011",
                "qty": 1,
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": gst_on(refund),
                "condition": "good",
                "original_line": 1,
            }
        ],
    }
    payload["totals"]["net_paise"] = 0
    payload["totals"]["gst_paise"] = 0
    payload["tenders"] = []

    response = _post(counter, payload)

    # Taken as a paper-era return - flagged, unpriced, and above all not linked to
    # the other store's line, whose returnable quantity is untouched.
    assert response.status_code == 201
    assert ContinuityFlag.Kind.RETURN_ORIG_MISSING in response.json()["flags"]
    their_line = Sale.objects.get(pk=theirs.json()["id"]).lines.get()
    assert not SaleLine.objects.filter(original_line=their_line).exists()


def test_a_cancelled_bill_is_not_returnable(counter):
    """It has already been reversed; giving back against it would refund what the
    books say was never sold."""
    original = _original_bill(counter)
    original.cancel()

    response = _post(counter, _exchange_payload(counter, original, till_seq=2))

    assert response.status_code == 201
    assert ContinuityFlag.Kind.RETURN_ORIG_MISSING in response.json()["flags"]


def test_a_part_return_is_rounded_half_up_and_the_parts_sum_to_the_whole(counter):
    """Three pieces at ten rupees refund 333 + 333 + 334 paise, never 333 thrice.

    Python's `round()` is banker's rounding on a float, so 1005/2 would give 502
    where half-up gives 503 - and the till, which computed it correctly, would
    have its printed bill refused.
    """
    stock_in(counter["store"], 9)
    paid = 1000  # three pieces for ten rupees: a third does not divide
    sale = bill_payload(counter["store"], counter["salesman"], till_seq=1, qty=3, mrp_paise=1000)
    sale["lines"][0]["disc_paise"] = 2000
    sale["lines"][0]["net_paise"] = paid
    sale["lines"][0]["gst_paise"] = gst_on(paid)
    sale["totals"] = {
        "gross_paise": 3000,
        "discount_paise": 2000,
        "net_paise": paid,
        "gst_paise": gst_on(paid),
        "round_paise": 0,
    }
    sale["tenders"] = [{"mode": "cash", "amount_paise": paid}]
    sale["override"] = {"user_id": counter["manager"].id}
    created = _post(counter, sale)
    assert created.status_code == 201, created.json()
    original = Sale.objects.get(pk=created.json()["id"])

    refunds = []
    for i, seq in enumerate((2, 3, 4), start=1):
        payload = bill_payload(counter["store"], counter["salesman"], till_seq=seq)
        payload["lines"] = []
        payload["exchange"] = {
            "original": {"store": counter["store"].code, "fy": FY, "till_seq": 1},
            "lines": [
                {
                    "line_no": 1,
                    "barcode": "8901000000011",
                    "qty": 1,
                    "refund_paise": 334 if i == 3 else 333,
                    "gst_rate": "5",
                    "gst_paise": gst_on(334 if i == 3 else 333),
                    "condition": "good",
                    "original_line": 1,
                }
            ],
        }
        refunds.append(334 if i == 3 else 333)
        payload["totals"] = {
            "gross_paise": 0,
            "discount_paise": 0,
            "net_paise": -refunds[-1],
            "gst_paise": -gst_on(refunds[-1]),
            "round_paise": 0,
        }
        payload["tenders"] = []
        assert _post(counter, payload).status_code == 201, f"leg {i}"

    assert sum(refunds) == original.lines.get().net_paise == paid


def test_a_return_against_a_bill_from_the_paper_era_is_taken_and_flagged(counter):
    _shelf(counter["store"], 5)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    refund = 100000
    payload["exchange"] = {
        "original": {"store": counter["store"].code, "fy": "25-26", "till_seq": 4001},
        "lines": [
            {
                "line_no": 2,
                "barcode": "8901000000011",
                "qty": 1,
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": gst_on(refund),
                "condition": "good",
                "reason": "size",
            }
        ],
    }
    payload["totals"]["net_paise"] = MRP_PAISE - refund
    payload["totals"]["gst_paise"] = gst_on(MRP_PAISE) - gst_on(refund)
    payload["tenders"] = [{"mode": "cash", "amount_paise": MRP_PAISE - refund}]

    response = _post(counter, payload)

    assert response.status_code == 201
    assert ContinuityFlag.Kind.RETURN_ORIG_MISSING in response.json()["flags"]


def test_a_bill_that_owes_the_customer_money_issues_a_note_and_no_cash(counter):
    """Grill Q7 - cash never leaves the drawer on a return."""
    original = _original_bill(counter)
    payload = _exchange_payload(counter, original, till_seq=2)
    # Give back the piece and buy nothing: the bill nets negative.
    payload["lines"] = []
    payload["totals"] = {
        "gross_paise": 0,
        "discount_paise": 0,
        "net_paise": -MRP_PAISE,
        "gst_paise": -gst_on(MRP_PAISE),
        "round_paise": 0,
    }
    payload["tenders"] = []

    response = _post(counter, payload)

    assert response.status_code == 201
    note = CreditNote.objects.get(source_sale__isnull=False)
    assert note.value_paise == MRP_PAISE
    assert note.doc_number.startswith(f"{FY}/{counter['store'].code}/CRN/")
    assert note.status == CreditNote.Status.OPEN
    # 180 days from the billing date, per the policy dial.
    assert str(note.expires_on) == "2027-01-26"


# --- the B2B corner --------------------------------------------------------


def test_a_gstin_on_the_bill_splits_the_tax_and_starts_the_irn_clock(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["customer"]["gstin"] = "10AABCU9603R1Z2"  # same state as the store

    response = _post(counter, payload)

    assert response.status_code == 201
    sale = Sale.objects.get()
    assert sale.b2b_tax_kind == Sale.B2bTaxKind.CGST_SGST
    assert str(IrnQueueItem.objects.get().due_on) == "2026-08-29"


def test_a_buyer_in_another_state_makes_it_igst(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["customer"]["gstin"] = "20AABCU9603R1Z1"  # Jharkhand; the store is Bihar

    _post(counter, payload)

    assert Sale.objects.get().b2b_tax_kind == Sale.B2bTaxKind.IGST


def test_a_printed_split_that_disagrees_with_the_gstin_is_flagged(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["customer"]["gstin"] = "20AABCU9603R1Z1"
    payload["b2b_tax_kind"] = "cgst_sgst"

    response = _post(counter, payload)

    assert response.status_code == 201
    assert ContinuityFlag.Kind.GST_MISMATCH in response.json()["flags"]


def test_a_well_formed_gstin_raises_nothing(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["customer"]["gstin"] = "10AABCU9603R1Z2"

    response = _post(counter, payload)

    assert response.json()["flags"] == []


def test_a_mistyped_gstin_is_flagged_and_the_bill_still_lands(counter):
    """#187's acceptance: validated softly - flagged, never refused.

    The customer is at the counter holding the garment. A cashier who fumbled one
    character of fifteen has made a tax invoice head office must correct, not a
    sale the shop should decline.
    """
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    # The real registration transposed - the shape survives, the check digit does
    # not, which is the commonest way a GSTIN is mistyped and the one that costs
    # the customer their input credit.
    payload["customer"]["gstin"] = "10AABCU9603R1ZM"

    response = _post(counter, payload)

    assert response.status_code == 201
    assert ContinuityFlag.Kind.GSTIN_INVALID in response.json()["flags"]
    flag = ContinuityFlag.objects.get(kind=ContinuityFlag.Kind.GSTIN_INVALID)
    assert flag.details["gstin"] == "10AABCU9603R1ZM"
    assert "check digit" in flag.details["reason"]


def test_a_mistyped_gstin_still_prints_and_records_a_split(counter):
    """The two characters that decide the tax are taken as typed.

    The till printed the customer's copy from them minutes ago and offline; a
    server that quietly chose otherwise would put one tax on the paper and
    another in the books. It is flagged for a human, never re-taxed.
    """
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["customer"]["gstin"] = "20AABCU9603R1ZM"  # Jharkhand, and mistyped

    _post(counter, payload)

    assert Sale.objects.get().b2b_tax_kind == Sale.B2bTaxKind.IGST


def test_a_gstin_is_stored_upper_case_however_it_was_typed(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["customer"]["gstin"] = " 10aabcu9603r1z2 "

    response = _post(counter, payload)

    assert Sale.objects.get().buyer_gstin == "10AABCU9603R1Z2"
    assert response.json()["flags"] == []


def test_a_bill_with_no_gstin_starts_no_clock_and_raises_nothing(counter):
    """#187's fourth acceptance criterion: B2C bills are completely unaffected."""
    _shelf(counter["store"], 3)

    response = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))

    assert response.json()["flags"] == []
    assert Sale.objects.get().b2b_tax_kind == Sale.B2bTaxKind.NONE
    assert not IrnQueueItem.objects.exists()


def test_tax_that_disagrees_with_the_dated_slab_is_flagged_not_refused(counter):
    """Step 12 is advisory by design: the bill is printed and the customer has
    gone, so the daily check gets told which bills to look at."""
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, gst_rate="18")

    response = _post(counter, payload)

    assert response.status_code == 201
    assert ContinuityFlag.Kind.GST_MISMATCH in response.json()["flags"]
    flag = ContinuityFlag.objects.get(kind=ContinuityFlag.Kind.GST_MISMATCH)
    assert flag.details["lines"][0]["slab_rate"] == "5.00"


# --- immutability ----------------------------------------------------------


@pytest.mark.parametrize("verb", ["put", "patch", "delete"])
def test_no_endpoint_can_change_a_posted_bill(counter, verb):
    """A7 - the paper in the customer's hand is the fact; the only correction is
    the kernel's reversing transition, and there is no route to anything else."""
    _shelf(counter["store"], 3)
    created = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))
    sale = Sale.objects.get(pk=created.json()["id"])

    detail = getattr(counter["client"], verb)(
        f"{SALES_URL}/{sale.doc_number}", {"net_paise": 1}, format="json"
    )
    listing = getattr(counter["client"], verb)(SALES_URL, {"net_paise": 1}, format="json")

    assert detail.status_code == 405
    assert listing.status_code == 405
    sale.refresh_from_db()
    assert sale.net_paise == MRP_PAISE


def test_the_database_itself_refuses_to_edit_a_posted_bill(counter):
    """Belt and braces: the trigger binds even a shell, not just the API."""
    from core.documents import DocumentEditError

    _shelf(counter["store"], 3)
    created = _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))
    sale = Sale.objects.get(pk=created.json()["id"])

    sale.net_paise = 1
    with pytest.raises(DocumentEditError):
        sale.save()


# --- flag kinds ------------------------------------------------------------


def test_every_flag_kind_the_contract_names_exists(counter):
    """All ten have a producer now, and each is asserted where it is raised: the
    four counter ones here, `offer_mismatch` in the rulebook suite (#183),
    `aged_uncosted` in the deferred-costing suite (#186) - raised by the nightly
    ageing pass on a queue that has not drained, not by a bill - `gstin_invalid`
    here too (#187), the two return ones in the plain-return suite (#184), and
    `employee_returns` in the daily-check suite (#188).

    Four of the ten are kinds db-design did not list, and each is deliberately its
    own rather than folded into a neighbour, because head office answers each with
    entirely different work:

    * `gstin_invalid` - "a character of this registration is mistyped", which is
      not "the tax on this bill is not the dated slab's".
    * `return_late` - a manager set the return window aside, which is the one
      policy at a counter they can set aside on their own say-so.
    * `return_uncosted` - a piece given back before the books could ever price it,
      so there is a cost event still parked against a sale that has been reversed.
    * `employee_returns` - a pattern *across* bills, so there is no one bill to
      hang it on and no one bill that answers it.
    """
    assert set(ContinuityFlag.Kind.values) == {
        "number_hole",
        "cn_unverified",
        "return_orig_missing",
        "offer_mismatch",
        "gst_mismatch",
        "gstin_invalid",
        "aged_uncosted",
        "return_late",
        "return_uncosted",
        "employee_returns",
    }


def test_a_bill_can_carry_more_than_one_flag_at_once(counter):
    _shelf(counter["store"], 3)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=6, gst_rate="18")

    response = _post(counter, payload)

    assert response.json()["flags"] == [
        ContinuityFlag.Kind.GST_MISMATCH,
        ContinuityFlag.Kind.NUMBER_HOLE,
    ]


def test_an_unknown_idempotency_key_is_a_new_bill_not_a_replay(counter):
    _shelf(counter["store"], 5)
    _post(counter, bill_payload(counter["store"], counter["salesman"], till_seq=1))

    second = _post(
        counter,
        bill_payload(
            counter["store"], counter["salesman"], till_seq=2, idempotency_uuid=str(uuid.uuid4())
        ),
    )

    assert second.status_code == 201
    assert Sale.objects.count() == 2


# --- the database's own guard (#241) ----------------------------------------


def test_the_database_refuses_a_upi_row_with_no_stamp(db):
    """The API validates, and the table refuses independently - `ck_saletender_
    upi_state_iff_upi` is the model's property of the data, not a rule that only
    holds when this endpoint is the writer."""
    from django.db.utils import IntegrityError

    store = build_store()
    cashier = build_cashier(store)
    sale = Sale.objects.create(
        store=store, fy=FY, till_seq=1, billed_at="2026-07-30T12:00:00Z", created_by=cashier
    )

    with pytest.raises(IntegrityError):
        SaleTender.objects.create(sale=sale, mode="upi", amount_paise=100, upi_state="")
