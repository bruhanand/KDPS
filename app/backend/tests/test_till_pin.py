"""A manager's counter PIN - the one credential that leaves the building (#182).

The PIN authorises an exception at a till that is offline, so it is verified on
the device against a hash that came down in the dataset. That makes three things
worth pinning here, and they are the three this suite is organised by:

  · **Only a counter's own people may hold one.** The hash reaches a shop-floor
    machine, so a person whose boundary is not stores, or who does not hold the
    rung the sale contract calls "a manager of this store", cannot set one.
  · **Nobody sets somebody else's.** An override names who stood at the counter;
    an administrator who could set a manager's PIN could accept an exception in
    that manager's name. So the endpoint asks for the caller's own password and
    writes only the caller's own row.
  · **It is hashed the way the till can read.** PBKDF2-SHA256, not the project's
    default bcrypt, because a browser can verify the first offline and not the
    second - see `accounts/till_pin.py`.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _sell import build_cashier, build_manager, build_store
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from accounts.till_pin import may_hold_till_pin

URL = "/api/auth/me/till-pin"


@pytest.fixture
def store(db):
    return build_store()


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _put(user: User, **body: object):
    return _client(user).put(URL, body, format="json")


def test_a_manager_sets_their_own_pin(store):
    manager = build_manager(store)

    response = _put(manager, current_password=TEST_PASSWORD, pin="4813")

    assert response.status_code == 200
    manager.refresh_from_db()
    assert manager.till_pin_hash.startswith("pbkdf2_sha256$")


def test_the_hash_is_one_a_browser_can_verify(store):
    """The till has PBKDF2 and no bcrypt. A hash it cannot read is not a
    credential, however strong it is."""
    manager = build_manager(store)

    _put(manager, current_password=TEST_PASSWORD, pin="4813")

    manager.refresh_from_db()
    algorithm, iterations, salt, digest = manager.till_pin_hash.split("$")
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) > 0
    assert salt and digest


def test_the_pin_is_never_stored_as_typed(store):
    manager = build_manager(store)

    _put(manager, current_password=TEST_PASSWORD, pin="4813")

    manager.refresh_from_db()
    assert "4813" not in manager.till_pin_hash


def test_setting_it_again_replaces_it(store):
    manager = build_manager(store)
    _put(manager, current_password=TEST_PASSWORD, pin="4813")
    manager.refresh_from_db()
    first = manager.till_pin_hash

    _put(manager, current_password=TEST_PASSWORD, pin="991122")

    manager.refresh_from_db()
    assert manager.till_pin_hash != first


def test_the_wrong_password_sets_nothing(store):
    manager = build_manager(store)

    response = _put(manager, current_password="not-my-password", pin="4813")

    assert response.status_code == 403
    assert response.json()["code"] == "PASSWORD_WRONG"
    manager.refresh_from_db()
    assert manager.till_pin_hash == ""


def test_a_cashier_cannot_hold_a_counter_pin(store):
    """`sell: operate` is doing the work; the PIN is the second eye on it.

    Refused by the section gate itself, in DRF's own words - the same shape every
    other capability refusal in this project wears.
    """
    cashier = build_cashier(store)

    response = _put(cashier, current_password=TEST_PASSWORD, pin="4813")

    assert response.status_code == 403
    cashier.refresh_from_db()
    assert cashier.till_pin_hash == ""


def test_somebody_who_is_not_at_a_store_cannot_hold_one(store):
    """The half a section gate cannot ask.

    A network-wide administrator may hold `sell: approve` on the stored matrix
    and still not be one of any counter's people - and this hash goes down to
    fifty shop-floor devices in the dataset, or to none.
    """
    everywhere = build_manager(store, username="sell_manager_network")
    everywhere.scope_type = ScopeType.ALL
    everywhere.save(update_fields=["scope_type"])

    response = _put(everywhere, current_password=TEST_PASSWORD, pin="4813")

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_A_TILL_MANAGER"
    everywhere.refresh_from_db()
    assert everywhere.till_pin_hash == ""


@pytest.mark.parametrize(
    "pin",
    [
        pytest.param("12a4", id="not all digits"),
        pytest.param("123", id="too short"),
        pytest.param("1234567", id="too long"),
        pytest.param("1111", id="one digit repeated"),
        pytest.param("", id="empty"),
    ],
)
def test_what_is_not_a_pin(store, pin):
    manager = build_manager(store)

    response = _put(manager, current_password=TEST_PASSWORD, pin=pin)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"
    manager.refresh_from_db()
    assert manager.till_pin_hash == ""


def test_the_profile_says_whether_a_pin_is_set(store):
    """The counter-PIN card has to be able to say "you have one" without ever
    being able to read it."""
    manager = build_manager(store)
    client = _client(manager)

    assert client.get("/api/auth/me").json()["has_till_pin"] is False
    _put(manager, current_password=TEST_PASSWORD, pin="4813")
    assert client.get("/api/auth/me").json()["has_till_pin"] is True


def test_a_hash_is_never_in_the_profile(store):
    manager = build_manager(store)
    _put(manager, current_password=TEST_PASSWORD, pin="4813")

    body = _client(manager).get("/api/auth/me").json()

    assert "till_pin_hash" not in body


def test_who_may_hold_one(store):
    """The one sentence the dataset's manager list is also built from."""
    assert may_hold_till_pin(build_manager(store)) is True
    assert may_hold_till_pin(build_cashier(store)) is False

    manager = build_manager(store, username="sell_manager_deactivated")
    manager.is_active = False
    assert may_hold_till_pin(manager) is False
