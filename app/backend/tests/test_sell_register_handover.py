"""Moving a store's counter onto a new machine (#189, grill Q1).

The till owns the bill counter, so when the counter machine dies it takes the
counter with it. There is no automatic recovery for that and there deliberately
is not one: a machine that stopped syncing looks exactly like a machine that is
offline, and a server that reassigned the series on its own would be guessing
about bills that are printed and in customers' hands.

So the recovery is an act. A manager says the machine has changed, gives a
reason, and the server answers with two things - where to resume, and the numbers
it never received. Every one of those numbers is a receipt in a drawer that has
to be keyed back in under its original number, which is the last test here.
"""

from __future__ import annotations

import pytest
from _rbac import make_role
from _sell import (
    bill_payload,
    build_cashier,
    build_manager,
    build_salesman,
    build_store,
    client_for,
    stock_in,
)

from accounts.models import ScopeType, User
from core.documents import VoucherSeries
from core.fiscal import financial_year
from masters.models import Store
from sell.models import RegisterHandover, Sale
from sell.services.register import HOLE_LIMIT

URL = "/api/sell/register/handover"
SALES_URL = "/api/sell/sales"

pytestmark = pytest.mark.django_db


@pytest.fixture
def counter() -> tuple[Store, User, User, object]:
    """A store that can sell, its cashier, its manager, and a name for the line."""
    store = build_store("HND-DEO")
    VoucherSeries.objects.get_or_create(fy=financial_year(), store_code=store.code, doc_type="SAL")
    stock_in(store, 50)
    return (
        store,
        build_cashier(store, "hnd_cashier"),
        build_manager(store, "hnd_manager"),
        build_salesman(store),
    )


def bill(client: object, store: Store, salesman: object, seq: int, **overrides: object) -> object:
    """Land one bill at `seq`, through the real accept pipeline."""
    payload = bill_payload(store, salesman, till_seq=seq, fy=financial_year(), **overrides)
    return client.post(SALES_URL, payload, format="json")  # type: ignore[attr-defined]


def test_a_cashier_cannot_hand_the_counter_over(
    counter: tuple[Store, User, User, object],
) -> None:
    """`sell: operate` bills. It does not decide that the machine has changed.

    The person whose till just died is exactly the person who should be fetching
    a manager: a handover leaves holes in a numbered money series, and somebody
    has to go and find the paper for each one.
    """
    store, cashier, _, _ = counter

    response = client_for(cashier).post(URL, {"reason": "machine died"}, format="json")

    assert response.status_code == 403
    assert not RegisterHandover.objects.exists()


def test_a_manager_hands_over_and_it_is_recorded(
    counter: tuple[Store, User, User, object],
) -> None:
    """The whole act: who, why, and what the frontier was at the time."""
    store, cashier, manager, salesman = counter
    till = client_for(cashier)
    for seq in (1, 2, 3):
        assert bill(till, store, salesman, seq).status_code == 201

    response = client_for(manager).post(URL, {"reason": "counter machine replaced"}, format="json")

    assert response.status_code == 200
    assert response.data == {"resume_from_seq": 4, "unsynced_hint": [], "hole_count": 0}
    row = RegisterHandover.objects.get()
    assert row.store_id == store.id
    assert row.actor_id == manager.id
    assert row.reason == "counter machine replaced"
    assert row.last_accepted_seq == 3
    assert row.fy == financial_year()


def test_the_unsynced_bills_are_named(counter: tuple[Store, User, User, object]) -> None:
    """Bills 1, 2 and 5 landed; 3 and 4 died with the machine.

    Those two are what the new till's screen walks somebody through re-entering,
    so they have to come back by number rather than as a count.
    """
    store, cashier, manager, salesman = counter
    till = client_for(cashier)
    for seq in (1, 2, 5):
        assert bill(till, store, salesman, seq).status_code == 201

    body = client_for(manager).post(URL, {"reason": "till dead"}, format="json").data

    assert body["resume_from_seq"] == 6
    assert body["unsynced_hint"] == [3, 4]
    assert body["hole_count"] == 2


def test_a_long_hole_list_says_how_long_it_really_is(
    counter: tuple[Store, User, User, object],
) -> None:
    """A machine that died at bill 250 leaves 249 receipts in a drawer.

    The response names as many as a person can work through and counts the rest;
    a screen reading "200 (1, 2, 3 …)" against a true 249 would tell somebody
    they were finished when they were not.
    """
    store, cashier, manager, salesman = counter
    till = client_for(cashier)
    assert bill(till, store, salesman, HOLE_LIMIT + 50).status_code == 201

    body = client_for(manager).post(URL, {"reason": "till dead"}, format="json").data

    assert body["hole_count"] == HOLE_LIMIT + 49
    assert len(body["unsynced_hint"]) == HOLE_LIMIT


def test_a_reason_is_required(counter: tuple[Store, User, User, object]) -> None:
    """Without one this is an unexplained gap in a bill series, which is the
    thing the row exists to prevent."""
    store, _, manager, _ = counter
    client = client_for(manager)

    for body in ({}, {"reason": "   "}):
        response = client.post(URL, body, format="json")
        assert response.status_code == 400, body
        assert response.data["code"] == "VALIDATION"
    assert not RegisterHandover.objects.exists()


def test_a_two_store_login_has_no_counter_to_hand_over(
    counter: tuple[Store, User, User, object],
) -> None:
    """The dataset's refusal, in the dataset's words: a handover is about one
    counter's numbering, so a person who can see two shops has none to move."""
    store, _, manager, _ = counter
    manager.stores.add(build_store("HND-GAY"))

    response = client_for(manager).post(URL, {"reason": "machine died"}, format="json")

    assert response.status_code == 403
    assert response.data["code"] == "TILL_SCOPE"
    assert not RegisterHandover.objects.exists()


def test_the_counter_is_not_moved_by_the_handover(
    counter: tuple[Store, User, User, object],
) -> None:
    """The server records the act and reads the state back. It does not renumber.

    `VoucherSeries.next_seq` follows bills the server has *accepted*; a handover
    that advanced it would be the server holding an opinion about a number nobody
    has printed - and the next straggler from the old machine would then look
    like a hole that had been jumped over rather than one being filled.
    """
    store, cashier, manager, salesman = counter
    till = client_for(cashier)
    assert bill(till, store, salesman, 1).status_code == 201
    series = VoucherSeries.objects.get(fy=financial_year(), store_code=store.code, doc_type="SAL")
    before = series.next_seq

    client_for(manager).post(URL, {"reason": "machine died"}, format="json")

    series.refresh_from_db()
    assert series.next_seq == before


def test_a_paper_bill_takes_its_original_number_exactly_once(
    counter: tuple[Store, User, User, object],
) -> None:
    """The other half of the handover: keying the drawer back in.

    Bill 2 was printed on the dead machine and never synced. It is re-entered
    from the printed copy under its own number and marked `paper`, which closes
    the hole. Sending it a second time - two people working through the same
    drawer - is refused rather than accepted as a second bill, because the number
    is the Tally key and two sales under one key can never be told apart.
    """
    store, cashier, manager, salesman = counter
    till = client_for(cashier)
    for seq in (1, 3):
        assert bill(till, store, salesman, seq).status_code == 201
    assert client_for(manager).post(URL, {"reason": "dead till"}, format="json").data[
        "unsynced_hint"
    ] == [2]

    reentered = bill(till, store, salesman, 2, origin="paper")
    assert reentered.status_code == 201
    assert Sale.objects.get(store=store, fy=financial_year(), till_seq=2).origin == "paper"

    again = bill(till, store, salesman, 2, origin="paper")
    assert again.status_code == 409
    assert again.data["code"] == "BILL_NO_TAKEN"
    assert Sale.objects.filter(store=store, fy=financial_year(), till_seq=2).count() == 1


def test_reading_bills_back_is_not_handing_a_counter_over(
    counter: tuple[Store, User, User, object],
) -> None:
    """`sell: view` reads yesterday's bills. It moves nothing."""
    store, _, _, _ = counter
    role = make_role("hnd_viewer", "Reads bills only")
    role.section_access = {
        **role.section_access,
        "sell": {"capability": "view", "label": "Read bills"},
    }
    role.save(update_fields=["section_access"])
    viewer = User.objects.create_user(
        username="hnd_viewer_user", password="x", role=role, scope_type=ScopeType.STORE
    )
    viewer.stores.add(store)

    response = client_for(viewer).post(URL, {"reason": "machine died"}, format="json")

    assert response.status_code == 403
    assert not RegisterHandover.objects.exists()
