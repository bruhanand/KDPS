"""The store's exception list, and clearing one (#188).

The ticket's third acceptance criterion: **flags land on the Dashboard queue with
links, and resolving clears them.** The Dashboard half is in the cash-summary
suite (it is a count on a payload); this is the list somebody actually works, and
the one write in the whole slice.

Two properties matter more than the shape:

  · **Nothing here can touch a bill** (A7). Clearing an exception is a statement
    about somebody's attention, and a bill that is genuinely wrong is corrected by
    the kernel's reversing transition and by nothing on this screen.
  · **What you are looking at never decides what you may do** (ADR-0003). The
    list obeys the top-bar switcher; the write obeys entitlement.
"""

from __future__ import annotations

from datetime import date

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _sell import (
    bill_payload,
    build_accountant,
    build_cashier,
    build_salesman,
    build_store,
    client_for,
    stock_in,
)
from django.utils import timezone

from accounts.models import ScopeType, User
from sell.models import ContinuityFlag, Sale

URL = "/api/sell/flags"
SALES_URL = "/api/sell/sales"
BILLED_DAY = "2026-07-30"


@pytest.fixture
def counter(db):
    store = build_store()
    stock_in(store, 20)
    return {
        "store": store,
        "cashier": build_cashier(store),
        "salesman": build_salesman(store),
    }


def _bill(counter, till_seq: int, **overrides) -> Sale:
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq, **overrides)
    response = client_for(counter["cashier"]).post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
    return Sale.objects.get(pk=response.json()["id"])


def _list(user, **params) -> dict:
    response = client_for(user).get(URL, params)
    assert response.status_code == 200, response.json()
    return response.json()


def test_a_flag_arrives_with_the_bill_it_is_about(counter):
    """The link the ticket asks for is the bill's own number - a person clearing
    an exception starts by reading the bill."""
    _bill(counter, 4)  # a hole under it

    body = _list(counter["cashier"])

    assert body["open_count"] == 1
    row = body["rows"][0]
    assert row["kind"] == "number_hole"
    assert row["kind_label"] == "Bills missing before this one"
    assert row["doc_number"].endswith("/SAL/4")
    assert row["store_code"] == counter["store"].code
    assert row["details"]["count"] == 3


def test_a_flag_about_no_particular_bill_says_so_rather_than_leaving_a_gap(counter):
    """A seller's return count is a pattern across bills, so there is no bill to
    link to - and the screen must be able to tell that from a missing field."""
    ContinuityFlag.objects.create(
        kind=ContinuityFlag.Kind.EMPLOYEE_RETURNS,
        store=counter["store"],
        details={"day": BILLED_DAY, "threshold": 5, "sellers": []},
    )
    row = _list(counter["cashier"])["rows"][0]
    assert row["doc_number"] == ""
    assert row["billed_at"] is None


def test_resolving_clears_it_from_the_open_list(counter):
    sale = _bill(counter, 4)
    flag = ContinuityFlag.objects.get(sale=sale)

    response = client_for(counter["cashier"]).put(
        f"{URL}/{flag.id}", {"status": "resolved", "note": "Re-keyed 1-3 from the printed copies"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert response.json()["resolved_by_name"]
    assert _list(counter["cashier"])["open_count"] == 0
    flag.refresh_from_db()
    assert flag.status == ContinuityFlag.Status.RESOLVED
    assert flag.resolved_at is not None
    assert flag.cleared_note == "Re-keyed 1-3 from the printed copies"


def test_ignoring_one_takes_a_reason(counter):
    """ "Dealt with" is evidenced by the thing having changed; "this is fine" is
    evidenced by nothing at all unless a person says why."""
    flag = ContinuityFlag.objects.get(sale=_bill(counter, 4))

    bare = client_for(counter["cashier"]).put(f"{URL}/{flag.id}", {"status": "ignored"})
    assert bare.status_code == 400
    assert bare.json()["code"] == "VALIDATION"

    ok = client_for(counter["cashier"]).put(
        f"{URL}/{flag.id}", {"status": "ignored", "note": "Test bills, never printed"}
    )
    assert ok.status_code == 200
    assert ContinuityFlag.objects.get(pk=flag.id).status == ContinuityFlag.Status.IGNORED


def test_a_flag_cannot_be_cleared_twice(counter):
    """One statement about one person's attention. A second would silently
    replace the first, taking the note and the name with it."""
    flag = ContinuityFlag.objects.get(sale=_bill(counter, 4))
    client_for(counter["cashier"]).put(f"{URL}/{flag.id}", {"status": "resolved"})

    again = client_for(counter["cashier"]).put(f"{URL}/{flag.id}", {"status": "resolved"})

    assert again.status_code == 409
    assert again.json()["code"] == "FLAG_ALREADY_CLEARED"


def test_there_is_no_way_back_to_open(counter):
    flag = ContinuityFlag.objects.get(sale=_bill(counter, 4))
    response = client_for(counter["cashier"]).put(f"{URL}/{flag.id}", {"status": "open"})
    assert response.status_code == 400


def test_clearing_a_flag_leaves_the_bill_alone(counter):
    """A7 in one assertion: nothing on this screen is a correction."""
    sale = _bill(counter, 4)
    before = (sale.docstatus, sale.doc_number, sale.net_paise, sale.updated_at)
    flag = ContinuityFlag.objects.get(sale=sale)

    client_for(counter["cashier"]).put(f"{URL}/{flag.id}", {"status": "resolved"})

    sale.refresh_from_db()
    assert (sale.docstatus, sale.doc_number, sale.net_paise, sale.updated_at) == before


def test_another_stores_flag_is_neither_listed_nor_clearable(counter):
    other = build_store("SEL-RAN")
    stranger = ContinuityFlag.objects.create(
        kind=ContinuityFlag.Kind.NUMBER_HOLE, store=other, details={"day": BILLED_DAY}
    )

    assert _list(counter["cashier"])["open_count"] == 0
    refused = client_for(counter["cashier"]).put(f"{URL}/{stranger.id}", {"status": "resolved"})
    # 404, not 403: a 403 would confirm the row - and the bill behind it - exists.
    assert refused.status_code == 404
    assert refused.json()["code"] == "NOT_FOUND"


def test_the_status_filter_never_moves_the_open_count(counter):
    """The count is the header somebody reads to know whether anything is
    waiting, so a filter must not change what it says."""
    _bill(counter, 4)
    _bill(counter, 8)
    flag = ContinuityFlag.objects.first()
    client_for(counter["cashier"]).put(f"{URL}/{flag.id}", {"status": "resolved"})

    for wanted in ("open", "resolved", "all"):
        assert _list(counter["cashier"], status=wanted)["open_count"] == 1

    assert len(_list(counter["cashier"], status="all")["rows"]) == 2
    assert len(_list(counter["cashier"], status="resolved")["rows"]) == 1


def test_a_day_filter_asks_the_models_own_question(counter):
    """A flag about a bill belongs to the bill's day; one about no bill says
    which day it is about (`ContinuityFlag.for_day`)."""
    _bill(counter, 4)
    ContinuityFlag.objects.create(
        kind=ContinuityFlag.Kind.EMPLOYEE_RETURNS,
        store=counter["store"],
        details={"day": "2026-07-29", "sellers": []},
    )

    assert len(_list(counter["cashier"], date=BILLED_DAY)["rows"]) == 1
    assert len(_list(counter["cashier"], date="2026-07-29")["rows"]) == 1
    assert len(_list(counter["cashier"], date="2026-07-28")["rows"]) == 0


def test_nonsense_filters_are_refused(counter):
    for params in ({"status": "sortof"}, {"date": "yesterday"}, {"date": "2026-02-30"}):
        response = client_for(counter["cashier"]).get(URL, params)
        assert response.status_code == 400, params
        assert response.json()["code"] == "VALIDATION"


def test_head_office_finance_works_the_same_list(counter):
    """ "The Dashboard action queue and HO both see" it, in the ticket's own
    words - so an accountant scoped to the network reads and clears it too."""
    flag = ContinuityFlag.objects.get(sale=_bill(counter, 4))
    accountant = build_accountant()

    assert _list(accountant)["open_count"] == 1
    assert client_for(accountant).put(f"{URL}/{flag.id}", {"status": "resolved"}).status_code == 200


def test_somebody_with_no_money_section_sees_none_of_it(counter):
    """The gate is `money`, not `sell` - a brand manager holds `sell: view` and no
    money at all, and a counter's exceptions are not their business."""
    _bill(counter, 4)
    manager = User.objects.create_user(
        username="flags_brand",
        password=TEST_PASSWORD,
        role=make_role("brand_manager", "Brand manager (flag tests)"),
        scope_type=ScopeType.ALL,
    )
    assert client_for(manager).get(URL).status_code == 403


def test_the_day_a_flag_belongs_to_matches_the_cash_summary(counter):
    """One rule, asked by two screens. The Money section counts these rows and
    this list draws them, and a second copy of "which day is this about" is how
    the count and the list start disagreeing."""
    _bill(counter, 4)
    listed = _list(counter["cashier"], date=BILLED_DAY)["rows"]
    summary = client_for(counter["cashier"]).get("/api/store/cash-summary", {"date": BILLED_DAY})
    assert summary.json()["flags_open"] == len(listed) == 1


def test_todays_flag_is_todays(counter):
    """Belt and braces on the clock: a bill printed today lands on today."""
    today = timezone.localdate()
    _bill(counter, 4, billed_at=f"{today.isoformat()}T06:00:00Z")
    assert len(_list(counter["cashier"], date=today.isoformat())["rows"]) == 1
    assert len(_list(counter["cashier"], date=date(2020, 1, 1).isoformat())["rows"]) == 0
