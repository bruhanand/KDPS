"""The held-bill mirror: what head office is allowed to know about a parked cart.

A hold is a cart the counter put down to serve the next customer (grill Q13). It
is **till-local**: the counter is authoritative, and this endpoint exists for one
reason only - so the store Dashboard can say "2 bills on hold" without the
manager having to walk to the counter and look.

That makes the two things worth proving here unusual for this app:

  · **A hold moves nothing.** No document, no number, no stock, no money. A test
    that only checked the rows landed would pass just as happily on an
    implementation that billed them.
  · **The push replaces.** The till sends its whole list every time, because a
    hold that was resumed at the counter has to *disappear* from the Dashboard,
    and there is no per-hold delete for it to send. Replace-all is how a mirror
    of somebody else's truth stays a mirror.
"""

from __future__ import annotations

import uuid

import pytest
from _sell import (
    build_cashier,
    build_piece,
    build_salesman,
    build_store,
    client_for,
)

from core.documents import VoucherSeries
from sell.models import HeldBill, Sale
from stockledger.models import StockLedgerEntry

URL = "/api/sell/held-bills"


def hold(label: str = "Mrs Sharma", **overrides: object) -> dict[str, object]:
    """One parked cart, in the shape the till pushes."""
    payload: dict[str, object] = {
        "held_uuid": str(uuid.uuid4()),
        "label": label,
        "held_at": "2026-07-31T11:05:00Z",
        "expires_policy": "today",
        "payload": {"lines": [{"barcode": "8901000000011", "qty": 1}]},
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def counter(db):
    store = build_store()
    build_piece()
    cashier = build_cashier(store)
    build_salesman(store)
    return {"store": store, "cashier": cashier, "client": client_for(cashier)}


def test_the_counters_list_becomes_the_stores_list(counter):
    response = counter["client"].put(
        URL, {"held": [hold("Mrs Sharma"), hold("The man in the blue shirt")]}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == {"count": 2}
    assert set(HeldBill.objects.values_list("label", flat=True)) == {
        "Mrs Sharma",
        "The man in the blue shirt",
    }


def test_a_resumed_hold_disappears_because_the_push_replaces(counter):
    kept, resumed = hold("Kept"), hold("Resumed")
    counter["client"].put(URL, {"held": [kept, resumed]}, format="json")

    response = counter["client"].put(URL, {"held": [kept]}, format="json")

    assert response.json() == {"count": 1}
    assert list(HeldBill.objects.values_list("label", flat=True)) == ["Kept"]


def test_an_empty_push_is_a_counter_with_nothing_parked(counter):
    counter["client"].put(URL, {"held": [hold()]}, format="json")

    response = counter["client"].put(URL, {"held": []}, format="json")

    assert response.status_code == 200
    assert response.json() == {"count": 0}
    assert not HeldBill.objects.exists()


def test_a_hold_that_is_still_held_keeps_its_row_rather_than_being_reborn(counter):
    parked = hold("Mrs Sharma")
    counter["client"].put(URL, {"held": [parked]}, format="json")
    first = HeldBill.objects.get()

    parked["label"] = "Mrs Sharma (waiting)"
    counter["client"].put(URL, {"held": [parked]}, format="json")

    again = HeldBill.objects.get()
    assert again.pk == first.pk
    assert again.label == "Mrs Sharma (waiting)"


def test_one_stores_push_never_touches_another_stores_holds(counter):
    other_store = build_store(code="SEL-RAN", state="20")
    other = build_cashier(other_store, username="ran_cashier")
    client_for(other).put(URL, {"held": [hold("Ranchi's customer")]}, format="json")

    counter["client"].put(URL, {"held": [hold("Deoghar's customer")]}, format="json")

    assert set(HeldBill.objects.values_list("store__code", "label")) == {
        ("SEL-RAN", "Ranchi's customer"),
        ("SEL-DEO", "Deoghar's customer"),
    }


def test_a_hold_moves_no_stock_no_money_and_no_number(counter):
    before = VoucherSeries.objects.get(store_code=counter["store"].code, doc_type="SAL").next_seq

    counter["client"].put(URL, {"held": [hold(), hold("Second")]}, format="json")

    assert not Sale.objects.exists()
    assert not StockLedgerEntry.objects.filter(store=counter["store"]).exists()
    assert (
        VoucherSeries.objects.get(store_code=counter["store"].code, doc_type="SAL").next_seq
        == before
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"held": [{"label": "no uuid"}]},
        {"held": [hold(expires_policy="for ever")]},
        {"held": [hold(held_uuid="not-a-uuid")]},
    ],
)
def test_a_push_the_contract_does_not_describe_is_refused(counter, body):
    response = counter["client"].put(URL, body, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"


def test_a_login_that_is_two_stores_is_not_a_till(counter):
    counter["cashier"].stores.add(build_store(code="SEL-RAN", state="20"))

    response = counter["client"].put(URL, {"held": [hold()]}, format="json")

    assert response.status_code == 403
    assert response.json()["code"] == "TILL_SCOPE"


def test_somebody_who_may_only_read_bills_may_not_park_one(counter, django_user_model):
    from _creds import TEST_PASSWORD
    from _rbac import make_role

    from accounts.models import ScopeType
    from accounts.sections import CAP_VIEW

    role = make_role("sell_reader", "Reads bills (held-bill tests)")
    role.section_access = {**role.section_access, "sell": {"capability": CAP_VIEW}}
    role.save(update_fields=["section_access"])
    reader = django_user_model.objects.create_user(
        username="held_reader",
        password=TEST_PASSWORD,
        role=role,
        scope_type=ScopeType.STORE,
    )
    reader.stores.add(counter["store"])

    response = client_for(reader).put(URL, {"held": [hold()]}, format="json")

    assert response.status_code == 403
    assert not HeldBill.objects.exists()
