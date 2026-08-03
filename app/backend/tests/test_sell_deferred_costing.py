"""Selling a piece before its paperwork, and paying off what that owes (#186).

The bargain grill Q5 struck is that the customer is never the one who waits. A
scan that finds nothing becomes a manual line, the bill prints, the money side
posts - and the *cost* side is parked in `sell_deferredcosting` because there is
no cost of record to post it at. Rule 5 (nothing at nought) and Rule 8 (nothing
blocked) both survive because of that parking.

This suite is about the second half: what happens when the paperwork lands. It
asserts the mechanism from three angles.

  · **The release itself**, as a golden file. A late cost event is two vouchers
    under one bill number written days apart, and the only thing that tells them
    apart is `against_voucher` - so what posts is pinned as text, not as one
    arithmetic assertion that would pass on eleven wrong legs.
  · **The three waits and their two doors.** A price arrives by PT; a brand and a
    supplier arrive by master data, and no PT will ever bring them. A row that
    learns something without becoming postable is re-labelled rather than posted.
  · **Nothing at nought, on any path.** The property that makes the whole design
    honest, asserted against the ledger rather than against the code that writes
    it.

The GST-recognition side of sold-before-PT stays CA-gated (CONTEXT.md); nothing
here encodes a ruling on it.
"""

from __future__ import annotations

import os
from datetime import timedelta
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
    stock_in,
)
from django.utils import timezone

from core.gl import GLEntry, trial_balance
from masters.models import Brand, Cohort, Season, Sku
from sell.models import ContinuityFlag, DeferredCosting, Sale, SaleLine, SellPolicy
from sell.services.costing_sweep import age_deferred, sweep_deferred
from stockledger.models import StockLedgerEntry, StockOnHand
from vendors.models import Vendor

GOLDEN = Path(__file__).parent / "golden" / "sale-postings"

#: A barcode the books have never heard of, which is the whole point of it.
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


def _sell_unknown(counter, *, till_seq: int = 1, qty: int = 1) -> Sale:
    """Bill a piece nothing in the books can place, the way the till does it."""
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=till_seq, barcode=UNKNOWN, qty=qty
    )
    payload["lines"][0]["season"] = ""
    payload["lines"][0]["manual_desc"] = "Blue check shirt, tag says 1499"
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    return Sale.objects.get(pk=response.json()["id"])


def _inward(*, model: str = "Outright", cost_paise: int = COST_PAISE) -> Cohort:
    """What a PT does to the masters: it prices the cohort.

    The sweep hangs off that fact rather than off the PT document, so this is the
    honest minimum - and it is what `stockledger.posting._register_identity`
    actually writes at the end of a real post.
    """
    return build_piece(barcode=UNKNOWN, season="FW25", cost_paise=cost_paise, model=model)


#: A brand a PT can name and the masters have never been told about.
GHOST = "GHOSTBRAND"


def _inward_of_an_unknown_brand(*, season: str = "FW25", cost_paise: int = COST_PAISE) -> Cohort:
    """A PT that prices the piece and names a brand nobody has set up.

    Realistic rather than contrived: a new label's first delivery arrives before
    anybody records its commercial terms, and the file says what it says.
    """
    sku, _ = Sku.objects.update_or_create(
        barcode=UNKNOWN,
        defaults={
            "design": "SHIRT-99",
            "color": "NAVY",
            "size": "M",
            "brand": GHOST,
            "item": "Shirt",
            "hsn": "6205",
            "mrp_paise": MRP_PAISE,
        },
    )
    cohort, _ = Cohort.objects.update_or_create(
        barcode=UNKNOWN,
        season=season,
        defaults={"sku": sku, "unit_cost_paise": cost_paise, "mrp_paise": MRP_PAISE},
    )
    return cohort


# --- the bill that could not be costed -------------------------------------


def test_a_bill_with_nothing_to_cost_still_posts_its_money(counter):
    """Rule 8: the customer's money is a fact whatever the books know about the
    piece, so event A posts in full and only event B waits."""
    sale = _sell_unknown(counter)

    line = SaleLine.objects.get()
    assert line.sold_before_inward is True
    assert line.costing_status == SaleLine.CostingStatus.DEFERRED
    assert line.manual_desc == "Blue check shirt, tag says 1499"
    # The money side is whole: the customer paid, and that posted.
    assert GLEntry.objects.filter(doc_number=sale.doc_number, account="CASH").exists()
    # Nothing at nought, on either ledger.
    assert not GLEntry.objects.filter(doc_number=sale.doc_number, account="COGS").exists()
    assert not StockLedgerEntry.objects.filter(doc_number=sale.doc_number).exists()
    assert DeferredCosting.objects.get().reason == DeferredCosting.Reason.UNPRICED
    assert trial_balance() == 0


# --- the price arriving ----------------------------------------------------


def test_the_pt_that_prices_the_cohort_releases_the_line(counter):
    """The first door: an inward prices the piece, and the sweep pays off the
    cost event and the stock leg that were both waiting on it."""
    sale = _sell_unknown(counter)

    _inward()

    row = DeferredCosting.objects.get()
    assert row.status == DeferredCosting.Status.POSTED
    assert row.posted_doc_number == sale.doc_number
    line = SaleLine.objects.get()
    assert line.unit_cost_paise == COST_PAISE
    assert line.costing_status == SaleLine.CostingStatus.POSTED
    assert line.cost_book == SaleLine.CostBook.OWN
    assert trial_balance() == 0


def test_the_late_cost_event_names_the_bill_it_belongs_to(counter):
    """`against_voucher` is the only thing separating a cost leg written on the
    day from one written three days later under the same bill number."""
    sale = _sell_unknown(counter)

    _inward()

    late = GLEntry.objects.filter(doc_number=sale.doc_number, account="COGS")
    assert late.count() == 1
    assert late.get().against_voucher == sale.doc_number
    # The money event, posted on the day, carries no such marker.
    assert GLEntry.objects.get(doc_number=sale.doc_number, account="CASH").against_voucher == ""


def test_the_piece_only_leaves_the_shelf_when_the_sweep_posts_it(counter):
    """A piece that was never inwarded cannot come off a shelf it was never on -
    so the movement is the sweep's to write, and it writes it exactly once."""
    sale = _sell_unknown(counter, qty=2)
    assert not StockLedgerEntry.objects.filter(sku_code=UNKNOWN).exists()

    _inward()

    sold = StockLedgerEntry.objects.get(
        sku_code=UNKNOWN, kind=StockLedgerEntry.Kind.SALE_OUT, doc_number=sale.doc_number
    )
    assert sold.qty == -2
    assert sold.amount == -2 * COST_PAISE
    # And the shelf goes negative rather than refusing: the pieces are in the
    # customer's hands, so the count was wrong (grill Q5).
    assert StockOnHand.objects.get(store=counter["store"], sku_code=UNKNOWN).net_qty == -2


def test_a_second_pt_for_the_same_cohort_does_not_pay_twice(counter):
    """The sweep fires once per valued row of every PT, so a re-post of the same
    cohort is the ordinary case and must be a no-op."""
    sale = _sell_unknown(counter)
    _inward()

    _inward()
    Cohort.objects.filter(barcode=UNKNOWN).update(unit_cost_paise=COST_PAISE + 1000)
    sweep_deferred(UNKNOWN, "FW25")

    assert GLEntry.objects.filter(doc_number=sale.doc_number, account="COGS").count() == 1
    assert (
        StockLedgerEntry.objects.filter(
            sku_code=UNKNOWN, kind=StockLedgerEntry.Kind.SALE_OUT
        ).count()
        == 1
    )
    # And the re-price never restates what the posted movement was worth (Rule 3).
    assert SaleLine.objects.get().unit_cost_paise == COST_PAISE


def test_a_line_billed_with_no_season_is_released_by_the_cohort_that_prices_it(counter):
    """The till often has no season for a piece it has never seen; the row waits
    for *any* price for the barcode, and takes the description with it."""
    _sell_unknown(counter)
    assert SaleLine.objects.get().season == ""

    _inward()

    line = SaleLine.objects.get()
    assert line.season == "FW25"
    assert line.brand == "MUFTI"
    assert line.design == "SHIRT-01"


# --- the masters arriving --------------------------------------------------


def test_a_priced_piece_whose_brand_is_unknown_waits_for_the_masters(counter):
    """The books can say what it cost and not whose it was, and `None` is not
    "ours" - booking a brand's stock into INVENTORY is the 30 June defect."""
    stock_in(counter["store"], 3)
    Brand.objects.filter(name="MUFTI").delete()
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    row = DeferredCosting.objects.get()
    assert row.reason == DeferredCosting.Reason.MODEL_UNKNOWN
    # Priced, so the piece *did* leave the shelf - only its value is missing.
    assert StockLedgerEntry.objects.filter(kind=StockLedgerEntry.Kind.SALE_OUT).exists()
    assert not GLEntry.objects.filter(account="COGS").exists()


def test_adding_the_brand_releases_the_line_without_moving_stock_twice(counter):
    """The second door. No PT will ever release this row - it is waiting on
    somebody typing a brand into the masters, and that edit is the trigger."""
    stock_in(counter["store"], 3)
    Brand.objects.filter(name="MUFTI").delete()
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    response = counter["client"].post(SALES_URL, payload, format="json")
    sale = Sale.objects.get(pk=response.json()["id"])
    assert DeferredCosting.objects.get().status == DeferredCosting.Status.WAITING

    build_brand("Outright")

    assert DeferredCosting.objects.get().status == DeferredCosting.Status.POSTED
    assert GLEntry.objects.filter(doc_number=sale.doc_number, account="COGS").count() == 1
    assert StockLedgerEntry.objects.filter(kind=StockLedgerEntry.Kind.SALE_OUT).count() == 1, (
        "the piece already left the shelf on the day; the sweep must not send it again"
    )
    assert trial_balance() == 0


def test_naming_the_supplier_releases_a_brand_owned_line(counter):
    """A payable with no counterparty is a guess, and the posting floor refuses it
    anyway - so the line waits until somebody says who is owed."""
    stock_in(counter["store"], 3, model="SOR")
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    response = counter["client"].post(SALES_URL, payload, format="json")
    sale = Sale.objects.get(pk=response.json()["id"])
    assert DeferredCosting.objects.get().reason == DeferredCosting.Reason.VENDOR_UNKNOWN

    build_supplier(Brand.objects.get(name="MUFTI"))

    row = DeferredCosting.objects.get()
    assert row.status == DeferredCosting.Status.POSTED
    payable = GLEntry.objects.get(doc_number=sale.doc_number, account="VENDOR_PAYABLE")
    assert payable.party_code == "ARVIND"
    assert payable.against_voucher == sale.doc_number
    assert SaleLine.objects.get().cost_vendor == Vendor.objects.get(code="ARVIND")
    assert trial_balance() == 0


def test_a_price_that_arrives_without_a_brand_relabels_the_wait(counter):
    """A row can learn something and still not be postable. The queue says which
    of the three waits it is in, because the two drain through different doors."""
    _sell_unknown(counter)

    _inward_of_an_unknown_brand()

    row = DeferredCosting.objects.get()
    assert row.status == DeferredCosting.Status.WAITING
    assert row.reason == DeferredCosting.Reason.MODEL_UNKNOWN
    # And it has been described, so the brand edit that releases it can find it.
    assert SaleLine.objects.get().brand == GHOST
    assert not GLEntry.objects.filter(account="COGS").exists()
    assert not StockLedgerEntry.objects.filter(sku_code=UNKNOWN).exists()


def test_a_relabelled_line_still_moves_its_stock_when_the_masters_arrive(counter):
    """The trap the `reason` column cannot answer: this row was re-labelled as a
    masters wait, but its piece has still never left a shelf. What decides is the
    line's own frozen cost, not the label."""
    sale = _sell_unknown(counter)
    _inward_of_an_unknown_brand()

    Brand.objects.create(
        code="ghost",
        name=GHOST,
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    assert DeferredCosting.objects.get().status == DeferredCosting.Status.POSTED
    sold = StockLedgerEntry.objects.get(
        sku_code=UNKNOWN, kind=StockLedgerEntry.Kind.SALE_OUT, doc_number=sale.doc_number
    )
    assert sold.qty == -1
    assert trial_balance() == 0


# --- what the golden file pins ---------------------------------------------


def _render(sale: Sale) -> str:
    """Both vouchers under one bill, in the order they were written."""
    lines = [f"{sale.doc_number}"]
    events: list[list[GLEntry]] = []
    for leg in GLEntry.objects.filter(doc_number=sale.doc_number).order_by("id"):
        if leg.line_no == 1:
            events.append([])
        events[-1].append(leg)
    written = ("A · money, on the day", "B · cost, when it arrived")
    for name, legs in zip(written, events, strict=True):
        lines.append(f"  event {name}")
        for leg in legs:
            side = "dr" if leg.amount > 0 else "cr"
            party = f" [{leg.party_type}:{leg.party_code}]" if leg.party_code else ""
            against = f" against {leg.against_voucher}" if leg.against_voucher else ""
            dims = " · ".join(p for p in (leg.brand, leg.season) if p)
            lines.append(
                f"    {side} {leg.account:<22}{abs(leg.amount):>10}"
                f"{('  ' + dims) if dims else ''}{party}{against}"
            )
        lines.append(f"    Σ {sum(leg.amount for leg in legs)}")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("model", "name"),
    [("Outright", "sold-before-inward-outright"), ("SOR", "sold-before-inward-sor")],
)
def test_the_whole_posting_of_a_released_bill(counter, model, name):
    """Money on the day, cost days later, both balanced, under one number."""
    sale = _sell_unknown(counter)
    if model == "SOR":
        build_supplier(build_brand(model))

    _inward(model=model)

    rendered = _render(sale)
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("KDPS_WRITE_GOLDEN") == "1":  # pragma: no cover - authoring aid
        path.write_text(rendered)
    assert path.exists(), f"missing golden file {path}"
    assert rendered == path.read_text(), (
        f"postings for {name} moved:\n\n--- expected ---\n{path.read_text()}"
        f"\n--- actual ---\n{rendered}"
    )
    assert trial_balance() == 0


def test_no_leg_on_any_path_is_ever_worth_nothing(counter):
    """The property the whole design exists to hold (Rule 5), asserted against the
    ledgers rather than against the code that writes them - a bill sold before
    inward, released, and one still waiting, all in the same books."""
    _sell_unknown(counter, till_seq=1)
    _inward()
    _sell_unknown(counter, till_seq=2)  # billed after the PT, but on a second barcode
    stock_in(counter["store"], 3)
    counter["client"].post(
        SALES_URL, bill_payload(counter["store"], counter["salesman"], till_seq=3), format="json"
    )

    assert not GLEntry.objects.filter(amount=0).exists()
    assert not StockLedgerEntry.objects.filter(amount=0).exists()
    assert trial_balance() == 0


# --- the queue as somebody sees it -----------------------------------------


def test_the_dashboard_counts_the_lines_still_waiting(counter):
    """The row a manager reads: how many pieces this shop sold that the books
    cannot value yet. It is meant to sit at nought."""
    url = "/api/store/dashboard"

    def waiting() -> int:
        body = counter["client"].get(url, HTTP_X_KDPS_UNIT=counter["store"].code).json()
        return {row["key"]: row["count"] for row in body["action_queue"]}["uncosted_sale_lines"]

    assert waiting() == 0
    _sell_unknown(counter)
    assert waiting() == 1
    _inward()
    assert waiting() == 0


def test_a_line_that_waits_too_long_becomes_somebody_s_job(counter):
    """The dial's days pass and the paperwork has not come: this stops being "on
    its way" and lands on the store's exception list."""
    sale = _sell_unknown(counter)
    _age(days=SellPolicy.current().uncosted_aging_days + 1)

    assert age_deferred() == 1

    flag = ContinuityFlag.objects.get()
    assert flag.kind == ContinuityFlag.Kind.AGED_UNCOSTED
    assert flag.sale == sale
    assert flag.store == counter["store"]
    assert flag.details["reasons"] == [DeferredCosting.Reason.UNPRICED]
    assert flag.details["lines"] == [1]


def test_ageing_the_same_queue_twice_does_not_flag_it_twice(counter):
    """It runs every night, so a second copy of yesterday's finding is noise the
    person clearing the list has to read past."""
    _sell_unknown(counter)
    _age(days=SellPolicy.current().uncosted_aging_days + 1)

    age_deferred()
    assert age_deferred() == 0

    assert ContinuityFlag.objects.count() == 1


def test_a_line_inside_the_dial_is_not_flagged(counter):
    _sell_unknown(counter)

    assert age_deferred() == 0

    assert not ContinuityFlag.objects.exists()


def test_the_flag_closes_when_the_paperwork_finally_lands(counter):
    """ "The flag closes" is the last step of the designed flow, and a flag nothing
    ever closes is a list people stop reading."""
    _sell_unknown(counter)
    _age(days=SellPolicy.current().uncosted_aging_days + 1)
    age_deferred()

    _inward()

    assert ContinuityFlag.objects.get().status == ContinuityFlag.Status.RESOLVED


def test_a_bill_with_a_line_still_waiting_keeps_its_flag_open(counter):
    """Two pieces sold before inward, one PT: the bill is still waiting."""
    _two_unknown_lines(counter)
    _age(days=SellPolicy.current().uncosted_aging_days + 1)
    age_deferred()

    _inward()

    assert ContinuityFlag.objects.get().status == ContinuityFlag.Status.OPEN
    assert DeferredCosting.objects.filter(status=DeferredCosting.Status.WAITING).count() == 1


def _age(*, days: int) -> None:
    """Put every waiting row that many days into the past.

    `created_at` is `auto_now_add`, so it cannot be set on the way in; this is the
    only honest way to make a queue old inside a test.
    """
    DeferredCosting.objects.update(created_at=timezone.now() - timedelta(days=days))


# --- the case that is not this one -----------------------------------------


def test_a_piece_the_books_know_but_the_shelf_says_nought_bills_normally(counter):
    """The commoner case, and deliberately not a deferral: the count was wrong,
    the piece is in the customer's hand, and the stocktake settles it (grill Q5).
    """
    build_piece()
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    assert not DeferredCosting.objects.exists()
    assert SaleLine.objects.get().costing_status == SaleLine.CostingStatus.POSTED
    assert StockOnHand.objects.get(store=counter["store"], sku_code="8901000000011").net_qty == -1
    assert GLEntry.objects.filter(account="COGS").count() == 1
    assert SaleLine.objects.get().net_paise == MRP_PAISE
    assert trial_balance() == 0


def test_the_flag_stops_naming_the_line_that_has_since_been_costed(counter):
    """A bill whose three waiting lines become one has not stopped waiting - but
    the two that posted are nobody's job now, and a flag still naming them sends
    somebody after work that is done."""
    _two_unknown_lines(counter)
    _age(days=SellPolicy.current().uncosted_aging_days + 1)
    age_deferred()
    assert ContinuityFlag.objects.get().details["lines"] == [1, 2]

    _inward()
    age_deferred()

    flag = ContinuityFlag.objects.get()
    assert flag.status == ContinuityFlag.Status.OPEN
    assert flag.details["lines"] == [2]


def test_a_flag_the_store_chose_to_ignore_is_not_raised_again_tomorrow(counter):
    """Otherwise "ignore" means nothing: the row is still on the Dashboard's
    count either way, so re-raising it every night only wears the list out."""
    _sell_unknown(counter)
    _age(days=SellPolicy.current().uncosted_aging_days + 1)
    age_deferred()
    ContinuityFlag.objects.update(status=ContinuityFlag.Status.IGNORED)

    assert age_deferred() == 0

    assert ContinuityFlag.objects.count() == 1


def test_a_line_billed_with_a_season_is_costed_out_of_that_season(counter):
    """A re-ordered style sits in two seasons at two costs. The till said which
    one it was selling, and the sweep honours it rather than re-running the scan
    ladder - the ladder answers "what is the counter selling", which is not the
    question a line that has already been sold is asking.
    """
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=1, barcode=UNKNOWN, season="SS26"
    )
    payload["lines"][0]["manual_desc"] = "Blue check shirt"
    assert counter["client"].post(SALES_URL, payload, format="json").status_code == 201
    Season.objects.get_or_create(
        code="SS26", defaults={"name": "Spring/Summer 2026", "status": "open", "sort_order": 3}
    )
    # The older season is priced first and cheaper; the ladder would prefer it.
    build_piece(barcode=UNKNOWN, season="FW25", cost_paise=40000)
    assert DeferredCosting.objects.get().status == DeferredCosting.Status.WAITING

    build_piece(barcode=UNKNOWN, season="SS26", cost_paise=90000)

    line = SaleLine.objects.get()
    assert line.season == "SS26"
    assert line.unit_cost_paise == 90000
    sold = StockLedgerEntry.objects.get(sku_code=UNKNOWN, kind=StockLedgerEntry.Kind.SALE_OUT)
    assert sold.amount == -90000
    assert sold.season == "SS26"
    assert trial_balance() == 0


def test_waking_a_dormant_supplier_releases_the_line_waiting_on_them(counter):
    """`supplier_of` will only name an active vendor, and switching one back on
    touches no brand link at all - so without a door of its own the queue would
    have no way to hear about it."""
    stock_in(counter["store"], 3, model="SOR")
    vendor = build_supplier(Brand.objects.get(name="MUFTI"))
    vendor.is_active = False
    vendor.save()
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    response = counter["client"].post(SALES_URL, payload, format="json")
    sale = Sale.objects.get(pk=response.json()["id"])
    assert DeferredCosting.objects.get().reason == DeferredCosting.Reason.VENDOR_UNKNOWN

    vendor.is_active = True
    vendor.save()

    assert DeferredCosting.objects.get().status == DeferredCosting.Status.POSTED
    assert GLEntry.objects.filter(doc_number=sale.doc_number, account="VENDOR_PAYABLE").exists()
    assert trial_balance() == 0


def _two_unknown_lines(counter) -> Sale:
    """One bill, two pieces nothing can place - and only one of them ever gets
    a PT, which is how a bill can be part-costed."""
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, barcode=UNKNOWN)
    second = {**payload["lines"][0], "line_no": 2, "barcode": "8909999999902"}
    payload["lines"] = [{**payload["lines"][0]}, second]
    for line in payload["lines"]:
        line["season"] = ""
        line["manual_desc"] = "off the tag"
    net = sum(line["net_paise"] for line in payload["lines"])
    payload["tenders"] = [{"mode": "cash", "amount_paise": net}]
    payload["totals"] = {
        "gross_paise": sum(line["mrp_paise"] for line in payload["lines"]),
        "discount_paise": 0,
        "net_paise": net,
        "gst_paise": sum(line["gst_paise"] for line in payload["lines"]),
        "round_paise": 0,
    }
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    return Sale.objects.get(pk=response.json()["id"])
