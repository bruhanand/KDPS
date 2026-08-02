"""The value a bill posts (#178, D10 api-contract §Postings).

Money is asserted as **golden files**, not as inline arithmetic. A bill's postings
are a dozen legs whose amounts follow from each other, and an inline assertion of
one leg proves nothing about the other eleven; a checked-in file shows the whole
voucher at once, so a diff on it is a sentence about which rupee moved and why.
The files live in `golden/sale-postings/` and are rendered by `_render` below -
account, side, exact paise, and the dimensions every margin question is asked by.

What each file pins:

  · **one bill per commercial model** - Outright and Correction come out of our own
    inventory; SOR and Consignment were never ours, so they raise what we owe the
    brand at the settlement rate and take the memo stock off,
  · **split tender** - three ways of paying one bill, each into its own account,
  · **exchange** - a piece back and a piece out on one balanced document, with the
    cost side reversed at the *original's* frozen cost,
  · **rounding** - the line that makes a bill come to whole rupees, on either side.

Beside the files, the properties no golden file can state: that the books tie after
every one of them, that a deliberately broken posting is refused outright rather
than written half-way, that a discount never moves what a brand is owed, and that
nothing can edit a posted bill.
"""

from __future__ import annotations

from pathlib import Path

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

from core.documents import DocStatus
from core.gl import GLAccount, GLEntry, account_balance, trial_balance
from core.posting import UnbalancedError, cr, dr, post_entries
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from masters.models import Brand
from sell.models import DeferredCosting, Sale, SaleLine
from sell.services.postings import resolve_cost_plan

GOLDEN = Path(__file__).parent / "golden" / "sale-postings"


@pytest.fixture
def counter(db):
    """A store that can sell, with an Outright piece on the shelf."""
    store = build_store()
    cashier = build_cashier(store)
    return {
        "store": store,
        "cashier": cashier,
        "manager": build_manager(store),
        "salesman": build_salesman(store),
        "client": client_for(cashier),
    }


def _sell(counter, *, model="Outright", qty_on_shelf=3, **payload_kwargs):
    """Shelve a piece on `model` and bill it. Returns the response."""
    stock_in(counter["store"], qty_on_shelf, model=model)
    if model in {"SOR", "Consignment"}:
        build_supplier(build_brand(model))
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, **payload_kwargs)
    return counter["client"].post(SALES_URL, payload, format="json")


# --- the golden files ------------------------------------------------------


#: The two vouchers a bill posts, in the order it posts them.
EVENTS = ("A · money", "B · cost")


def _render(sale: Sale) -> str:
    """A bill's whole value posting, as the text the golden files hold.

    Legs come back in insertion order (`id`), and `post_entries` numbers each
    voucher's legs from 1 - so a `line_no` of 1 is where the next event starts.
    That is what separates the money side from the cost side without either of
    them carrying a label the ledger does not actually store.

    Each event is footed with its own Σ, not just the document, because that is
    the real invariant: two balanced vouchers, not one lucky total.
    """
    lines = [f"{sale.doc_number}"]
    events: list[list[GLEntry]] = []
    for leg in GLEntry.objects.filter(doc_number=sale.doc_number).order_by("id"):
        if leg.line_no == 1:
            events.append([])
        events[-1].append(leg)
    assert len(events) <= len(EVENTS), f"{sale.doc_number} posted {len(events)} vouchers"
    for name, legs in zip(EVENTS, events, strict=False):
        lines.append(f"  event {name}")
        for leg in legs:
            side = "dr" if leg.amount > 0 else "cr"
            party = f" [{leg.party_type}:{leg.party_code}]" if leg.party_code else ""
            dims = " · ".join(p for p in (leg.brand, leg.season) if p)
            lines.append(
                f"    {side} {leg.account:<22}{abs(leg.amount):>10}"
                f"{('  ' + dims) if dims else ''}{party}"
            )
        lines.append(f"    Σ {sum(leg.amount for leg in legs)}")
    return "\n".join(lines) + "\n"


def _assert_golden(sale: Sale, name: str) -> None:
    """Compare a bill's postings with the checked-in file, or write it first.

    Regenerating is deliberately a hand action (`KDPS_WRITE_GOLDEN=1`): a golden
    file that rewrites itself on failure is not a golden file, it is a log.
    """
    import os

    rendered = _render(sale)
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("KDPS_WRITE_GOLDEN") == "1":  # pragma: no cover - authoring aid
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
    assert path.exists(), f"missing golden file {path}"
    assert rendered == path.read_text(), (
        f"postings for {name} moved:\n\n--- expected ---\n{path.read_text()}"
        f"\n--- actual ---\n{rendered}"
    )


@pytest.mark.parametrize(
    ("model", "name"),
    [
        ("Outright", "outright-cash"),
        ("Correction", "correction-cash"),
        ("SOR", "sor-cash"),
        ("Consignment", "consignment-cash"),
    ],
)
def test_one_bill_per_commercial_model(counter, model, name):
    """The same shirt, sold four ways, out of four different books."""
    response = _sell(counter, model=model)

    assert response.status_code == 201, response.json()
    _assert_golden(Sale.objects.get(pk=response.json()["id"]), name)
    assert trial_balance() == 0


def test_a_bill_paid_three_ways(counter):
    """Split tender: each way of paying lands in its own account."""
    stock_in(counter["store"], 3)
    net = MRP_PAISE
    payload = bill_payload(
        counter["store"],
        counter["salesman"],
        till_seq=1,
        tenders=[
            {"mode": "cash", "amount_paise": 50000},
            {"mode": "card", "amount_paise": 60000},
            upi_tender(net - 110000),
        ],
    )
    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    _assert_golden(Sale.objects.get(pk=response.json()["id"]), "split-tender")
    assert trial_balance() == 0


@pytest.mark.parametrize(
    ("mrp", "charged", "name"),
    [
        (149937, 149900, "rounded-down"),
        (149963, 150000, "rounded-up"),
    ],
)
def test_a_bill_rounded_to_whole_rupees(counter, mrp, charged, name):
    """The rounding line, on both sides of it.

    A bill whose lines come to ₹1,499.37 is charged ₹1,499 and the shop is 37 paise
    down; one that comes to ₹1,499.63 is charged ₹1,500 and the shop is 37 paise up.
    Same account either way, and the sign is which - revenue is always recognised
    at what the lines say, never at the rounded figure.
    """
    stock_in(counter["store"], 3)
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=1, mrp_paise=mrp, gst_rate="5"
    )
    payload["totals"] |= {"net_paise": charged, "round_paise": charged - mrp}
    payload["tenders"] = [{"mode": "cash", "amount_paise": charged}]
    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    _assert_golden(Sale.objects.get(pk=response.json()["id"]), name)
    assert trial_balance() == 0


def test_an_exchange_posts_one_balanced_document(counter):
    """A piece back and a piece out, on one bill.

    The return leg gives back the revenue and the tax the customer actually paid,
    and puts the cost back into the book it came out of; the sale leg is ordinary.
    What the customer hands over is the difference, and it is the only cash that
    moves.

    The cohort is deliberately **re-priced between the two bills** - the next
    delivery of the same shirt cost ₹800 - so the two cost legs are different
    numbers. Reversing at ₹700 is the whole assertion: an exchange unwinds what the
    piece cost when it was sold, and a return valued at today's cost of record
    would leave the difference stranded in inventory forever.
    """
    stock_in(counter["store"], 4)
    first = counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )
    assert first.status_code == 201, first.json()
    build_piece(cost_paise=80000)  # the next delivery cost more

    dearer = 199900
    refund = MRP_PAISE
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=2, mrp_paise=dearer)
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
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": gst_on(refund),
                "condition": "good",
                "reason": "size",
            }
        ],
    }
    payload["totals"] |= {
        "net_paise": dearer - refund,
        "gst_paise": gst_on(dearer) - gst_on(refund),
    }
    payload["tenders"] = [{"mode": "cash", "amount_paise": dearer - refund}]
    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    _assert_golden(Sale.objects.get(pk=response.json()["id"]), "exchange")
    assert trial_balance() == 0


def test_an_exchange_of_brand_owned_stock_reverses_the_accrual(counter):
    """Giving a brand's piece back reduces what we owe that brand, not our cost."""
    build_supplier(build_brand("SOR"))
    stock_in(counter["store"], 4, model="SOR")
    first = counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )
    assert first.status_code == 201, first.json()
    owed_after_sale = account_balance(GLAccount.VENDOR_PAYABLE)

    refund = MRP_PAISE
    dearer = 199900
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=2, mrp_paise=dearer)
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
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": gst_on(refund),
                "condition": "good",
                "reason": "size",
            }
        ],
    }
    payload["totals"] |= {
        "net_paise": dearer - refund,
        "gst_paise": gst_on(dearer) - gst_on(refund),
    }
    payload["tenders"] = [{"mode": "cash", "amount_paise": dearer - refund}]
    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    # One piece out, one piece back, at the same settlement rate: the brand is owed
    # exactly what it was owed after the first bill.
    assert account_balance(GLAccount.VENDOR_PAYABLE) == owed_after_sale
    assert trial_balance() == 0


# --- the money side --------------------------------------------------------


def test_revenue_is_net_of_the_tax_the_customer_paid(counter):
    _sell(counter)

    revenue = -account_balance(GLAccount.SALES_REVENUE)
    output_gst = -account_balance(GLAccount.OUTPUT_GST)
    assert output_gst == gst_on(MRP_PAISE)
    # Base plus tax is exactly what was paid - no paisa is rounded away between
    # the printed bill and the ledger.
    assert revenue + output_gst == MRP_PAISE
    assert account_balance(GLAccount.CASH) == MRP_PAISE


def test_a_credit_note_tender_extinguishes_the_liability_it_raised(counter):
    """Spending a note takes the liability off, and no cash comes in for it."""
    stock_in(counter["store"], 4)
    # A bill that nets negative issues a note; the next bill spends it.
    dearer = MRP_PAISE
    first = counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )
    assert first.status_code == 201
    cheaper = 50000
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=2, mrp_paise=cheaper)
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
                "refund_paise": dearer,
                "gst_rate": "5",
                "gst_paise": gst_on(dearer),
                "condition": "good",
                "reason": "size",
            }
        ],
    }
    payload["totals"] |= {
        "gross_paise": cheaper,
        "net_paise": cheaper - dearer,
        "gst_paise": gst_on(cheaper) - gst_on(dearer),
    }
    payload["tenders"] = []
    issued = counter["client"].post(SALES_URL, payload, format="json")
    assert issued.status_code == 201, issued.json()
    note = Sale.objects.get(pk=issued.json()["id"]).credit_notes_issued.get()
    _assert_golden(Sale.objects.get(pk=issued.json()["id"]), "credit-note-issued")
    owed_to_customer = -account_balance(GLAccount.CREDIT_NOTE_LIABILITY)
    # The leg is the note, to the paisa: the bill's own liability and the document
    # it minted cannot say different numbers.
    assert owed_to_customer == note.value_paise

    third = bill_payload(
        counter["store"], counter["salesman"], till_seq=3, mrp_paise=note.value_paise
    )
    third["tenders"] = [
        {
            "mode": "credit_note",
            "amount_paise": note.value_paise,
            "credit_note": note.doc_number,
        }
    ]
    spent = counter["client"].post(SALES_URL, third, format="json")

    assert spent.status_code == 201, spent.json()
    _assert_golden(Sale.objects.get(pk=spent.json()["id"]), "credit-note-redeemed")
    assert account_balance(GLAccount.CREDIT_NOTE_LIABILITY) == 0
    # A note is not money: no cash row was written for it.
    assert not CashLedgerEntry.objects.filter(mode="credit_note").exists()
    assert trial_balance() == 0


def test_each_tender_is_a_cash_ledger_receipt_under_the_bills_own_number(counter):
    """The collections read from one place, and point back at the bill."""
    stock_in(counter["store"], 3)
    payload = bill_payload(
        counter["store"],
        counter["salesman"],
        till_seq=1,
        tenders=[
            {"mode": "cash", "amount_paise": 49900},
            {"mode": "card", "amount_paise": MRP_PAISE - 49900},
        ],
    )
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()

    rows = {r.account: r for r in CashLedgerEntry.objects.all()}
    assert set(rows) == {"CASH", "CARD"}
    assert rows["CASH"].amount == 49900
    assert rows["CARD"].amount == MRP_PAISE - 49900
    assert all(r.doc_number == response.json()["doc_number"] for r in rows.values())
    assert all(r.kind == CashLedgerEntry.Kind.RECEIPT for r in rows.values())


def test_a_card_sale_does_not_report_the_books_as_broken(counter):
    """Books-health ties a card bill: the subledger and the clearing account agree.

    A card swipe writes a CARD receipt row while the GL sends it to CARD_CLEARING.
    Reconciling the cash subledger against the CASH account alone would have called
    that a break in the books after every card sale.
    """
    stock_in(counter["store"], 3)
    payload = bill_payload(
        counter["store"],
        counter["salesman"],
        till_seq=1,
        tenders=[{"mode": "card", "amount_paise": MRP_PAISE}],
    )
    assert counter["client"].post(SALES_URL, payload, format="json").status_code == 201

    from finledger.health import _reconciliation

    balances = {
        code: account_balance(code)
        for code in (
            GLAccount.VENDOR_PAYABLE,
            GLAccount.CASH,
            GLAccount.CARD_CLEARING,
            GLAccount.UPI_CLEARING,
        )
    }
    assert _reconciliation(balances)["reconciled"] is True


# --- the cost side ---------------------------------------------------------


def test_owned_stock_comes_out_of_our_own_inventory(counter):
    _sell(counter, model="Outright")

    assert account_balance(GLAccount.COGS) == COST_PAISE
    assert account_balance(GLAccount.INVENTORY) == -COST_PAISE
    assert account_balance(GLAccount.VENDOR_PAYABLE) == 0
    assert account_balance(GLAccount.SOR_STOCK) == 0


def test_brand_owned_stock_raises_what_we_owe_the_brand(counter):
    _sell(counter, model="SOR")

    assert account_balance(GLAccount.COGS) == COST_PAISE
    # Never INVENTORY: the piece was never on our balance sheet.
    assert account_balance(GLAccount.INVENTORY) == 0
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -COST_PAISE
    # And the memo pair the inward raised comes off with the piece.
    assert account_balance(GLAccount.SOR_STOCK) == -COST_PAISE
    assert account_balance(GLAccount.SOR_CONTRA) == COST_PAISE


def test_the_accrual_names_the_vendor_it_is_owed_to(counter):
    _sell(counter, model="Consignment")

    leg = GLEntry.objects.get(account=GLAccount.VENDOR_PAYABLE)
    assert leg.party_type == "vendor"
    assert leg.party_code == "ARVIND"
    # And the vendor's own account shows it, so the subledger still ties to the
    # payable control account.
    row = VendorLedgerEntry.objects.get(kind=VendorLedgerEntry.Kind.BILL)
    assert row.amount == COST_PAISE
    assert row.vendor.code == "ARVIND"


def test_a_discount_never_moves_what_the_brand_is_owed(counter):
    """The settlement rate, never the discounted price - the whole point of #178.

    A brand-owned piece sold at half off still owes the brand the same rupees: the
    discount is KDPS's to give and KDPS's to lose. Posting the payable from the
    selling price would hand the brand the shop's own markdown.
    """
    build_supplier(build_brand("SOR"))
    stock_in(counter["store"], 3, model="SOR")
    half_off = MRP_PAISE // 2
    payload = bill_payload(
        counter["store"],
        counter["salesman"],
        till_seq=1,
        disc_paise=half_off,
        override={"user_id": counter["manager"].id, "kind": "over_cap_discount"},
    )
    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -COST_PAISE
    assert account_balance(GLAccount.COGS) == COST_PAISE


def test_a_piece_the_books_cannot_price_posts_money_but_no_cost(counter):
    """Sold before inward: the customer's money is a fact, the cost is not yet."""
    stock_in(counter["store"], 3)
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=1, barcode="8909999999999"
    )
    payload["lines"][0]["manual_desc"] = "Grey trouser, no tag"
    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    assert account_balance(GLAccount.CASH) == MRP_PAISE
    assert account_balance(GLAccount.COGS) == 0
    assert account_balance(GLAccount.INVENTORY) == 0
    waiting = DeferredCosting.objects.get()
    assert waiting.reason == DeferredCosting.Reason.UNPRICED
    assert trial_balance() == 0


def test_a_brand_the_masters_never_heard_of_waits_instead_of_guessing(counter):
    """A priced piece with no brand row is not "ours" - it is unplaced.

    Its stock still moves (the piece left the shelf) but its value waits, because
    booking it into INVENTORY would understate what a brand may be owed and
    overstate what we hold.
    """
    stock_in(counter["store"], 3)
    Brand.objects.all().delete()
    response = counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )

    assert response.status_code == 201, response.json()
    assert account_balance(GLAccount.CASH) == MRP_PAISE  # the money side posted
    assert account_balance(GLAccount.COGS) == 0  # the cost side did not
    waiting = DeferredCosting.objects.get()
    assert waiting.reason == DeferredCosting.Reason.MODEL_UNKNOWN
    assert SaleLine.objects.get().costing_status == SaleLine.CostingStatus.DEFERRED
    assert trial_balance() == 0


def test_brand_owned_stock_with_no_supplier_of_record_waits(counter):
    """A payable needs somebody to owe it to; nobody is not a guess we make."""
    build_brand("SOR")  # no vendor carries it
    stock_in(counter["store"], 3, model="SOR")
    response = counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )

    assert response.status_code == 201, response.json()
    assert account_balance(GLAccount.VENDOR_PAYABLE) == 0
    assert DeferredCosting.objects.get().reason == DeferredCosting.Reason.VENDOR_UNKNOWN
    assert trial_balance() == 0


def test_an_exchange_unwinds_the_model_the_sale_posted_not_todays(counter):
    """The defect this snapshot exists to stop.

    A brand-owned piece is sold; the brand is then re-negotiated to Outright, which
    is an ordinary edit an Operations Head makes in Master Data. The exchange must
    still put the payable back - the money is owed to the brand for the piece that
    actually sold - and must not credit an inventory account KDPS never debited.
    Re-deriving from the live Brand row would do exactly that, and the trial balance
    would stay at zero throughout, so nothing downstream would ever report it.
    """
    build_supplier(build_brand("SOR"))
    stock_in(counter["store"], 4, model="SOR")
    first = counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )
    assert first.status_code == 201, first.json()
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -COST_PAISE

    build_brand("Outright")  # the terms change after the sale

    dearer = 199900
    refund = MRP_PAISE
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=2, mrp_paise=dearer)
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
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": gst_on(refund),
                "condition": "good",
                "reason": "size",
            }
        ],
    }
    payload["totals"] |= {
        "net_paise": dearer - refund,
        "gst_paise": gst_on(dearer) - gst_on(refund),
    }
    payload["tenders"] = [{"mode": "cash", "amount_paise": dearer - refund}]
    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    returned = SaleLine.objects.get(line_no=2)
    assert returned.cost_book == SaleLine.CostBook.BRAND
    # The accrual is back off: the brand-owned piece came back, whatever the brand's
    # terms say today.
    assert account_balance(GLAccount.VENDOR_PAYABLE) == 0
    assert account_balance(GLAccount.SOR_STOCK) == 0
    # And the new piece, sold under the new terms, is ours.
    assert account_balance(GLAccount.INVENTORY) == -COST_PAISE
    assert trial_balance() == 0


def test_a_sold_line_records_which_book_priced_it(counter):
    """The snapshot is on the line, not looked up - Rule 3."""
    _sell(counter, model="SOR")
    line = SaleLine.objects.get()

    assert line.cost_book == SaleLine.CostBook.BRAND
    assert line.cost_vendor is not None and line.cost_vendor.code == "ARVIND"


def test_a_line_the_books_could_not_place_records_no_book(counter):
    """Blank is what an exchange later reads as "there was nothing to reverse"."""
    stock_in(counter["store"], 3)
    Brand.objects.all().delete()
    assert (
        counter["client"]
        .post(
            SALES_URL,
            bill_payload(counter["store"], counter["salesman"], till_seq=1),
            format="json",
        )
        .status_code
        == 201
    )

    line = SaleLine.objects.get()
    assert line.cost_book == ""
    assert line.cost_vendor is None


def test_two_suppliers_for_one_brand_cannot_be_chosen_between(counter):
    """`supplier_of` refuses rather than picking the first row."""
    brand = build_brand("SOR")
    build_supplier(brand, code="ARVIND")
    build_supplier(brand, code="MADURA")
    build_piece(model="SOR")

    plan = resolve_cost_plan(
        brand=brand.name, barcode="8901000000011", season="FW25", unit_cost_paise=COST_PAISE
    )
    assert plan.deferral == DeferredCosting.Reason.VENDOR_UNKNOWN


def _inward_under(store, vendor, *, number: str, barcode="8901000000011", season="FW25"):
    """One PT inward of the fixture cohort, booked against `vendor`.

    Written straight to the ledger rather than through a helper because what the
    test needs is exactly what `supplier_of` reads: a `PT_INWARD` leg carrying a
    booking. The projection is beside the point here.
    """
    from masters.models import Season
    from stockledger.models import StockLedgerEntry
    from vendors.models import Booking

    booking = Booking.objects.create(
        number=number,
        vendor=vendor,
        brand=Brand.objects.get(code="mufti"),
        season=Season.objects.get(code="FW25"),
    )
    return StockLedgerEntry.objects.create(
        store=store,
        gstin=store.gstin,
        qty=1,
        amount=COST_PAISE,
        sku_code=barcode,
        season=season,
        brand="MUFTI",
        kind=StockLedgerEntry.Kind.PT_INWARD,
        doc_number=f"26-27/SEL-DEO/PT/{number}",
        line_no=1,
        booking=booking,
    )


def test_the_inward_names_the_supplier_even_when_the_brand_has_two(counter):
    """The piece knows better than the brand: one booked inward decides."""
    brand = build_brand("SOR")
    arvind = build_supplier(brand, code="ARVIND")
    build_supplier(brand, code="MADURA")
    build_piece(model="SOR")
    _inward_under(counter["store"], arvind, number="BK-1")

    plan = resolve_cost_plan(
        brand=brand.name, barcode="8901000000011", season="FW25", unit_cost_paise=COST_PAISE
    )
    assert plan.vendor == arvind


def test_a_cohort_inwarded_under_two_vendors_defers_rather_than_guessing(counter):
    """Two vendors' inwards on one cohort: nobody can say whose piece just sold.

    The pieces are indistinguishable once they share a (barcode, season), so the
    latest booking is not an answer - it is a guess with a counterparty on it,
    and a payable to the wrong vendor is invisible to the trial balance and the
    subledger tie alike. The line waits for a human instead.
    """
    brand = build_brand("SOR")
    arvind = build_supplier(brand, code="ARVIND")
    madura = build_supplier(brand, code="MADURA")
    build_piece(model="SOR")
    _inward_under(counter["store"], arvind, number="BK-1")
    _inward_under(counter["store"], madura, number="BK-2")

    plan = resolve_cost_plan(
        brand=brand.name, barcode="8901000000011", season="FW25", unit_cost_paise=COST_PAISE
    )
    assert plan.vendor is None
    assert plan.deferral == DeferredCosting.Reason.VENDOR_UNKNOWN


def test_restocking_from_the_same_vendor_still_posts_to_that_vendor(counter):
    """Two inwards, one vendor: no ambiguity, no deferral."""
    brand = build_brand("SOR")
    arvind = build_supplier(brand, code="ARVIND")
    build_piece(model="SOR")
    _inward_under(counter["store"], arvind, number="BK-1")
    _inward_under(counter["store"], arvind, number="BK-2")

    plan = resolve_cost_plan(
        brand=brand.name, barcode="8901000000011", season="FW25", unit_cost_paise=COST_PAISE
    )
    assert plan.vendor == arvind


def test_a_cancelled_exchange_gives_the_returnable_quantity_back(counter):
    """A cancelled bill's returns never happened, so they cannot spend the quota.

    The counter takes an exchange, realises the bill was wrong, and cancels it by
    the kernel's own transition. The customer still holds the piece and the
    receipt; the next attempt at the same return must be accepted. Counting the
    cancelled bill's return line against the original would refuse it with
    ALREADY_RETURNED - a refund path the books closed over a bill they themselves
    say never happened.
    """
    stock_in(counter["store"], 6)
    first = counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=1), format="json"
    )
    assert first.status_code == 201, first.json()

    def exchange_payload(till_seq: int):
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

    exchanged = counter["client"].post(SALES_URL, exchange_payload(2), format="json")
    assert exchanged.status_code == 201, exchanged.json()
    Sale.objects.get(pk=exchanged.json()["id"]).cancel()

    again = counter["client"].post(SALES_URL, exchange_payload(3), format="json")
    assert again.status_code == 201, again.json()


# --- the invariants no golden file can state -------------------------------


def test_the_books_tie_after_every_bill_shape(counter):
    """Σ = 0 across a mixed day, not just after one clean sale."""
    stock_in(counter["store"], 10)
    for seq, tenders in enumerate(
        [
            [{"mode": "cash", "amount_paise": MRP_PAISE}],
            [{"mode": "card", "amount_paise": MRP_PAISE}],
            [upi_tender(MRP_PAISE)],
            [
                {"mode": "cash", "amount_paise": 1},
                upi_tender(MRP_PAISE - 1),
            ],
        ],
        start=1,
    ):
        response = counter["client"].post(
            SALES_URL,
            bill_payload(counter["store"], counter["salesman"], till_seq=seq, tenders=tenders),
            format="json",
        )
        assert response.status_code == 201, response.json()
        assert trial_balance() == 0


def test_a_posting_that_does_not_balance_is_refused_and_writes_nothing(counter):
    """Balanced-or-fail, proven against a real bill's own document.

    The deliberately broken case the ticket asks for: an unbalanced set on a live
    Sale is refused by the engine, and the ledger is exactly as it was - so no
    posting path can ever leave a bill half-written.
    """
    _sell(counter)
    sale = Sale.objects.get()
    before = list(GLEntry.objects.values_list("id", flat=True))

    with pytest.raises(UnbalancedError):
        post_entries(
            sale,
            [dr(GLAccount.CASH, 100000), cr(GLAccount.SALES_REVENUE, 99999)],
            posted_by=counter["cashier"],
        )

    assert list(GLEntry.objects.values_list("id", flat=True)) == before
    assert trial_balance() == 0


def test_a_bill_posts_two_events_under_one_number(counter):
    """Two vouchers, one document: the money side and the cost side.

    Separate because a bill can have a real money side and no costable line at
    all - one voucher would have to either refuse the money or invent the cost.
    """
    _sell(counter)
    sale = Sale.objects.get()

    legs = list(GLEntry.objects.filter(doc_number=sale.doc_number).order_by("id"))
    assert [leg.line_no for leg in legs].count(1) == 2
    assert sum(leg.amount for leg in legs) == 0


def test_every_leg_names_the_registration_it_was_billed_under(counter):
    """Bihar and Jharkhand are separate persons; a leg that cannot say which is
    no use to either return."""
    _sell(counter)
    sale = Sale.objects.get()

    legs = GLEntry.objects.filter(doc_number=sale.doc_number)
    assert legs.exists()
    for leg in legs:
        assert leg.store_id == counter["store"].id
        assert leg.gstin_id == counter["store"].gstin_id


def test_a_posted_bill_cancels_only_by_the_kernels_own_transition(counter):
    """No edit path exists, and the database is what says so (A7).

    Correction-by-reversal: the one move a submitted bill has left is to
    cancelled, and every other column change is refused by the FSM trigger - so a
    posted bill's postings can never be quietly re-based under them.
    """
    _sell(counter)
    sale = Sale.objects.get()
    assert sale.docstatus == DocStatus.SUBMITTED

    sale.net_paise = 1
    with pytest.raises(Exception, match="immutable|forbidden|docstatus"):
        sale.save(update_fields=["net_paise"])

    fresh = Sale.objects.get(pk=sale.pk)
    fresh.cancel()
    assert Sale.objects.get(pk=sale.pk).docstatus == DocStatus.CANCELLED
