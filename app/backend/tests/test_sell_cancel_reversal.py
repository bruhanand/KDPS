"""Cancelling a bill or a return, and every mark it has to take back (#220).

Before this, `cancel()` walked the row to `cancelled` and did nothing else. So a
cancelled bill left five things standing: its legs in the general ledger, its
pieces off the shelf, the money in the store's drawer, the accrual against what
we owed the brand, and - worst - the credit note in the customer's hand, still
spendable for a refund the books now said had never been given. The returnable
quantity on the original line was freed at the same moment (correctly: the piece
is back with the customer), so the very same line could be returned again for a
*second* live note while the first was still good.

The suite is written the way the defect is read: **against the state of the books
before and after**, not against the number of rows written. A cancel is correct
when every account balance, every stock bucket and every subledger is exactly what
it was before the document existed - so that is what each test asserts, over the
bill shapes that post different things (owned stock, brand-owned stock, split
tenders, an exchange, a piece sold before its paperwork).

Two things it also pins, which are properties of the design rather than of any
one bill:

  · **the refusal.** A note that has already been partly spent is not this
    cascade's decision - the money left the counter with a customer who used it -
    so the cancel is refused by name and the document is left exactly as it was
    (#291, on the same ground as the CA-gated no-reposting rule).
  · **atomicity.** A refusal half-way through leaves nothing behind, because the
    whole cascade rides inside the transition's own transaction.

Cancel is deliberately unreachable from any screen (api-contract A7: no mutation
endpoint exists on a posted Sale), so every test here drives the document object
the way a shell session does.
"""

from __future__ import annotations

from datetime import date

import pytest
from _sell import (
    COST_PAISE,
    MRP_PAISE,
    SALES_URL,
    bill_payload,
    build_brand,
    build_cashier,
    build_manager,
    build_piece,
    build_salesman,
    build_store,
    build_supplier,
    client_for,
    gst_on,
    stock_in,
    upi_tender,
)
from django.core.management import call_command
from django.db.models import Sum

from core.documents import DocStatus
from core.gl import GLAccount, GLEntry, account_balance, trial_balance
from core.reversal import ReversalRefused
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from sell.models import (
    CreditNote,
    CreditNoteRedemption,
    DeferredCosting,
    Return,
    ReturnLine,
    Sale,
    SaleLine,
    SellPolicy,
)
from sell.services.costing_sweep import sweep_deferred
from sell.services.movements import post_stock_move
from sell.services.postings import CostedLine, plan_from_original, post_return_value
from stockledger.models import QuarantineStock, StockOnHand

#: A barcode the books have never heard of - a piece sold before its paperwork.
UNKNOWN = "8909999999901"


@pytest.fixture
def counter(db):
    store = build_store()
    cashier = build_cashier(store)
    return {
        "store": store,
        "cashier": cashier,
        "manager": build_manager(store),
        "salesman": build_salesman(store),
        "client": client_for(cashier),
    }


# --- reading the books -----------------------------------------------------


def _books() -> dict[str, int]:
    """Every account with a balance, as one comparable snapshot.

    Balances rather than row counts, because a reversal *adds* rows: the ledger is
    append-only by DB trigger, so "back to where it was" can only ever mean the
    sums, never the shape.
    """
    return {
        row["account"]: row["total"]
        for row in GLEntry.objects.values("account").annotate(total=Sum("amount"))
        if row["total"]
    }


def _shelf() -> dict[tuple[int, str], tuple[int, int]]:
    """Every stock bucket that holds anything: on-hand and quarantine alike."""
    on_hand = {
        (row.store_id, row.sku_code): (row.net_qty, int(row.net_value_paise or 0))
        for row in StockOnHand.objects.all()
        if row.net_qty or row.net_value_paise
    }
    quarantine = {
        (row.store_id, f"quarantine:{row.sku_code}"): (row.qty, int(row.value_paise or 0))
        for row in QuarantineStock.objects.all()
    }
    return {**on_hand, **quarantine}


def _subledgers() -> dict[str, int]:
    """The two running balances the Books Health screen ties against the GL.

    Zeros are dropped for the same reason `_books` drops them: a reversal appends
    rather than deletes, so an account that has netted back to nothing is exactly
    an account that never existed - and keeping the key would make every snapshot
    compare unequal for a difference that is not one.
    """
    balances = {"vendor": VendorLedgerEntry.objects.aggregate(t=Sum("amount"))["t"] or 0}
    for row in CashLedgerEntry.objects.values("account").annotate(total=Sum("amount")):
        balances[f"cash:{row['account']}"] = row["total"] or 0
    return {key: total for key, total in balances.items() if total}


def _state() -> tuple[dict, dict, dict]:
    return _books(), _shelf(), _subledgers()


def _sell(counter, *, model="Outright", qty_on_shelf=3, till_seq=1, **payload_kwargs) -> Sale:
    """Shelve a piece on `model` and bill it. Returns the posted bill."""
    stock_in(counter["store"], qty_on_shelf, model=model)
    if model in {"SOR", "Consignment"}:
        build_supplier(build_brand(model))
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=till_seq, **payload_kwargs
    )
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    return Sale.objects.get(pk=response.json()["id"])


# --- the books come back ---------------------------------------------------


@pytest.mark.parametrize("model", ["Outright", "Correction", "SOR", "Consignment"])
def test_cancelling_a_bill_puts_the_books_back_exactly(counter, model):
    """The headline. Every account, every bucket, every subledger, on every one of
    the four commercial models - because the cost side branches on the model and
    a reversal that read today's masters instead of the line's frozen columns
    would unwind a brand-owned piece into our own inventory and still tie."""
    stock_in(counter["store"], 3, model=model)
    if model in {"SOR", "Consignment"}:
        build_supplier(build_brand(model))
    before = _state()

    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    sale = Sale.objects.get(pk=response.json()["id"])
    assert _state() != before  # the bill did something, or this proves nothing

    sale.cancel(counter["cashier"])

    assert _state() == before
    assert trial_balance() == 0
    assert Sale.objects.get(pk=sale.pk).docstatus == DocStatus.CANCELLED


def test_cancelling_a_bill_paid_three_ways_puts_each_drawer_back(counter):
    """Card and UPI are clearing accounts, not cash: a reversal that netted them
    into one would tie on the total and leave the settlement reconciliation
    reading the wrong number in three places."""
    stock_in(counter["store"], 3)
    before = _state()
    third = MRP_PAISE // 3
    tenders = [
        {"mode": "cash", "amount_paise": third},
        {"mode": "card", "amount_paise": third},
        upi_tender(MRP_PAISE - 2 * third),
    ]
    response = counter["client"].post(
        SALES_URL,
        bill_payload(counter["store"], counter["salesman"], till_seq=1, tenders=tenders),
        format="json",
    )
    assert response.status_code == 201, response.json()
    sale = Sale.objects.get(pk=response.json()["id"])
    assert account_balance(GLAccount.CARD_CLEARING) == third

    sale.cancel(counter["cashier"])

    assert _state() == before
    # the cash subledger un-took each tender under the bill's own number
    reversals = CashLedgerEntry.objects.filter(
        doc_number=sale.doc_number, kind=CashLedgerEntry.Kind.REVERSAL
    )
    assert reversals.count() == 3
    assert all(row.reverses_id for row in reversals)


def test_cancelling_a_brand_owned_bill_un_owes_the_brand(counter):
    """The accrual is what makes SOR different, and it lives in two books: the GL
    payable control account and the vendor subledger. Both have to come back or
    Books Health reports a drift that is really a cancel half-done."""
    sale = _sell(counter, model="SOR")
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -COST_PAISE
    assert VendorLedgerEntry.objects.aggregate(t=Sum("amount"))["t"] == COST_PAISE

    sale.cancel(counter["cashier"])

    assert account_balance(GLAccount.VENDOR_PAYABLE) == 0
    assert VendorLedgerEntry.objects.aggregate(t=Sum("amount"))["t"] == 0
    # the subledger reversal is an append that names what it undoes, not an edit
    assert VendorLedgerEntry.objects.count() == 2
    assert VendorLedgerEntry.objects.filter(reverses__isnull=False).count() == 1


def test_cancelling_an_exchange_puts_both_halves_back(counter):
    """A piece out and a piece back on one document. The reversal has to run both
    ways round: the sold piece returns to the shelf, the returned piece leaves it."""
    stock_in(counter["store"], 6)
    first = counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )
    assert first.status_code == 201, first.json()
    before = _state()

    exchanged = counter["client"].post(
        SALES_URL, _exchange_payload(counter, till_seq=2), format="json"
    )
    assert exchanged.status_code == 201, exchanged.json()
    Sale.objects.get(pk=exchanged.json()["id"]).cancel(counter["cashier"])

    assert _state() == before


def test_a_damaged_return_comes_back_out_of_quarantine(counter):
    """A piece taken back damaged never reaches the shelf - it goes to quarantine -
    so its reversal must come out of quarantine and not out of on-hand. Kind is
    what says which bucket, which is why the mirror keeps the original's kind."""
    stock_in(counter["store"], 6)
    counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )
    before = _state()

    payload = _exchange_payload(counter, till_seq=2)
    payload["exchange"]["lines"][0]["condition"] = "damaged"
    exchanged = counter["client"].post(SALES_URL, payload, format="json")
    assert exchanged.status_code == 201, exchanged.json()
    assert QuarantineStock.objects.get().qty == 1

    Sale.objects.get(pk=exchanged.json()["id"]).cancel(counter["cashier"])

    assert _state() == before
    assert not QuarantineStock.objects.exists()


def test_the_projections_still_match_a_rebuild_after_a_cancel(counter):
    """`StockOnHand` is a cache of the ledger, and a reversal that moved the cache
    without appending a leg (or the other way about) would only show up here."""
    sale = _sell(counter, qty_on_shelf=4)
    sale.cancel(counter["cashier"])
    cached = _shelf()

    call_command("rebuild_stock_on_hand")

    assert _shelf() == cached


def _exchange_payload(counter, *, till_seq: int) -> dict:
    """A dearer piece out, the original piece back, on one bill."""
    dearer = 199900
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=till_seq, mrp_paise=dearer
    )
    payload["exchange"] = {
        "original": {"store": counter["store"].code, "fy": payload["fy"], "till_seq": 1},
        "lines": [
            {
                "line_no": 2,
                "direction": "return",
                "barcode": "8901000000011",
                "season": "FW25",
                "original_line": 1,
                "qty": 1,
                "refund_paise": MRP_PAISE,
                "gst_rate": "5",
                "gst_paise": gst_on(MRP_PAISE),
                "condition": "good",
                "reason": "size",
            }
        ],
    }
    payload["totals"] |= {
        "net_paise": dearer - MRP_PAISE,
        "gst_paise": gst_on(dearer) - gst_on(MRP_PAISE),
    }
    payload["tenders"] = [{"mode": "cash", "amount_paise": dearer - MRP_PAISE}]
    return payload


# --- the credit note -------------------------------------------------------


def _historical_return(counter, sale: Sale) -> tuple[Return, CreditNote]:
    """One standalone return with the note it handed over - the pre-#273 shape.

    The writer retired when return legs moved onto ordinary bills, but the rows
    are still in every store's history and are the reason the defect was found. It
    is rebuilt here through the same three calls the retired pipeline made, so the
    document under test is the one the books actually hold.
    """
    original = sale.lines.get()
    ret = Return.objects.create(
        store=counter["store"],
        fy=sale.fy,
        original_sale=sale,
        returned_at=sale.billed_at,
        created_by=counter["cashier"],
    )
    ret.post()
    line = ReturnLine.objects.create(
        return_doc=ret,
        line_no=1,
        original_line=original,
        barcode=original.barcode,
        season=original.season,
        design=original.design,
        color=original.color,
        size=original.size,
        brand=original.brand,
        item=original.item,
        hsn=original.hsn,
        qty=1,
        refund_paise=original.net_paise,
        gst_rate=original.gst_rate,
        gst_paise=original.gst_paise,
        unit_cost_paise=original.unit_cost_paise,
        cost_book=original.cost_book,
        cost_vendor=original.cost_vendor,
    )
    costed = [CostedLine(row=line, plan=plan_from_original(original))]
    post_return_value(ret, costed, counter["cashier"])
    post_stock_move(ret, counter["store"], line, counter["cashier"])
    note = CreditNote.objects.create(
        store=counter["store"],
        fy=sale.fy,
        value_paise=line.refund_paise,
        expires_on=date(2027, 1, 30),
        source_return=ret,
        created_by=counter["cashier"],
    )
    note.post()
    return ret, note


def test_cancelling_a_return_voids_the_note_it_issued(counter):
    """The defect in one sentence: the customer must not be left holding a live
    note for a refund the books have just taken back."""
    sale = _sell(counter)
    ret, note = _historical_return(counter, sale)
    assert note.status == CreditNote.Status.OPEN
    assert account_balance(GLAccount.CREDIT_NOTE_LIABILITY) == -MRP_PAISE

    ret.cancel(counter["cashier"])

    assert CreditNote.objects.get(pk=note.pk).status == CreditNote.Status.CANCELLED
    assert account_balance(GLAccount.CREDIT_NOTE_LIABILITY) == 0
    assert Return.objects.get(pk=ret.pk).docstatus == DocStatus.CANCELLED


def test_cancelling_a_return_puts_the_bill_back_where_it_was(counter):
    """The whole return, undone: revenue, tax, the piece and the note together."""
    sale = _sell(counter)
    before = _state()
    ret, _ = _historical_return(counter, sale)
    assert _state() != before

    ret.cancel(counter["cashier"])

    assert _state() == before


def test_one_piece_cannot_produce_a_second_live_note(counter):
    """The path the ticket describes, closed.

    Cancelling frees the returnable quantity - correctly, the piece is back with
    the customer - so the same line can be returned again. What must not survive
    is the first note: two live notes for one piece is money invented twice.
    """
    sale = _sell(counter)
    first, first_note = _historical_return(counter, sale)

    first.cancel(counter["cashier"])
    second, second_note = _historical_return(counter, sale)  # the quantity was freed

    live = CreditNote.objects.exclude(docstatus=DocStatus.CANCELLED)
    assert [note.pk for note in live] == [second_note.pk]
    assert CreditNote.objects.get(pk=first_note.pk).status == CreditNote.Status.CANCELLED
    assert account_balance(GLAccount.CREDIT_NOTE_LIABILITY) == -MRP_PAISE


def test_cancelling_is_refused_while_the_note_has_been_spent(counter):
    """The open money ruling, named rather than guessed at.

    A note the customer has already spent cannot simply be withdrawn, so the
    document that issued it will not cancel until #291 says what should happen.
    """
    sale = _sell(counter)
    ret, note = _historical_return(counter, sale)
    spender = _sell(counter, qty_on_shelf=1, till_seq=2)
    CreditNoteRedemption.objects.create(credit_note=note, sale=spender, amount_paise=10000)
    before = _state()

    with pytest.raises(ReversalRefused, match="partly-spent|already been spent"):
        ret.cancel(counter["cashier"])

    # nothing moved, and the document is exactly as it was: the whole cascade
    # rides inside the transition's transaction.
    assert _state() == before
    assert Return.objects.get(pk=ret.pk).docstatus == DocStatus.SUBMITTED
    assert CreditNote.objects.get(pk=note.pk).status == CreditNote.Status.OPEN


def test_a_note_spent_on_a_cancelled_bill_is_open_again(counter):
    """A redemption against a bill that was itself cancelled did not happen.

    The cancel mirrored that bill's `Dr CREDIT_NOTE_LIABILITY`, so the books have
    already handed the money back to the note; counting the redemption as well
    would show a spent note the ledger was still carrying the liability for - and
    would block the issuing document behind a spend that was already unwound.
    """
    sale = _sell(counter)
    ret, note = _historical_return(counter, sale)
    spender = _sell(counter, qty_on_shelf=1, till_seq=2)
    CreditNoteRedemption.objects.create(credit_note=note, sale=spender, amount_paise=10000)
    spender.cancel(counter["cashier"])

    fresh = CreditNote.objects.get(pk=note.pk)
    assert fresh.spent_paise == 0
    assert fresh.status == CreditNote.Status.OPEN
    listed = CreditNote.with_balance(CreditNote.objects.filter(pk=note.pk)).get()
    assert getattr(listed, CreditNote.BALANCE) == MRP_PAISE

    ret.cancel(counter["cashier"])  # no longer refused

    assert CreditNote.objects.get(pk=note.pk).status == CreditNote.Status.CANCELLED


# --- the piece sold before its paperwork -----------------------------------


def test_a_cancelled_bills_uncosted_line_is_never_swept(counter):
    """A line waiting for its price has no cost event and no stock leg, so there
    is nothing to reverse - but there is something to stop. Left waiting, the next
    PT to price the cohort would post a cost and take a piece off a shelf for a
    bill the books say never happened, days after anybody was looking.
    """
    policy = SellPolicy.current()
    policy.manual_discount_cap_percent = 100
    policy.save(update_fields=["manual_discount_cap_percent"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, barcode=UNKNOWN)
    payload["lines"][0]["season"] = ""
    payload["lines"][0]["manual_desc"] = "Blue check shirt"
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    sale = Sale.objects.get(pk=response.json()["id"])
    assert DeferredCosting.objects.get().status == DeferredCosting.Status.WAITING

    sale.cancel(counter["cashier"])
    assert DeferredCosting.objects.get().status == DeferredCosting.Status.CANCELLED
    before = _state()  # what the cancel left; the sweep must not move it

    build_piece(barcode=UNKNOWN, season="FW25", cost_paise=COST_PAISE)
    assert sweep_deferred(UNKNOWN, "FW25") == 0
    assert _state() == before
    assert not StockOnHand.objects.filter(sku_code=UNKNOWN, net_qty__lt=0).exists()


def test_a_bill_with_nothing_to_cost_still_cancels_its_money(counter):
    """Event A posted in full for a piece the books could not place, so cancelling
    has to take exactly that back - and nothing else, because event B never ran."""
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, barcode=UNKNOWN)
    payload["lines"][0]["season"] = ""
    payload["lines"][0]["manual_desc"] = "Blue check shirt"
    before = _state()
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()

    Sale.objects.get(pk=response.json()["id"]).cancel(counter["cashier"])

    assert _state() == before
    assert account_balance(GLAccount.COGS) == 0


# --- the transition itself -------------------------------------------------


def test_a_cancelled_bill_cannot_be_cancelled_twice(counter):
    """The FSM is what makes reversing exactly-once, without a marker on any leg:
    a cancelled row is frozen, so there is no second cancel to double-reverse."""
    sale = _sell(counter)
    sale.cancel(counter["cashier"])
    after = _state()

    with pytest.raises(Exception, match="cancelled|frozen"):
        Sale.objects.get(pk=sale.pk).cancel(counter["cashier"])

    assert _state() == after


def test_the_reversal_names_who_cancelled(counter):
    """Rule 10 - every action has an actor, and a reversal is an action."""
    sale = _sell(counter)

    sale.cancel(counter["cashier"])

    mirrors = GLEntry.objects.filter(memo=f"Reversal of {sale.doc_number}")
    assert mirrors.exists()
    assert {leg.posted_by_id for leg in mirrors} == {counter["cashier"].id}


def test_the_cancelled_bills_lines_are_no_longer_returnable(counter):
    """Already asserted from the API side in the accept suite; repeated here
    against the reversal, because the two now happen in one transaction and the
    freeing is only safe *because* the note is voided with it."""
    sale = _sell(counter)
    sale.cancel(counter["cashier"])

    assert (
        SaleLine.objects.filter(sale=sale).exclude(sale__docstatus=DocStatus.CANCELLED).count() == 0
    )
