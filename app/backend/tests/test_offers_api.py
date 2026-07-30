"""The rulebook end to end: authored at head office, priced at the counter.

Three things are being held down here, and only the first is about HTTP.

  1. **A live rule is never edited in place.** The till has cached it and bills
     have printed under it, so a change ends it and starts another.
  2. **The rules reach the till**, dates and all, and a rule that stops running
     is reported as withdrawn rather than left on the device for ever.
  3. **The cap now credits the rulebook** - and only the server's reading of it.
     This is the hole `_rulebook_saving` was written around, and closing it is
     most of what #183 is worth on the money side.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _sell import (
    MRP_PAISE,
    bill_payload,
    build_brand,
    build_cashier,
    build_salesman,
    build_store,
    client_for,
    stock_in,
)
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from accounts.sections import CAP_MANAGE, CAP_VIEW
from masters.models import Brand, Sku
from offers.models import Offer
from sell.models import ContinuityFlag, SaleLine

OFFERS_URL = "/api/offers/"
DATASET_URL = "/api/sell/dataset"
SALES_URL = "/api/sell/sales"
BILL_DAY = date(2026, 7, 30)


# --- fixtures --------------------------------------------------------------


def _ho(capability: str = CAP_MANAGE) -> APIClient:
    """Head office: `offers_price` at the rung being tested, no store boundary."""
    role = make_role(f"ho_offers_{capability}", "HO offers")
    role.section_access = {"offers_price": {"capability": capability}}
    role.save(update_fields=["section_access"])
    user = User.objects.create_user(
        username=f"ho_{uuid.uuid4().hex[:8]}",
        password=TEST_PASSWORD,
        role=role,
        scope_type=ScopeType.ALL,
    )
    return client_for(user)


def _rule_body(store_code: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Mufti flat 30",
        "brand": "mufti",
        "layer": "brand",
        "trigger_type": "none",
        "reward_type": "pct_off",
        "reward_config": {"percent": "30.00"},
        "store_scope": {"kind": "specific", "stores": [store_code]},
        "starts_on": "2026-07-01",
    }
    body.update(overrides)
    return body


def _live_rule(store_code: str, **kwargs: object) -> Offer:
    """A rule already through its authoring gate, straight into the table."""
    brand, _ = Brand.objects.get_or_create(code="mufti", defaults={"name": "MUFTI"})
    approver = User.objects.create_user(
        username=f"approver_{uuid.uuid4().hex[:6]}", password=TEST_PASSWORD
    )
    fields: dict[str, object] = {
        "name": "Mufti flat 30",
        "brand": brand,
        "layer": Offer.Layer.BRAND,
        "trigger_type": Offer.Trigger.NONE,
        "reward_type": Offer.Reward.PCT_OFF,
        "reward_config": {"percent": "30.00"},
        "store_scope": {"kind": "specific", "stores": [store_code]},
        "starts_on": date(2026, 7, 1),
        "status": Offer.Status.LIVE,
        "approved_by": approver,
    }
    fields.update(kwargs)
    return Offer.objects.create(**fields)


@pytest.fixture
def counter(db):
    # `db` rather than a module-level `django_db` mark, matching every other sell
    # suite: the transaction-mode tests elsewhere in the run tear their fixtures
    # down differently, and mixing the two styles in one session confuses
    # pytest's finaliser stack.
    store = build_store()
    build_brand()  # the rules below are MUFTI's, and a rule names a real brand
    cashier = build_cashier(store)
    return {
        "store": store,
        "cashier": cashier,
        "client": client_for(cashier),
        "salesman": build_salesman(store),
    }


# --- authoring -------------------------------------------------------------


def test_a_new_offer_starts_as_a_draft_that_nobody_has_stacked(counter):
    """The two shipped defaults, both of them the safe end of their dial."""
    response = _ho().post(OFFERS_URL, _rule_body(counter["store"].code), format="json")

    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "draft"
    assert response.json()["combinable"] is False


def test_reading_the_rulebook_does_not_let_you_write_it(counter):
    viewer = _ho(CAP_VIEW)
    assert viewer.get(OFFERS_URL).status_code == 200
    refused = viewer.post(OFFERS_URL, _rule_body(counter["store"].code), format="json")
    assert refused.status_code == 403


def test_a_live_rule_is_ended_and_replaced_rather_than_edited(counter):
    """The counter has this rule cached and has printed bills under it.

    Editing it in place would rewrite the terms of a sale that has already
    happened, which is the one thing no document in this system permits.
    """
    offer = _live_rule(counter["store"].code)
    body = _rule_body(counter["store"].code, reward_config={"percent": "50.00"})

    response = _ho().put(f"{OFFERS_URL}{offer.id}", body, format="json")

    assert response.status_code == 201, response.json()
    assert response.json()["replaced_offer_id"] == offer.id
    assert response.json()["status"] == "draft"
    offer.refresh_from_db()
    assert offer.status == Offer.Status.ENDED
    assert offer.reward_config == {"percent": "30.00"}  # untouched, as printed


def test_a_live_rule_can_still_simply_be_stopped(counter):
    offer = _live_rule(counter["store"].code)

    response = _ho().put(f"{OFFERS_URL}{offer.id}", {"status": "ended"}, format="json")

    assert response.status_code == 200, response.json()
    offer.refresh_from_db()
    assert offer.status == Offer.Status.ENDED
    assert offer.replaced_by.count() == 0


def test_an_offer_cannot_go_live_without_somebody_having_approved_it(counter):
    """D5 Q9 gate 1: a named approver before go-live, checked twice.

    Once here, where the message can say so, and once by the table's own CHECK -
    because a rulebook that could go live unapproved through some other path is
    not gated at all.
    """
    created = _ho().post(OFFERS_URL, _rule_body(counter["store"].code), format="json")
    offer_id = created.json()["id"]

    refused = _ho().put(f"{OFFERS_URL}{offer_id}", {"status": "live"}, format="json")

    assert refused.status_code == 400
    assert refused.json()["code"] == "VALIDATION"


def test_a_storewide_rule_that_could_never_apply_is_refused_at_authoring(counter):
    """An add-on works on an already-reduced price, so it can only take a further
    percentage or amount off. A "buy 2 get 1" here would save nothing at all, and
    a rule that silently does nothing is worse than one that is refused."""
    body = _rule_body(
        counter["store"].code,
        layer="storewide",
        brand=None,
        trigger_type="group",
        trigger_config={"buy": 2, "get": 1},
        reward_type="item_free",
    )

    response = _ho().post(OFFERS_URL, body, format="json")

    assert response.status_code == 400
    assert "add-on" in response.json()["error"]


def test_a_brand_rule_without_its_brand_is_refused(counter):
    body = _rule_body(counter["store"].code, brand=None)

    response = _ho().post(OFFERS_URL, body, format="json")

    assert response.status_code == 400
    assert "every brand" in response.json()["error"]


def test_all_stores_is_resolved_to_a_list_the_day_it_is_written(counter):
    """D5 Q4. A wildcard evaluated at billing time would enrol a shop that opened
    after the offer was costed; the list is the decision."""
    build_store("SEL-JSL", state="20")

    response = _ho().post(
        OFFERS_URL, _rule_body(counter["store"].code, store_scope={"kind": "all"}), format="json"
    )

    assert response.status_code == 201
    assert sorted(response.json()["stores"]) == ["SEL-DEO", "SEL-JSL"]

    later = build_store("SEL-NEW", state="10")
    offer = Offer.objects.get(pk=response.json()["id"])
    assert later.code not in offer.store_scope["stores"]


def test_a_store_sees_its_own_rules_and_not_another_stores(counter):
    _live_rule(counter["store"].code, name="Ours")
    _live_rule("SEL-JSL", name="Theirs")

    rows = counter["client"].get(OFFERS_URL).json()

    assert [row["name"] for row in rows] == ["Ours"]


# --- the rules reaching the counter ----------------------------------------


def test_the_dataset_carries_the_rules_with_their_own_dates(counter):
    """The dates ride inside the data so an offline counter starts and stops an
    offer on its own clock (grill Q3)."""
    _live_rule(counter["store"].code, ends_on=date(2026, 12, 31))

    offers = counter["client"].get(DATASET_URL).json()["offers"]

    assert len(offers) == 1
    assert offers[0]["starts_on"] == "2026-07-01"
    assert offers[0]["ends_on"] == "2026-12-31"
    assert offers[0]["reward_config"] == {"percent": "30.00"}


def test_the_dataset_never_ships_who_pays_for_a_discount(counter):
    """`funder` is margin attribution (D5 Q7). The till is a shop-floor device and
    has no use for it; H2's whole point is that it holds prices, never economics."""
    _live_rule(counter["store"].code, funder=Offer.Funder.KDPS)

    assert "funder" not in counter["client"].get(DATASET_URL).json()["offers"][0]


def test_a_draft_rule_never_reaches_a_counter(counter):
    _live_rule(counter["store"].code, status=Offer.Status.DRAFT, approved_by=None)

    assert counter["client"].get(DATASET_URL).json()["offers"] == []


def test_a_rule_taken_off_this_store_is_reported_as_withdrawn(counter):
    """The delta's hardest case, and the reason it scans the network rather than
    this store: an offer edited off this store drops out of any store-narrowed
    query, so a delta that filtered first could never mention it again and the
    till would honour it for ever."""
    offer = _live_rule(counter["store"].code)
    cursor = counter["client"].get(DATASET_URL).json()["cursor"]
    offer.store_scope = {"kind": "specific", "stores": ["SEL-JSL"]}
    offer.save()

    payload = counter["client"].get(f"{DATASET_URL}?since={cursor}").json()

    assert payload["offers"] == []
    assert payload["deleted"]["offers"] == [offer.id]


def test_a_rule_whose_end_date_passed_is_reported_as_withdrawn(counter):
    """It dies of a date with nothing written to its row, exactly as a credit note
    does - so the delta has to ask, or a till offline over a weekend keeps
    discounting under a promotion that finished on the Saturday."""
    offer = _live_rule(counter["store"].code, ends_on=date.today() - timedelta(days=1))
    since = (date.today() - timedelta(days=3)).isoformat() + "T00:00:00Z"

    payload = counter["client"].get(f"{DATASET_URL}?since={since}").json()

    assert payload["deleted"]["offers"] == [offer.id]


def test_a_bootstrap_reports_nothing_withdrawn(counter):
    _live_rule(counter["store"].code, ends_on=date.today() - timedelta(days=1))

    payload = counter["client"].get(DATASET_URL).json()

    assert payload["full"] is True
    assert payload["offers"] == []
    assert payload["deleted"]["offers"] == []


def test_the_store_dashboard_says_what_is_running_this_morning(counter):
    _live_rule(counter["store"].code)

    live = counter["client"].get("/api/store/dashboard").json()["live"]["offers"]

    assert live == [{"id": Offer.objects.get().id, "brand": "MUFTI", "one_liner": "MUFTI: 30% off"}]


# --- the cap, which is the money half --------------------------------------


def _shelf(store, qty: int = 3) -> None:
    stock_in(store, qty)


def test_the_cap_credits_what_the_rulebook_actually_gave(counter):
    """The hole `_rulebook_saving` was written around, closed.

    ₹1,499 at 30% is ₹449.70 - far past any cashier's own cap - and it goes
    through without a manager, because the rulebook gave it and the *server* is
    the one that says so.
    """
    _live_rule(counter["store"].code)
    _shelf(counter["store"])
    saved = 44970
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=saved)
    payload["lines"][0]["offer_evidence"] = {"layer": "brand", "saved_paise": saved}

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    assert response.json()["flags"] == []
    assert SaleLine.objects.get().override_by is None


def test_the_cap_still_covers_a_discount_the_rulebook_did_not_give(counter):
    """A rule is running, and the counter gave more than it is worth. The excess
    is a cashier's own, and B2 caps it exactly as if there were no rule at all."""
    _live_rule(counter["store"].code)
    _shelf(counter["store"])
    payload = bill_payload(
        counter["store"], counter["salesman"], till_seq=1, disc_paise=44970 + 30000
    )
    payload["lines"][0]["offer_evidence"] = {"layer": "brand", "saved_paise": 44970}

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"


def test_a_piece_the_amm_sheet_never_discounts_takes_no_rule(counter):
    """D5 Q3. The flag lives on the SKU master, not on the bill, and the server
    reads it there - a till that mis-stated it must not be able to discount a
    piece head office says is never discounted."""
    _live_rule(counter["store"].code)
    _shelf(counter["store"])
    Sku.objects.filter(barcode="8901000000011").update(no_discount=True)
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=44970)
    payload["lines"][0]["offer_evidence"] = {"layer": "brand", "saved_paise": 44970}

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 422
    assert response.json()["code"] == "OVERRIDE_REQUIRED"


def test_a_clean_bill_raises_no_offer_flag(counter):
    """The acceptance criterion, stated directly: the advisory recompute agrees
    with the counter on a bill the counter priced correctly."""
    _live_rule(counter["store"].code)
    _shelf(counter["store"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=44970)
    payload["lines"][0]["offer_evidence"] = {"layer": "brand", "saved_paise": 44970}

    counter["client"].post(SALES_URL, payload, format="json")

    assert not ContinuityFlag.objects.filter(kind=ContinuityFlag.Kind.OFFER_MISMATCH).exists()


def test_a_bill_that_missed_a_running_offer_is_flagged_not_refused(counter):
    """A stale till charged full price under a rule head office had published.

    The customer was under-served and the bill is already in their hand, so the
    answer is the store's morning queue, never a refusal.
    """
    _live_rule(counter["store"].code)
    _shelf(counter["store"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201
    assert "offer_mismatch" in response.json()["flags"]
    flag = ContinuityFlag.objects.get(kind=ContinuityFlag.Kind.OFFER_MISMATCH)
    assert flag.details["lines"][0] == {
        "line_no": 1,
        "charged_paise": 0,
        "rulebook_paise": 44970,
        "offer_id": None,
    }


def test_the_rulebook_is_read_as_of_the_day_the_bill_was_printed(counter):
    """A counter bills offline under the rules it holds, and syncs days later.

    Resolving against *today's* rulebook would refuse a bill the store priced
    honestly - `OVERRIDE_REQUIRED` on a printed receipt, with the whole queue
    stopped behind it. An ended rule is still consulted for a bill printed inside
    its dates, because it was running when that bill was printed.
    """
    _live_rule(
        counter["store"].code,
        status=Offer.Status.ENDED,
        ends_on=BILL_DAY,  # stopped the evening this bill was rung up
    )
    _shelf(counter["store"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=44970)

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201, response.json()
    assert response.json()["flags"] == []


def test_the_line_records_which_rule_the_counter_sold_it_under(counter):
    offer = _live_rule(counter["store"].code)
    _shelf(counter["store"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1, disc_paise=44970)
    payload["lines"][0]["offer_id"] = offer.id
    payload["lines"][0]["offer_evidence"] = {"offer_id": offer.id, "saved_paise": 44970}

    counter["client"].post(SALES_URL, payload, format="json")

    assert SaleLine.objects.get().offer_id == offer.id


def test_an_offer_id_naming_no_rule_is_dropped_rather_than_refused(counter):
    """The bill is printed. A bad reference is a finding, not a stopped queue."""
    _shelf(counter["store"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)
    payload["lines"][0]["offer_id"] = 987654

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201
    assert SaleLine.objects.get().offer_id is None


def test_a_bill_priced_under_no_rulebook_at_all_is_still_clean(counter):
    """The commonest bill in the system today: no offers, no discount, no flag."""
    _shelf(counter["store"])
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=1)

    response = counter["client"].post(SALES_URL, payload, format="json")

    assert response.status_code == 201
    assert response.json()["flags"] == []
    assert SaleLine.objects.get().net_paise == MRP_PAISE
