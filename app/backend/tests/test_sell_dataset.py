"""The till's sync-down feed (#179, D10 step 3).

`GET /api/sell/dataset` is the one place the counter learns anything: what it may
sell, at what ticket price, at what tax, who is standing behind it, and which
credit notes are still worth money. The till then bills **offline** off that copy,
so what is tested here is not "did the endpoint answer" but three sharper things.

  · **A bootstrap and a delta describe the same world.** A till that has been
    offline for a week catches up by cursor, so a delta that misses a row is a
    counter selling last week's price - and a delta that cannot express a
    *removal* is a counter selling a piece head office withdrew.
  · **No cost, ever.** H2. The dataset is a file on a shop-floor device; a store
    person may know the ticket price of everything and the cost of nothing, and
    `StockOnHand` carries `net_value_paise` right beside the quantity this payload
    wants. The test for that is deliberately blunt: walk the whole payload and
    fail on any key or any number that could be a cost.
  · **One store, and the manager PINs of that store alone.** The list of
    override PIN hashes is a credential set that leaves the building. A scope
    that resolved to "all stores" and shipped fifty stores' hashes to one till
    would pass every shape assertion in this file.

The four acceptance criteria on the ticket, in order: full-then-delta including
deletions; no cost or margin field anywhere; exactly one store, with its own
salesmen and managers; offer rows carrying their dates inside the data.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _sell import (
    COST_PAISE,
    MRP_PAISE,
    SALES_URL,
    bill_payload,
    build_cashier,
    build_manager,
    build_salesman,
    build_store,
    client_for,
    stock_in,
)
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.models import ScopeType, User
from core.documents import DocStatus
from masters.models import Cohort, GstSlab, Sku
from sell.models import CreditNote
from stockledger.models import StockOnHand

URL = "/api/sell/dataset"

#: Every section a till expects to find, whatever else changes.
SECTIONS = [
    "cursor",
    "full",
    "store",
    "items",
    "stock",
    "gst_slabs",
    "offers",
    "credit_notes",
    "salesmen",
    "managers",
    "deleted",
]

#: Words that name a cost, a margin or a stock valuation. A key containing any of
#: them has no business in a payload that goes to a shop floor. `net_value_paise`
#: is the live hazard: it sits on the very `StockOnHand` row the `stock` section
#: is built from.
COST_WORDS = ["cost", "margin", "profit", "landed", "purchase", "wsp", "value_paise", "valuation"]


def _walk(node: Any, path: str = "") -> list[tuple[str, Any]]:
    """Every (path, leaf) pair in a JSON payload, so an assertion can be blunt."""
    if isinstance(node, dict):
        return [pair for key, value in node.items() for pair in _walk(value, f"{path}.{key}")]
    if isinstance(node, list):
        return [pair for i, item in enumerate(node) for pair in _walk(item, f"{path}[{i}]")]
    return [(path, node)]


def assert_no_cost_anywhere(payload: dict[str, Any]) -> None:
    """H2, asserted over the whole tree rather than section by section.

    Both halves matter. The key check catches a field somebody adds later; the
    *value* check catches the same field renamed to something innocent, because
    the fixture's cost is a number that appears nowhere else in the world.
    """
    for path, value in _walk(payload):
        lowered = path.lower()
        assert not any(word in lowered for word in COST_WORDS), f"cost-shaped key at {path}"
        assert value != COST_PAISE, f"the fixture's unit cost surfaced at {path}"
        assert value != COST_PAISE * 3, f"a stock valuation surfaced at {path}"


@pytest.fixture
def till(db):
    """A store with three pieces on the shelf and a counter person to sell them."""
    store = build_store()
    stock_in(store, 3)
    cashier = build_cashier(store)
    salesman = build_salesman(store)
    return {
        "store": store,
        "cashier": cashier,
        "salesman": salesman,
        "client": client_for(cashier),
    }


# --- Criterion 3: one store, and its own people ----------------------------


def test_bootstrap_carries_every_section_for_one_store(till):
    body = till["client"].get(URL).json()

    assert sorted(body) == sorted(SECTIONS)
    assert body["full"] is True
    assert body["store"] == {
        "code": till["store"].code,
        "gstin": till["store"].gstin.gstin,
        "state_code": till["store"].gstin.state_code,
    }
    assert [row["barcode"] for row in body["stock"]] == ["8901000000011"]
    assert body["stock"][0]["qty"] == 3
    assert [(row["barcode"], row["season"]) for row in body["items"]] == [("8901000000011", "FW25")]
    item = body["items"][0]
    assert item["mrp_paise"] == MRP_PAISE
    assert item["brand"] == "MUFTI"
    assert item["size"] == "M"
    assert item["color"] == "NAVY"
    assert item["hsn"] == "6205"
    assert item["no_discount"] is False
    assert [row["code"] for row in body["salesmen"]] == ["ALIE"]


def test_a_multi_store_login_is_not_a_till(db):
    """`TILL_SCOPE`, and its own code - the till is a store login by construction.

    An area manager holding `sell: operate` over two stores is refused rather than
    served an arbitrary one of them, because there is no honest answer: the
    payload names a GSTIN, a set of PIN hashes and one shelf.
    """
    first = build_store()
    second = build_store(code="SEL-BKR")
    stock_in(first, 1)
    user = User.objects.create_user(
        username="two_store_boss",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Two-store manager"),
        scope_type=ScopeType.STORE,
    )
    user.stores.add(first, second)

    response = client_for(user).get(URL)

    assert response.status_code == 403
    assert response.json()["code"] == "TILL_SCOPE"


def test_a_network_login_is_not_a_till(db):
    """Nor is somebody who can see everything - "all stores" is not a counter."""
    build_store()
    user = User.objects.create_user(
        username="network_ops",
        password=TEST_PASSWORD,
        role=make_role("it_admin", "IT admin"),
        scope_type=ScopeType.ALL,
    )

    response = client_for(user).get(URL)

    assert response.status_code == 403
    assert response.json()["code"] == "TILL_SCOPE"


def test_a_login_without_the_sell_rung_is_refused(till):
    """The capability gate, ahead of the scope one."""
    outsider = User.objects.create_user(
        username="warehouse_hand",
        password=TEST_PASSWORD,
        role=make_role("warehouse", "Warehouse"),
        scope_type=ScopeType.STORE,
    )
    outsider.stores.add(till["store"])

    assert client_for(outsider).get(URL).status_code == 403


def test_another_stores_shelf_salesmen_and_managers_never_arrive(till):
    """The scope-negative case, on all three store-owned sections at once."""
    other = build_store(code="SEL-HZB")
    stock_in(other, 5, barcode="8901000000099")
    build_salesman(other, code="ZZZZ")
    stranger = build_manager(other, username="hzb_manager")
    stranger.till_pin_hash = "pbkdf2$stranger"
    stranger.save(update_fields=["till_pin_hash"])

    body = till["client"].get(URL).json()

    assert "8901000000099" not in [row["barcode"] for row in body["stock"]]
    assert "8901000000099" not in [row["barcode"] for row in body["items"]]
    assert "ZZZZ" not in [row["code"] for row in body["salesmen"]]
    assert body["managers"] == []


def test_managers_carry_a_pin_hash_and_only_this_stores_managers_do(till):
    """`sell >= approve` at this store, with a PIN set. Nobody else.

    Three exclusions are asserted together because each one on its own would look
    like an oversight: the cashier standing at this very counter does not hold the
    rung, a manager who never set a PIN is not a credential, and a network
    administrator whose matrix cell says `sell: manage` is still not one of this
    store's people - their hash has no business on a shop-floor device.
    """
    manager = build_manager(till["store"], username="deo_manager")
    manager.till_pin_hash = "pbkdf2$deo"
    manager.save(update_fields=["till_pin_hash"])
    pinless = build_manager(till["store"], username="deo_manager_no_pin")
    admin = User.objects.create_user(
        username="it_admin_everywhere",
        password=TEST_PASSWORD,
        role=make_role("it_admin", "IT admin"),
        scope_type=ScopeType.ALL,
    )
    admin.stores.add(till["store"])

    body = till["client"].get(URL).json()

    assert body["managers"] == [
        {
            "user_id": manager.id,
            "name": manager.full_name or manager.username,
            "till_pin_hash": "pbkdf2$deo",
        }
    ]
    assert pinless.id not in [row["user_id"] for row in body["managers"]]
    assert admin.id not in [row["user_id"] for row in body["managers"]]
    assert till["cashier"].id not in [row["user_id"] for row in body["managers"]]


# --- Criterion 2: no cost, anywhere ---------------------------------------


def test_no_cost_or_margin_field_appears_in_the_payload(till):
    """H2. The shelf is worth ₹2,100 at cost and the payload must not know it."""
    manager = build_manager(till["store"], username="deo_manager")
    manager.till_pin_hash = "pbkdf2$deo"
    manager.save(update_fields=["till_pin_hash"])
    CreditNote.objects.create(
        store=till["store"], fy="26-27", value_paise=120000, expires_on=date(2027, 1, 30)
    ).post()

    assert StockOnHand.objects.get(store=till["store"]).net_value_paise == COST_PAISE * 3
    assert_no_cost_anywhere(till["client"].get(URL).json())


# --- Criterion 4: dated rules ride inside the data -------------------------


def test_gst_slabs_carry_their_own_effective_date(till):
    """The till starts and stops a tax rate on its own clock (grill Q3)."""
    GstSlab.objects.create(
        name="Apparel (from Oct)",
        hsn_prefix="61",
        threshold_paise=250000,
        rate_below=Decimal("5.00"),
        rate_above=Decimal("18.00"),
        effective_from=date(2026, 10, 1),
    )

    slabs = till["client"].get(URL).json()["gst_slabs"]

    future = next(row for row in slabs if row["effective_from"] == "2026-10-01")
    assert future["hsn_prefix"] == "61"
    assert future["rate_below"] == "5.00"
    assert future["rate_above"] == "18.00"
    assert future["threshold_paise"] == 250000


def test_offers_is_present_and_empty_until_the_rulebook_lands(till):
    """Empty, not absent: "no offers running" is something a till must be able to
    read. The rulebook is #183; when it lands each row carries its own dates."""
    assert till["client"].get(URL).json()["offers"] == []


# --- Criterion 1: full then delta, including deletions ---------------------


def test_a_delta_returns_only_what_changed_since_the_cursor(till):
    first = till["client"].get(URL).json()
    cursor = _cursor_now()

    quiet = till["client"].get(URL, {"since": cursor}).json()

    assert quiet["full"] is False
    assert quiet["items"] == []
    assert quiet["stock"] == []
    # The small sections are sent whole on every response - a delta over five
    # rows saves nothing and would need a deletion channel of its own.
    assert [row["code"] for row in quiet["salesmen"]] == ["ALIE"]
    assert quiet["store"] == first["store"]

    Sku.objects.filter(barcode="8901000000011").update(mrp_paise=199900, updated_at=timezone.now())
    Cohort.objects.filter(barcode="8901000000011").update(mrp_paise=199900)

    moved = till["client"].get(URL, {"since": cursor}).json()

    assert [row["barcode"] for row in moved["items"]] == ["8901000000011"]
    assert moved["items"][0]["mrp_paise"] == 199900


def test_a_pieces_first_arrival_at_this_store_reaches_the_delta(till):
    """A cohort bought long ago, arriving here today, is new *to this till*.

    The watermark that moves is the stock projection's, not the item master's, so
    a delta keyed on `Cohort.updated_at` alone would send the till a quantity for
    a barcode it cannot describe or price.
    """
    cursor = _cursor_now()
    Sku.objects.filter(barcode="8901000000011").update(
        updated_at=timezone.now() - timedelta(days=9)
    )
    Cohort.objects.filter(barcode="8901000000011").update(
        updated_at=timezone.now() - timedelta(days=9)
    )
    stock_in(till["store"], 2, barcode="8901000000022")
    Sku.objects.filter(barcode="8901000000022").update(
        updated_at=timezone.now() - timedelta(days=9)
    )
    Cohort.objects.filter(barcode="8901000000022").update(
        updated_at=timezone.now() - timedelta(days=9)
    )

    body = till["client"].get(URL, {"since": cursor}).json()

    assert [row["barcode"] for row in body["items"]] == ["8901000000022"]
    assert [row["barcode"] for row in body["stock"]] == ["8901000000022"]


def test_a_withdrawn_item_arrives_as_a_deletion(till):
    """Criterion 1's teeth: the delta can say "stop selling this".

    Deactivating a SKU is the only withdrawal that exists - a cohort is a buying
    fact and a stock row falls to nought rather than vanishing - so the barcode is
    the identity a removal travels under.
    """
    cursor = till["client"].get(URL).json()["cursor"]

    Sku.objects.filter(barcode="8901000000011").update(is_active=False, updated_at=timezone.now())

    body = till["client"].get(URL, {"since": cursor}).json()

    assert body["deleted"]["items"] == ["8901000000011"]
    assert body["items"] == []
    # And a fresh till never hears about it at all: there is nothing to delete
    # from an empty cache, and an inactive piece is simply not for sale.
    fresh = till["client"].get(URL).json()
    assert fresh["deleted"]["items"] == []
    assert fresh["items"] == []


def test_an_open_credit_note_rides_down_and_a_spent_one_is_deleted(till):
    """The note's balance is derived from redemption rows, so the delta is too.

    A submitted document cannot be UPDATEd - the FSM trigger refuses it - so
    spending a note moves no column on it. What moves is a redemption row, and the
    watermark has to read that or a till would go on offering money already spent.
    """
    note = CreditNote.objects.create(
        store=till["store"],
        fy="26-27",
        value_paise=120000,
        expires_on=timezone.localdate() + timedelta(days=180),
    )
    note.post()

    body = till["client"].get(URL).json()
    assert body["credit_notes"] == [
        {"number": note.doc_number, "remaining_paise": 120000, "expires_on": str(note.expires_on)}
    ]
    cursor = body["cursor"]

    _spend(note, till, 120000)

    delta = till["client"].get(URL, {"since": cursor}).json()
    assert delta["credit_notes"] == []
    assert delta["deleted"]["credit_notes"] == [note.doc_number]


def test_a_partly_spent_note_arrives_with_its_remaining_balance(till):
    note = CreditNote.objects.create(
        store=till["store"],
        fy="26-27",
        value_paise=120000,
        expires_on=timezone.localdate() + timedelta(days=180),
    )
    note.post()
    cursor = till["client"].get(URL).json()["cursor"]

    _spend(note, till, 50000)

    delta = till["client"].get(URL, {"since": cursor}).json()
    assert delta["credit_notes"] == [
        {"number": note.doc_number, "remaining_paise": 70000, "expires_on": str(note.expires_on)}
    ]
    assert delta["deleted"]["credit_notes"] == []


def test_a_note_that_expired_while_the_till_was_offline_arrives_as_a_deletion(till, monkeypatch):
    """Nothing was written when it expired - a date simply passed (Rule 11).

    So this arm of the delta cannot be a watermark comparison: it has to ask which
    notes crossed their own deadline between the cursor and today, or a till
    offline over a long weekend would keep honouring one.

    The clock is moved rather than the row's history, because the row has no
    history to move: a submitted document may not be UPDATEd (the FSM trigger
    refuses it), so a note's `updated_at` cannot be back-dated in a fixture. And
    the cursor is taken *after* the note was posted on purpose - that leaves the
    watermark arm unable to match, so only the deadline arm can be what selects
    it, which is the thing this test is about.
    """
    note = CreditNote.objects.create(
        store=till["store"],
        fy="26-27",
        value_paise=120000,
        expires_on=timezone.localdate() + timedelta(days=1),
    )
    note.post()
    cursor = _cursor_now()
    assert till["client"].get(URL, {"since": cursor}).json()["credit_notes"] == []

    _three_days_later(monkeypatch)
    delta = till["client"].get(URL, {"since": cursor}).json()

    assert delta["deleted"]["credit_notes"] == [note.doc_number]
    assert delta["credit_notes"] == []


def test_a_cancelled_note_arrives_as_a_deletion(till):
    note = CreditNote.objects.create(
        store=till["store"],
        fy="26-27",
        value_paise=120000,
        expires_on=timezone.localdate() + timedelta(days=180),
    )
    note.post()
    cursor = till["client"].get(URL).json()["cursor"]

    note.cancel()

    delta = till["client"].get(URL, {"since": cursor}).json()

    assert delta["deleted"]["credit_notes"] == [note.doc_number]
    assert note.docstatus == DocStatus.CANCELLED


def test_a_draft_note_is_not_money_yet_and_stays_home(till):
    CreditNote.objects.create(
        store=till["store"],
        fy="26-27",
        value_paise=120000,
        expires_on=timezone.localdate() + timedelta(days=180),
    )

    assert till["client"].get(URL).json()["credit_notes"] == []


@pytest.mark.parametrize(
    "damaged",
    [
        "yesterday-ish",  # not a timestamp at all
        "2026-02-30T00:00:00Z",  # correctly shaped, and no such day
        "2026-13-01T00:00:00Z",  # correctly shaped, and no such month
        "2026-07-30T25:00:00Z",  # correctly shaped, and no such hour
        "0",
    ],
)
def test_a_damaged_cursor_self_heals_into_a_bootstrap(till, damaged):
    """A GET the till cannot escape from is worse than a re-send.

    The cursor is opaque and ours; a till holding a damaged one has no way to
    repair it, so an unreadable `since` is answered with the full snapshot rather
    than a 400 the queue would retry for ever - or a 500, which is what the three
    correctly-shaped-and-impossible cases here used to give: Django's
    `parse_datetime` answers `None` for the first and *raises* for those.
    """
    response = till["client"].get(URL, {"since": damaged})

    assert response.status_code == 200
    body = response.json()
    assert body["full"] is True
    assert [row["barcode"] for row in body["items"]] == ["8901000000011"]


def test_a_piece_nobody_has_priced_reaches_the_till_as_no_price(till):
    """`null`, never nought - a zero here is a garment billed at ₹0.

    A PT that quotes no MRP registers the SKU with none, deliberately, so an
    unpriced piece really does reach a shelf. The till prices the scan from this
    field and the accept pipeline writes what the till sends straight onto the
    bill, so a nought would post no revenue and no tax against a shirt that walked
    out of the shop.

    The second piece is the fallback: a lot that never carried its own MRP takes the
    SKU's. (A *nought* on the cohort is not asserted because the database will not
    hold one - `ck_cohort_unit_cost_le_mrp` would have to be satisfied by a nought
    cost, and Rule 5 forbids a posting at nought value. `_ticket_price` treats it as
    "no price" anyway, so a future writer cannot make a stored nought shadow a good
    price on the SKU.)
    """
    stock_in(till["store"], 1, barcode="8901000000033")
    Sku.objects.filter(barcode="8901000000033").update(mrp_paise=None)
    Cohort.objects.filter(barcode="8901000000033").update(mrp_paise=None)
    stock_in(till["store"], 1, barcode="8901000000044")
    Cohort.objects.filter(barcode="8901000000044").update(mrp_paise=None)

    items = {row["barcode"]: row["mrp_paise"] for row in till["client"].get(URL).json()["items"]}

    assert items["8901000000033"] is None
    assert items["8901000000044"] == MRP_PAISE


def test_the_cursor_laps_backwards_so_a_late_commit_cannot_be_missed(till):
    """The returned cursor is behind the clock on purpose.

    `updated_at` is stamped when a transaction starts writing, not when it
    commits, so a cursor set to "now" can step over a row that was already
    stamped and had not landed yet. The till upserts by key, so re-sending a row
    costs nothing and missing one costs a wrong price at a counter.
    """
    before = timezone.now()

    cursor = parse_datetime(till["client"].get(URL).json()["cursor"])

    assert cursor is not None
    assert cursor < before


def _cursor_now() -> str:
    """A cursor meaning "this instant".

    The endpoint's own cursor deliberately sits a minute behind the clock (see the
    test above), which re-sends everything a fixture has just written. Tests about
    the delta *predicate* rather than about that lap ask from now instead.
    """
    return timezone.now().isoformat().replace("+00:00", "Z")


def _three_days_later(monkeypatch: pytest.MonkeyPatch) -> None:
    """Move the whole system's clock on three days.

    A note dies because a date passed, and nothing else in this system can make a
    date pass. Patching `django.utils.timezone.now` is safe on a read path: the
    endpoint under test writes nothing, so no `auto_now` column is stamped from
    the moved clock.
    """
    later = timezone.now() + timedelta(days=3)
    monkeypatch.setattr("django.utils.timezone.now", lambda: later)


def _spend(note: CreditNote, till: dict[str, Any], amount: int, *, till_seq: int = 201) -> None:
    """Redeem `amount` off `note` through a bill, the way the counter does.

    Through the accept pipeline rather than by INSERTing a redemption row: the
    note's balance is only true if it is the sum of real redemptions, and a
    fixture that wrote one straight would be testing itself.
    """
    payload = bill_payload(
        till["store"],
        till["salesman"],
        till_seq=till_seq,
        tenders=[
            {"mode": "credit_note", "amount_paise": amount, "credit_note": note.doc_number},
            {"mode": "cash", "amount_paise": MRP_PAISE - amount},
        ],
    )
    response = till["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()
