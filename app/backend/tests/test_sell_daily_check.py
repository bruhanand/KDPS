"""The nightly reconciliation (#188) - the pilot's go/no-go gate.

The ticket's second and fourth acceptance criteria live here:

  · the command flags holes surviving EOD, offer/GST mismatches beyond tolerance,
    aged deferred costings and per-employee return counts;
  · **a clean seeded day produces zero flags** - the green-gate demo.

The second one is the load-bearing test in the file. A check that cried wolf on
an ordinary Tuesday would be turned off inside a week, and then the four findings
it exists for would go unread; so every test that arranges a *clean* day and
asserts silence is as much the point as the ones that arrange a defect.

Everything here also runs twice where it can, because the check runs every night
against a day that no longer changes: a second run must find nothing new.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from _sell import (
    FY,
    MRP_PAISE,
    bill_payload,
    build_brand,
    build_cashier,
    build_manager,
    build_salesman,
    build_store,
    client_for,
    gst_on,
    stock_in,
)
from django.core.management import call_command
from django.utils import timezone

from core.documents import DocStatus
from masters.models import GstSlab
from offers.models import Offer
from sell.models import ContinuityFlag, Sale, SaleLine, SellPolicy
from sell.services.daily_check import run

SALES_URL = "/api/sell/sales"

#: The trading day this suite reconciles. Fixed rather than "today", because the
#: whole file is about which day a finding lands on.
DAY = date(2026, 7, 30)
DAY_ISO = DAY.isoformat()


@pytest.fixture
def counter(db):
    store = build_store()
    stock_in(store, 40)
    return {
        "store": store,
        "cashier": build_cashier(store),
        "manager": build_manager(store),
        "salesman": build_salesman(store),
    }


def _bill(counter, till_seq: int, **overrides):
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq, **overrides)
    response = client_for(counter["cashier"]).post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    return Sale.objects.get(pk=response.json()["id"])


def _open(kind: str | None = None):
    rows = ContinuityFlag.objects.filter(status=ContinuityFlag.Status.OPEN)
    return rows.filter(kind=kind) if kind else rows


# --- the green gate ---------------------------------------------------------


def test_a_clean_day_produces_no_flags_at_all(counter):
    """The acceptance criterion the pilot is judged on."""
    _bill(counter, 1)
    _bill(counter, 2)
    _bill(counter, 3)
    assert ContinuityFlag.objects.count() == 0  # nothing at the counter either

    report = run(DAY)

    assert report.total_raised == 0
    assert ContinuityFlag.objects.count() == 0


def test_a_store_that_never_billed_is_not_a_finding(counter):
    """Fifty shops are checked every night and most of them are ordinary."""
    assert run(DAY).total_raised == 0


def test_running_twice_finds_nothing_the_second_time(counter):
    """It runs every night against a day that cannot change any more."""
    _bill(counter, 4)  # a hole under it
    first = run(DAY)
    assert first.total_raised == 1

    second = run(DAY)
    assert second.total_raised == 0
    assert second.refreshed == 1  # the standing flag was rewritten, not repeated
    assert _open(ContinuityFlag.Kind.NUMBER_HOLE).filter(sale__isnull=True).count() == 1


# --- did every bill arrive? -------------------------------------------------


def test_holes_surviving_the_day_are_flagged_against_the_store(counter):
    _bill(counter, 4)

    run(DAY)

    standing = _open(ContinuityFlag.Kind.NUMBER_HOLE).get(sale__isnull=True)
    assert standing.details["missing"] == [1, 2, 3]
    assert standing.details["count"] == 3
    assert standing.details["day"] == DAY_ISO
    assert standing.details["fy"] == FY


def test_a_hole_that_fills_overnight_closes_both_flags(counter):
    """The commonest case by far: a till was behind at six and caught up by ten.
    Nothing should be on anybody's morning list."""
    _bill(counter, 2)  # bill 1 still queued somewhere
    assert _open(ContinuityFlag.Kind.NUMBER_HOLE).count() == 1  # accept's own
    run(DAY)
    assert _open(ContinuityFlag.Kind.NUMBER_HOLE).count() == 2  # + the standing one

    _bill(counter, 1)  # the straggler arrives
    report = run(DAY)

    assert report.resolved == 2
    assert _open(ContinuityFlag.Kind.NUMBER_HOLE).count() == 0


def test_a_hole_a_store_chose_to_ignore_is_not_raised_again(counter):
    """`ignored` is the store having looked. Re-raising would make it mean
    nothing - and the row still counts on the Dashboard either way."""
    _bill(counter, 4)
    run(DAY)
    ContinuityFlag.objects.filter(sale__isnull=True).update(status=ContinuityFlag.Status.IGNORED)

    report = run(DAY)

    assert report.total_raised == 0
    assert (
        ContinuityFlag.objects.filter(
            kind=ContinuityFlag.Kind.NUMBER_HOLE, sale__isnull=True
        ).count()
        == 1
    )


# --- was the customer charged what the rulebook says? -----------------------


def test_tax_that_disagrees_with_the_dated_slab_is_flagged(counter):
    """The bill charged 18% on a piece the slab prices at 5%. The counter's own
    check catches it too - what this proves is that the nightly pass asks the
    same question of a written bill and gets the same answer."""
    _bill(counter, 1, gst_rate="18")
    ContinuityFlag.objects.all().delete()  # forget what the counter said

    run(DAY)

    flag = _open(ContinuityFlag.Kind.GST_MISMATCH).get()
    assert flag.sale.till_seq == 1
    assert flag.details["lines"][0]["line_no"] == 1
    assert flag.details["lines"][0]["slab_rate"] == "5.00"


def test_a_bill_already_flagged_at_the_counter_is_not_flagged_twice(counter):
    """Two rows saying one thing about one bill is not twice the information."""
    _bill(counter, 1, gst_rate="18")
    assert _open(ContinuityFlag.Kind.GST_MISMATCH).count() == 1

    assert run(DAY).total_raised == 0
    assert _open(ContinuityFlag.Kind.GST_MISMATCH).count() == 1


def test_a_slab_corrected_after_the_bill_synced_is_caught_by_the_night_run(counter):
    """The reason the nightly pass is not a second copy of the accept check: the
    bill cannot move, but the book it is read against can."""
    _bill(counter, 1)
    assert ContinuityFlag.objects.count() == 0

    GstSlab.objects.update(rate_below=12)  # head office fixes a rate, after the fact

    run(DAY)

    assert _open(ContinuityFlag.Kind.GST_MISMATCH).count() == 1


def test_an_offer_the_counter_never_applied_is_found_at_night(counter):
    """A bill priced at full MRP under a rulebook that says 30% off - the
    applied-vs-rulebook half (B3, D5 Q10)."""
    Offer.objects.create(
        name="30% off MUFTI",
        brand=build_brand(),
        layer=Offer.Layer.BRAND,
        trigger_type=Offer.Trigger.NONE,
        reward_type=Offer.Reward.PCT_OFF,
        reward_config={"percent": "30.00"},
        store_scope={"kind": "specific", "stores": [counter["store"].code]},
        starts_on=DAY - timedelta(days=1),
        status=Offer.Status.LIVE,
        approved_by=counter["manager"],  # a live rule names its approver (D5 Q9)
    )
    _bill(counter, 1)
    ContinuityFlag.objects.all().delete()

    run(DAY)

    flag = _open(ContinuityFlag.Kind.OFFER_MISMATCH).get()
    line = flag.details["lines"][0]
    assert line["charged_paise"] == 0
    assert line["rulebook_paise"] > 0


def test_a_return_leg_is_never_repriced_against_todays_book(counter):
    """A refund is what the customer actually paid (D2), so measuring it against
    today's slab would flag every return taken after a rate change - the check
    crying wolf about the one thing it is for."""
    original = _bill(counter, 1, qty=2)
    line = original.lines.get()
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=2)
    payload["exchange"] = {
        "original": {"store": counter["store"].code, "fy": FY, "till_seq": 1},
        "lines": [
            {
                "line_no": 2,
                "barcode": line.barcode,
                "qty": 1,
                "refund_paise": int(line.net_paise) // 2,
                "gst_rate": "5",
                "gst_paise": int(line.gst_paise) // 2,
                "condition": "good",
                "reason": "size",
                "original_line": 1,
            }
        ],
    }
    net = MRP_PAISE - int(line.net_paise) // 2
    payload["totals"]["net_paise"] = net
    payload["totals"]["gst_paise"] = gst_on(MRP_PAISE) - int(line.gst_paise) // 2
    payload["tenders"] = [{"mode": "cash", "amount_paise": net}]
    assert client_for(counter["cashier"]).post(SALES_URL, payload, format="json").status_code == 201

    GstSlab.objects.update(rate_below=12)
    run(DAY)

    # The two *sold* lines are flagged; the return leg is not among them.
    flagged_lines = [
        line["line_no"]
        for flag in _open(ContinuityFlag.Kind.GST_MISMATCH)
        for line in flag.details["lines"]
    ]
    assert flagged_lines == [1, 1]


def test_a_cancelled_bill_is_not_repriced(counter):
    """The books say it did not happen, so there is nothing to disagree with."""
    _bill(counter, 1, gst_rate="18")
    ContinuityFlag.objects.all().delete()
    Sale.objects.update(docstatus=DocStatus.CANCELLED)

    assert run(DAY).total_raised == 0


# --- who took the returns? --------------------------------------------------


def _return_bill(counter, till_seq: int, original: Sale, qty: int) -> None:
    """An equal-value bill that sells and takes back `qty` pieces."""
    line = original.lines.get()
    # Whole pieces at what they were paid, so the server's own back-calculation
    # lands on the same paisa - an integer division of the line's tax would be
    # one paisa out and the bill would be refused for arithmetic, not for what
    # the test is about.
    refund = int(line.net_paise) * qty // int(line.qty)
    refund_gst = gst_on(refund)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq, qty=qty)
    payload["exchange"] = {
        "original": {"store": counter["store"].code, "fy": FY, "till_seq": original.till_seq},
        "lines": [
            {
                "line_no": 2,
                "barcode": line.barcode,
                "qty": qty,
                "refund_paise": refund,
                "gst_rate": "5",
                "gst_paise": refund_gst,
                "condition": "good",
                "reason": "size",
                "original_line": 1,
            }
        ],
    }
    outgoing = MRP_PAISE * qty
    net = outgoing - refund
    payload["totals"]["net_paise"] = net
    payload["totals"]["gst_paise"] = gst_on(outgoing) - refund_gst
    payload["tenders"] = [{"mode": "cash", "amount_paise": net}] if net > 0 else []
    response = client_for(counter["cashier"]).post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()


def test_returns_are_counted_per_seller_whether_or_not_anybody_is_flagged(counter):
    """Grill Q7's ask is the count; the flag is only what a large one becomes."""
    original = _bill(counter, 1, qty=6)
    _return_bill(counter, 2, original, 2)

    report = run(DAY)

    assert report.returns_by_seller[f"{counter['store'].code}/ALIE"] == 2
    assert _open(ContinuityFlag.Kind.EMPLOYEE_RETURNS).count() == 0  # under the dial


def test_a_seller_past_the_dial_is_named(counter):
    original = _bill(counter, 1, qty=8)
    _return_bill(counter, 2, original, 6)  # the dial ships at five

    run(DAY)

    flag = _open(ContinuityFlag.Kind.EMPLOYEE_RETURNS).get()
    assert flag.details["threshold"] == SellPolicy.current().return_review_count
    assert flag.details["sellers"] == [{"salesman": "ALIE", "name": "Ali E.", "returns": 6}]
    assert flag.details["day"] == DAY_ISO
    assert flag.sale_id is None  # a pattern across bills has no one bill


def test_the_dial_is_data_and_moving_it_moves_the_finding(counter):
    """Rule 12: a store with a returns-heavy Saturday moves the number rather than
    learning to ignore the list."""
    original = _bill(counter, 1, qty=8)
    _return_bill(counter, 2, original, 6)
    SellPolicy.objects.update(return_review_count=10)

    assert run(DAY).total_raised == 0


# --- ageing -----------------------------------------------------------------


def test_the_ageing_step_runs_inside_the_nightly_check(counter):
    """It had a schedule of its own until this existed (#186); folding it in must
    not lose it."""
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["lines"][0]["barcode"] = "8909999999999"  # a piece the books have never seen
    payload["lines"][0]["manual_desc"] = "Navy shirt, tag says 1499"
    assert client_for(counter["cashier"]).post(SALES_URL, payload, format="json").status_code == 201
    SellPolicy.objects.update(uncosted_aging_days=0)

    report = run(timezone.localdate())

    assert report.raised[ContinuityFlag.Kind.AGED_UNCOSTED] == 1
    assert _open(ContinuityFlag.Kind.AGED_UNCOSTED).count() == 1


# --- the command ------------------------------------------------------------


def test_the_command_defaults_to_yesterday_and_says_when_a_day_is_clean(counter, capsys):
    call_command("sell_daily_check")
    out = capsys.readouterr().out
    assert (timezone.localdate() - timedelta(days=1)).isoformat() in out
    assert "Clean day" in out


def test_the_command_takes_a_day_and_a_store(counter, capsys):
    _bill(counter, 4)
    call_command("sell_daily_check", date=DAY_ISO, store=counter["store"].code)
    out = capsys.readouterr().out
    assert "number_hole" in out
    assert "1 new exception" in out


def test_a_line_the_bill_never_wrote_cannot_reach_the_reprice(counter):
    """Belt and braces on the join: the reprice reads a bill's own rows, so a
    line of another bill can never be counted into this one's finding."""
    _bill(counter, 1, gst_rate="18")
    _bill(counter, 2)
    ContinuityFlag.objects.all().delete()

    run(DAY)

    flags = list(_open(ContinuityFlag.Kind.GST_MISMATCH))
    assert len(flags) == 1
    assert flags[0].sale.till_seq == 1
    assert SaleLine.objects.filter(sale__till_seq=2).count() == 1


# --- what a re-run must not do ----------------------------------------------


def test_an_ignored_hole_does_not_silence_a_new_one(counter):
    """`ignored` is the store having looked at *these* missing numbers. When the
    set changes that is a finding nobody has seen, and writing it quietly into
    the row somebody already dismissed would lose it."""
    _bill(counter, 4)  # 1-3 missing
    run(DAY)
    ContinuityFlag.objects.filter(sale__isnull=True).update(status=ContinuityFlag.Status.IGNORED)

    _bill(counter, 9)  # 5-8 missing too, and nobody has seen those

    report = run(DAY)

    assert report.raised[ContinuityFlag.Kind.NUMBER_HOLE] == 1
    fresh = _open(ContinuityFlag.Kind.NUMBER_HOLE).get(sale__isnull=True)
    assert fresh.details["missing"] == [1, 2, 3, 5, 6, 7, 8]


def test_the_standing_hole_keeps_the_day_it_first_survived(counter):
    """It is a fact about a shop, not about a day, so a run for an older date
    must not drag it out of the day somebody has been looking at it on."""
    _bill(counter, 4)
    run(DAY)

    run(DAY - timedelta(days=5))

    standing = _open(ContinuityFlag.Kind.NUMBER_HOLE).get(sale__isnull=True)
    assert standing.details["day"] == DAY_ISO
    assert _open(ContinuityFlag.Kind.NUMBER_HOLE).filter(sale__isnull=True).count() == 1


def test_a_finding_somebody_cleared_is_not_handed_back(counter):
    """A cron retry after a partial night must not undo a morning's work. The
    bill cannot change - there is no writer for a posted sale (A7) - so a finding
    somebody answered is answered for good."""
    _bill(counter, 1, gst_rate="18")
    ContinuityFlag.objects.all().delete()
    run(DAY)
    ContinuityFlag.objects.update(status=ContinuityFlag.Status.RESOLVED, resolved_at=timezone.now())

    assert run(DAY).total_raised == 0
    assert ContinuityFlag.objects.filter(kind=ContinuityFlag.Kind.GST_MISMATCH).count() == 1


def test_a_return_count_somebody_cleared_is_not_handed_back(counter):
    original = _bill(counter, 1, qty=8)
    _return_bill(counter, 2, original, 6)
    run(DAY)
    ContinuityFlag.objects.filter(kind=ContinuityFlag.Kind.EMPLOYEE_RETURNS).update(
        status=ContinuityFlag.Status.RESOLVED, resolved_at=timezone.now()
    )

    assert run(DAY).raised[ContinuityFlag.Kind.EMPLOYEE_RETURNS] == 0
    assert ContinuityFlag.objects.filter(kind=ContinuityFlag.Kind.EMPLOYEE_RETURNS).count() == 1


def test_one_store_is_one_stores_run(counter):
    """`--store DEO` must not report the shop next door's unpriced lines."""
    other = build_store("SEL-RAN")
    stock_in(other, 5)
    other_cashier = build_cashier(other, username="ran_cashier")
    other_salesman = build_salesman(other, code="RANE")
    payload = bill_payload(other, other_salesman, till_seq=1)
    payload["lines"][0]["barcode"] = "8909999999999"
    payload["lines"][0]["manual_desc"] = "Navy shirt, tag says 1499"
    assert client_for(other_cashier).post(SALES_URL, payload, format="json").status_code == 201
    SellPolicy.objects.update(uncosted_aging_days=0)

    mine = run(timezone.localdate(), counter["store"].code)

    assert mine.total_raised == 0
    assert _open(ContinuityFlag.Kind.AGED_UNCOSTED).count() == 0
    assert run(timezone.localdate()).raised[ContinuityFlag.Kind.AGED_UNCOSTED] == 1
