"""The counter's boot state (#180, D10 step 3).

`GET /api/sell/register` exists because the till owns the bill counter and the
server only accepts what the till already printed. The two copies drift, and each
way of drifting has a different consequence:

  · the till is **ahead** - ordinary, bills are queued and will arrive;
  · the till is **behind** - it lost its local state, and re-issuing a number that
    is already on a posted bill would put two different customers' purchases under
    one Tally key;
  · numbers are **missing underneath** - a machine died holding them, and a human
    re-enters those from paper.

So what is tested here is the frontier, the gaps below it, and that neither is
computed from anything but bills the server has actually numbered.
"""

from __future__ import annotations

import pytest
from _rbac import make_role
from _sell import (
    bill_payload,
    build_cashier,
    build_salesman,
    build_store,
    client_for,
    stock_in,
)

from accounts.models import ScopeType, User
from core.documents import VoucherSeries
from core.fiscal import financial_year
from masters.models import Store
from sell.services.register import HOLE_LIMIT

URL = "/api/sell/register"
SALES_URL = "/api/sell/sales"

pytestmark = pytest.mark.django_db


@pytest.fixture
def counter() -> tuple[Store, User, object]:
    """A store that can sell, its cashier, and somebody to credit the line to.

    The financial year is read from the clock rather than pinned, because the
    endpoint answers for the year it is now: a fixture year would pass today and
    describe an empty counter every 1 April.
    """
    store = build_store("REG-DEO")
    VoucherSeries.objects.get_or_create(fy=financial_year(), store_code=store.code, doc_type="SAL")
    stock_in(store, 50)
    return store, build_cashier(store, "reg_cashier"), build_salesman(store)


def bill(client: object, store: Store, salesman: object, seq: int) -> None:
    """Land one bill at `seq`, through the real accept pipeline."""
    payload = bill_payload(store, salesman, till_seq=seq, fy=financial_year())
    response = client.post(SALES_URL, payload, format="json")  # type: ignore[attr-defined]
    assert response.status_code == 201, response.data


def test_fresh_counter_starts_at_nothing(counter: tuple[Store, User, object]) -> None:
    """A store that has never billed reports zero, not one.

    The till reads this as "the server has accepted nothing", and its own first
    bill is number 1. Answering `1` here would mean the frontier and the next
    number are the same field, and one of the two readers would be wrong.
    """
    store, cashier, _ = counter
    body = client_for(cashier).get(URL).data

    assert body == {
        "fy": financial_year(),
        "last_accepted_seq": 0,
        "holes": [],
        "hole_count": 0,
        "series_open": True,
    }


def test_frontier_follows_the_bills(counter: tuple[Store, User, object]) -> None:
    store, cashier, salesman = counter
    client = client_for(cashier)
    for seq in (1, 2, 3):
        bill(client, store, salesman, seq)

    body = client.get(URL).data

    assert body["last_accepted_seq"] == 3
    assert body["holes"] == []
    assert body["hole_count"] == 0


def test_a_gap_underneath_is_named(counter: tuple[Store, User, object]) -> None:
    """Bills 1, 2 and 5 landed; 3 and 4 are on a machine somewhere.

    The kernel accepts the jump and flags it rather than refusing a printed bill;
    this is where the store finds out *which* numbers to go looking for.
    """
    store, cashier, salesman = counter
    client = client_for(cashier)
    for seq in (1, 2, 5):
        bill(client, store, salesman, seq)

    body = client.get(URL).data

    assert body["last_accepted_seq"] == 5
    assert body["holes"] == [3, 4]
    assert body["hole_count"] == 2


def test_a_late_bill_closes_its_own_hole(counter: tuple[Store, User, object]) -> None:
    """A straggler syncing days later fills the gap it left, and the frontier
    does not move backwards to meet it."""
    store, cashier, salesman = counter
    client = client_for(cashier)
    bill(client, store, salesman, 1)
    bill(client, store, salesman, 3)
    assert client.get(URL).data["holes"] == [2]

    bill(client, store, salesman, 2)

    body = client.get(URL).data
    assert body["last_accepted_seq"] == 3
    assert body["holes"] == []


def test_the_hole_list_is_bounded_but_the_count_is_not(
    counter: tuple[Store, User, object],
) -> None:
    """A till that died at bill 250 leaves 249 holes.

    The boot call names as many as a human can act on and says how many there
    really are; a list nobody can read is not better than a number.
    """
    store, cashier, salesman = counter
    client = client_for(cashier)
    bill(client, store, salesman, HOLE_LIMIT + 50)

    body = client.get(URL).data

    assert body["last_accepted_seq"] == HOLE_LIMIT + 50
    assert body["hole_count"] == HOLE_LIMIT + 49
    assert len(body["holes"]) == HOLE_LIMIT
    assert body["holes"][:2] == [1, 2]


def test_last_year_is_not_this_year(counter: tuple[Store, User, object]) -> None:
    """The counter restarts at 1 every April, so a previous year's bills must not
    show up as this year's frontier."""
    store, cashier, salesman = counter
    client = client_for(cashier)
    VoucherSeries.objects.get_or_create(fy="20-21", store_code=store.code, doc_type="SAL")
    payload = bill_payload(store, salesman, till_seq=99, fy="20-21")
    assert client.post(SALES_URL, payload, format="json").status_code == 201

    body = client.get(URL).data

    assert body["fy"] == financial_year()
    assert body["last_accepted_seq"] == 0


def test_a_missing_series_says_so_at_open(counter: tuple[Store, User, object]) -> None:
    """No series row means every bill this store prints today will fail to sync.

    The till learns it at store open, when somebody can still ring head office,
    rather than at the first customer.
    """
    store, _, _ = counter
    other = build_store("REG-GAY")
    VoucherSeries.objects.filter(
        fy=financial_year(), store_code=other.code, doc_type="SAL"
    ).delete()
    cashier = build_cashier(other, "reg_cashier_gay")

    body = client_for(cashier).get(URL).data

    assert body["series_open"] is False


def test_a_two_store_login_is_never_a_till(counter: tuple[Store, User, object]) -> None:
    """The same refusal the dataset gives, and for the same reason: a register is
    one counter's numbering, and a person who can see two stores has no counter."""
    store, cashier, _ = counter
    cashier.stores.add(build_store("REG-GAY"))

    response = client_for(cashier).get(URL)

    assert response.status_code == 403
    assert response.data["code"] == "TILL_SCOPE"


def test_reading_yesterdays_bills_is_not_running_a_till(
    counter: tuple[Store, User, object],
) -> None:
    """`sell: view` reads bills back. It does not get the counter's state."""
    store, _, _ = counter
    role = make_role("reg_viewer", "Reads bills only")
    role.section_access = {
        **role.section_access,
        "sell": {"capability": "view", "label": "Read bills"},
    }
    role.save(update_fields=["section_access"])
    viewer = User.objects.create_user(
        username="reg_viewer_user", password="x", role=role, scope_type=ScopeType.STORE
    )
    viewer.stores.add(store)

    assert client_for(viewer).get(URL).status_code == 403
