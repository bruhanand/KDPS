"""The store's day by tender (#188, contract §Step 6).

`GET /api/store/cash-summary` is what a store person counts a drawer against, so
the acceptance criterion is a tie rather than a shape: **the summary matches the
tender rows to the paisa for any day**. Everything here is about the ways that
tie could quietly break - a bill from another store, a bill from another day, a
cancelled bill, a credit note that is not money.

Read-only by construction: there is no writer for a day summary anywhere in this
contract, because agreeing a day is store open/close (I3).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _sell import (
    FY,
    MRP_PAISE,
    bill_payload,
    build_accountant,
    build_cashier,
    build_manager,
    build_salesman,
    build_store,
    client_for,
    stock_in,
    upi_tender,
)
from django.db.models import Sum
from django.utils import timezone

from accounts.models import ScopeType, User
from core.documents import DocStatus
from finledger.models import CashLedgerEntry
from sell.models import ContinuityFlag, CreditNote, Sale, SaleTender

URL = "/api/store/cash-summary"
SALES_URL = "/api/sell/sales"

#: The day every bill in this suite is printed on, matching `_sell.bill_payload`.
#: Fixed rather than "today" because the suite is about which day a figure lands
#: on, and one that ran differently at 23:59 IST would be testing the clock.
BILLED_DAY = "2026-07-30"


@pytest.fixture
def counter(db):
    store = build_store()
    stock_in(store, 20)
    return {
        "store": store,
        "cashier": build_cashier(store),
        "manager": build_manager(store),
        "salesman": build_salesman(store),
    }


def _bill(counter, till_seq: int, **overrides) -> None:
    """One accepted bill, straight through the real accept pipeline.

    Never an INSERT: the point of this endpoint is that it agrees with what the
    pipeline wrote, so a fixture writing the rows itself would check the fixture.
    """
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq, **overrides)
    response = client_for(counter["cashier"]).post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()


def _summary(user, **params) -> dict:
    response = client_for(user).get(URL, params)
    assert response.status_code == 200, response.json()
    return response.json()


def _tender_ledger() -> dict[str, int]:
    """What the tender rows themselves say, by mode - the thing the summary must
    equal. Read straight off the table so the assertion is a tie and not a second
    copy of the expected numbers."""
    return {
        row["mode"]: int(row["total"])
        for row in SaleTender.objects.values("mode").annotate(total=Sum("amount_paise"))
    }


def test_the_day_by_mode_ties_to_the_tender_rows_to_the_paisa(counter):
    """The acceptance criterion, said as arithmetic."""
    _bill(counter, 1)
    _bill(
        counter,
        2,
        tenders=[
            {"mode": "card", "amount_paise": 100000},
            upi_tender(MRP_PAISE - 100000),
        ],
    )
    body = _summary(counter["cashier"], date=BILLED_DAY)
    ledger = _tender_ledger()

    assert body["modes"]["cash"] == ledger["cash"] == MRP_PAISE
    assert body["modes"]["card"] == ledger["card"] == 100000
    assert body["modes"]["upi"] == ledger["upi"] == MRP_PAISE - 100000
    assert body["modes"]["credit_note"] == 0
    assert body["bills"] == 2


def test_every_mode_is_present_even_on_a_day_nobody_used_it(counter):
    """A tile that vanishes when unused makes a store person wonder where it went."""
    body = _summary(counter["cashier"], date=BILLED_DAY)
    assert body["modes"] == {"cash": 0, "card": 0, "upi": 0, "credit_note": 0}
    assert body["upi_split"] == {"confirmed": 0, "manual": 0}
    assert body["bills"] == 0
    assert body["returns"] == 0
    assert body["credit_notes_issued_paise"] == 0
    assert body["flags_open"] == 0


def test_upi_split_ties_to_the_upi_total_by_construction(counter):
    """Confirmed cannot legitimately reach the server yet (#248), but the
    pipeline accepts it correctly, and the split has to be right the day it
    starts arriving - so one bill sends each stamp."""
    _bill(counter, 1, tenders=[upi_tender(MRP_PAISE, state="confirmed", reference="AXL999")])
    _bill(counter, 2, tenders=[upi_tender(MRP_PAISE)])

    body = _summary(counter["cashier"], date=BILLED_DAY)

    assert body["upi_split"]["confirmed"] == MRP_PAISE
    assert body["upi_split"]["manual"] == MRP_PAISE
    assert body["upi_split"]["confirmed"] + body["upi_split"]["manual"] == body["modes"]["upi"]


def test_another_day_is_not_this_day(counter):
    _bill(counter, 1)
    body = _summary(counter["cashier"], date="2026-07-29")
    assert body["modes"]["cash"] == 0
    assert body["bills"] == 0


def test_another_store_is_not_this_store(counter):
    """The tie is per store, and the store comes from scope, never from the bill."""
    other = build_store("SEL-RAN")
    stock_in(other, 5)
    other_cashier = build_cashier(other, username="ran_cashier")
    other_salesman = build_salesman(other, code="RANE")
    response = client_for(other_cashier).post(
        SALES_URL, bill_payload(other, other_salesman, till_seq=1), format="json"
    )
    assert response.status_code == 201, response.json()
    _bill(counter, 1)

    assert _summary(counter["cashier"], date=BILLED_DAY)["bills"] == 1
    assert _summary(other_cashier, date=BILLED_DAY)["bills"] == 1
    assert _tender_ledger()["cash"] == MRP_PAISE * 2  # both bills exist; each day sees one


def test_a_cancelled_bill_leaves_the_day(counter):
    """The books correct by reversal, so the row and its tenders stay - and a day
    that still counted them could never be matched to a drawer again."""
    _bill(counter, 1)
    Sale.objects.filter(till_seq=1).update(docstatus=DocStatus.CANCELLED)

    body = _summary(counter["cashier"], date=BILLED_DAY)
    assert body["bills"] == 0
    assert body["modes"]["cash"] == 0


def test_a_credit_note_tender_is_counted_but_is_not_cash(counter):
    """It extinguishes a liability rather than filling a drawer, so it has its own
    column and must never land in the cash one."""
    note = CreditNote.objects.create(
        store=counter["store"], fy=FY, value_paise=50000, expires_on="2027-01-30"
    )
    note.post()
    _bill(
        counter,
        1,
        tenders=[
            {"mode": "credit_note", "amount_paise": 50000, "credit_note": note.doc_number},
            {"mode": "cash", "amount_paise": MRP_PAISE - 50000},
        ],
    )
    body = _summary(counter["cashier"], date=BILLED_DAY)
    assert body["modes"]["cash"] == MRP_PAISE - 50000
    assert body["modes"]["credit_note"] == 50000


def test_open_exceptions_from_the_day_are_counted_and_cleared_ones_are_not(counter):
    _bill(counter, 4)  # a hole: bills 1-3 never arrived
    assert ContinuityFlag.objects.filter(kind=ContinuityFlag.Kind.NUMBER_HOLE).count() == 1
    assert _summary(counter["cashier"], date=BILLED_DAY)["flags_open"] == 1

    ContinuityFlag.objects.update(status=ContinuityFlag.Status.RESOLVED)
    assert _summary(counter["cashier"], date=BILLED_DAY)["flags_open"] == 0


def test_the_date_defaults_to_today_and_a_nonsense_date_is_refused(counter):
    assert _summary(counter["cashier"])["date"] == timezone.localdate().isoformat()

    for bad in ("yesterday", "2026-02-30"):
        response = client_for(counter["cashier"]).get(URL, {"date": bad})
        assert response.status_code == 400, bad
        assert response.json()["code"] == "VALIDATION"


def test_a_head_office_reader_must_pick_a_store(counter):
    """Fifty shops is not a day summary. The same refusal the Dashboard gives, in
    the same words, because it is the same resolver."""
    accountant = build_accountant()
    response = client_for(accountant).get(URL)
    assert response.status_code == 403
    assert response.json()["code"] == "SCOPE_DENIED"

    assert _summary(accountant, store=counter["store"].code)["store"] == counter["store"].code


def test_somebody_with_no_money_section_cannot_read_it(counter):
    """Gated `money: view` per the contract - a brand manager holds none."""
    manager = User.objects.create_user(
        username="cs_brand",
        password=TEST_PASSWORD,
        role=make_role("brand_manager", "Brand manager (cash summary tests)"),
        scope_type=ScopeType.ALL,
    )
    assert client_for(manager).get(URL, {"store": counter["store"].code}).status_code == 403


def test_yesterdays_bill_stays_on_yesterday(counter):
    """The bill's own clock decides the day, not the moment it synced."""
    yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
    _bill(counter, 1, billed_at=f"{yesterday}T06:00:00Z")
    assert _summary(counter["cashier"], date=yesterday)["bills"] == 1
    assert _summary(counter["cashier"])["bills"] == 0


def test_a_discount_moves_the_tenders_and_the_summary_with_them(counter):
    """The summary is tax- and discount-inclusive: it is what the customer paid."""
    disc = 20000
    _bill(counter, 1, disc_paise=disc, override={"user_id": counter["manager"].id})
    assert _summary(counter["cashier"], date=BILLED_DAY)["modes"]["cash"] == MRP_PAISE - disc


def test_home_and_money_read_the_same_day(counter):
    """The two screens share `storefront.day`, so this is a tie rather than a
    coincidence - and it is the tie that matters, because a manager reading one
    figure on Home and another in Money has no way to tell which is the day."""
    today = timezone.localdate().isoformat()
    _bill(counter, 1, billed_at=f"{today}T06:00:00Z")

    home = client_for(counter["cashier"]).get("/api/store/dashboard").json()
    money = _summary(counter["cashier"])

    assert home["sales_live"] is True
    assert home["today"]["collections"] == money["modes"]
    assert home["today"]["bills"] == money["bills"] == 1
    assert home["today"]["net_sales_paise"] == sum(money["modes"].values()) == MRP_PAISE
    assert home["today"]["pieces"] == 1
    assert home["last7"][-1] == {"date": today, "net_sales_paise": MRP_PAISE}


def test_the_dashboard_queue_carries_the_stores_open_exceptions(counter):
    """AC3's first half: a flag lands on the Dashboard queue. Clearing it is the
    flags endpoint's own suite."""
    _bill(counter, 4)  # a hole
    home = client_for(counter["cashier"]).get("/api/store/dashboard").json()
    queue = {row["key"]: row["count"] for row in home["action_queue"]}
    assert queue["continuity_flags"] == 1


def _exchange(counter, till_seq: int, original: Sale, *, refund_multiple: int = 1) -> None:
    """A bill that sells one piece and takes `refund_multiple` back against
    `original`'s only line - the shape of every exchange the till can send."""
    line = original.lines.get()
    # What the customer actually paid for those pieces (D2), which is the line's
    # own value shared over its quantity - never today's price.
    refund = int(line.net_paise) * refund_multiple // int(line.qty)
    refund_gst = int(line.gst_paise) * refund_multiple // int(line.qty)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq)
    payload["exchange"] = {
        "original": {"store": counter["store"].code, "fy": FY, "till_seq": original.till_seq},
        "lines": [
            {
                "line_no": 2,
                "barcode": line.barcode,
                "qty": refund_multiple,
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": refund_gst,
                "condition": "good",
                "reason": "size",
                "original_line": 1,
            }
        ],
    }
    net = MRP_PAISE - refund
    payload["totals"]["net_paise"] = net
    payload["totals"]["gst_paise"] = int(payload["totals"]["gst_paise"]) - refund_gst
    payload["tenders"] = [{"mode": "cash", "amount_paise": net}] if net > 0 else []
    response = client_for(counter["cashier"]).post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()


def test_pieces_given_back_are_counted_apart_from_pieces_sold(counter):
    """ "We sold two and took one back" is two facts; netting them hides one."""
    _bill(counter, 1, qty=2)
    _exchange(counter, 2, Sale.objects.get(till_seq=1))

    body = _summary(counter["cashier"], date=BILLED_DAY)
    assert body["bills"] == 2
    assert body["returns"] == 1


def test_a_bill_that_owes_the_customer_hands_over_a_note_and_no_cash(counter):
    """Cash never leaves the drawer on a return (grill Q7), so the day's cash does
    not fall - the store's liability rises instead, and that is its own figure."""
    _bill(counter, 1, qty=2)
    _exchange(counter, 2, Sale.objects.get(till_seq=1), refund_multiple=2)

    body = _summary(counter["cashier"], date=BILLED_DAY)
    note = CreditNote.objects.get(source_sale__till_seq=2)
    assert body["credit_notes_issued_paise"] == int(note.value_paise) > 0
    assert body["modes"]["cash"] == MRP_PAISE * 2  # the first bill's takings, undisturbed


def test_the_summary_ties_to_the_cash_ledger_as_well_as_to_the_tenders(counter):
    """Two books, one figure. The tenders are what the summary reads (see
    `storefront/day.py` for why), and `finledger` writes a receipt row per tender
    beside them - so if the two ever part company, the number a store counts a
    drawer against is wrong in a way nothing else would notice.

    The credit note is deliberately not in the tie: it closes a liability rather
    than filling a drawer, so it has a value leg and no cash row at all.
    """
    _bill(counter, 1)
    _bill(
        counter,
        2,
        tenders=[
            {"mode": "card", "amount_paise": 100000},
            upi_tender(MRP_PAISE - 100000),
        ],
    )
    body = _summary(counter["cashier"], date=BILLED_DAY)

    receipts = CashLedgerEntry.objects.filter(
        kind=CashLedgerEntry.Kind.RECEIPT,
        doc_number__in=list(
            Sale.objects.filter(store=counter["store"]).values_list("doc_number", flat=True)
        ),
    )
    per_account = {
        row["account"]: int(row["total"])
        for row in receipts.values("account").annotate(total=Sum("amount"))
    }
    assert per_account["CASH"] == body["modes"]["cash"]
    assert per_account["CARD"] == body["modes"]["card"]
    assert per_account["UPI"] == body["modes"]["upi"]


def test_a_brand_scoped_reader_gets_no_store_at_all(counter):
    """`visible_store_ids` answers `None` for a brand manager meaning "stores are
    the wrong question", never "every store" - and the money tiles are exactly the
    figure that must not fall out of that. The read-scope fail-open class this
    codebase has shipped before."""
    _bill(counter, 1)
    brand_manager = User.objects.create_user(
        username="cs_brand_scope",
        password=TEST_PASSWORD,
        role=make_role("owner", "Owner rung, brand boundary (cash summary tests)"),
        scope_type=ScopeType.BRAND,
    )

    for url in ("/api/store/dashboard", URL):
        response = client_for(brand_manager).get(url, {"store": counter["store"].code})
        assert response.status_code == 403, url
        assert response.json()["code"] == "SCOPE_DENIED"
        assert "brand" in response.json()["error"]
