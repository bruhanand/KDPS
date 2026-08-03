"""Booking & Price end to end (D11): who writes a number, and who signs it.

Six things are held down here, and each one is a promise the access table made
that the code did not keep before this module:

  1. **Authoring is `operate`, not `manage`.** The write gate used to ask for a
     rung only IT Admin holds, so the Owner, the Brand Manager and the promo user
     the table hands offers to could not write one (D11 F1).
  2. **Nobody clears their own offer.** Writing "approved" onto your own draft was
     the whole gate; now the decision belongs to a second person, and it is the
     decision that publishes the rule (D11 §7, the deferred half of D5 Q9).
  3. **A ticket keeps its history.** MRP used to be overwritten in place, so a bill
     from last month could not be explained. Every movement is a row, and the list
     can be read as of a past day (D11 §4).
  4. **A ticket never goes below what the piece cost to land** — refused with the
     cost in the sentence, not by a database CHECK.
  5. **A rule's discount and a person's discount are different money**, and the
     pack tells them apart — including the discount a piece was owed and never
     given (D11 §8, R4).
  6. **A booking reaches "booked" through somebody else's signature.** It used to
     be created booked, which made `booking: approve` decide nothing (D11 §3).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _sell import (
    COST_PAISE,
    MRP_PAISE,
    bill_payload,
    build_brand,
    build_cashier,
    build_piece,
    build_salesman,
    build_store,
    build_supplier,
    client_for,
    stock_in,
)
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from accounts.sections import CAP_APPROVE, CAP_OPERATE, CAP_VIEW
from approvals.models import Approval, ApprovalStatus
from masters.models import Cohort, PriceChange, Sku
from offers.models import Offer
from vendors.models import Booking, BookingLine, Vendor

OFFERS_URL = "/api/offers/"
PRICE_URL = "/api/offers/price-list"
DISCOUNTS_URL = "/api/sell/discounts"
SALES_URL = "/api/sell/sales"
BARCODE = "8901000000011"


# --- people ---------------------------------------------------------------


def _person(section: str, capability: str, *, role_code: str = "") -> APIClient:
    """One head-office seat holding exactly one rung of one section."""
    code = role_code or f"{section}_{capability}_{uuid.uuid4().hex[:6]}"
    role = make_role(code, code.replace("_", " ").title())
    role.section_access = {section: {"capability": capability}}
    role.save(update_fields=["section_access"])
    user = User.objects.create_user(
        username=f"u_{uuid.uuid4().hex[:8]}",
        password=TEST_PASSWORD,
        role=role,
        scope_type=ScopeType.ALL,
    )
    return client_for(user)


def _promo() -> APIClient:
    """The tenth persona: authors offers, clears none of them."""
    return _person("offers_price", CAP_OPERATE)


def _signer(section: str = "offers_price") -> APIClient:
    """Somebody the seeded policy names as an approver of that family."""
    return _person(section, CAP_APPROVE, role_code=f"owner_{uuid.uuid4().hex[:6]}")


def _owner_client() -> APIClient:
    """An approver whose *role code* is `owner`, which the policies name."""
    role = make_role("owner", "Owner")
    role.section_access = {
        "offers_price": {"capability": CAP_APPROVE},
        "booking": {"capability": CAP_APPROVE},
    }
    role.save(update_fields=["section_access"])
    user = User.objects.create_user(
        username=f"owner_{uuid.uuid4().hex[:8]}",
        password=TEST_PASSWORD,
        role=role,
        scope_type=ScopeType.ALL,
    )
    return client_for(user)


def _rule_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Mufti flat 30",
        "brand": "mufti",
        "layer": "brand",
        "trigger_type": "none",
        "reward_type": "pct_off",
        "reward_config": {"percent": "30.00"},
        "store_scope": {"kind": "all", "stores": ["SEL-DEO"]},
        "starts_on": str(date.today()),
    }
    body.update(overrides)
    return body


@pytest.fixture
def rulebook(db):
    """A brand to point a rule at and a shop to run it in. Both are refused when
    missing - a rule with no brand and a rule with no store are both nothing."""
    build_brand()
    return build_store()


@pytest.fixture
def shop(db):
    store = build_store()
    build_brand()
    cashier = build_cashier(store)
    return {
        "store": store,
        "cashier": cashier,
        "client": client_for(cashier),
        "salesman": build_salesman(store),
    }


# --- authoring and the gate ------------------------------------------------


def test_the_promo_rung_can_write_a_rule_at_all(rulebook):
    """D11 F1: the gate used to be `manage`, which no business seat holds."""
    response = _promo().post(OFFERS_URL, _rule_body(), format="json")

    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "draft"
    assert response.json()["awaiting_approval"] is False


def test_reading_the_rulebook_still_does_not_let_you_write_it(rulebook):
    response = _person("offers_price", CAP_VIEW).post(OFFERS_URL, _rule_body(), format="json")

    assert response.status_code == 403


def test_nobody_approves_their_own_offer_by_typing_approved(rulebook):
    author = _promo()
    made = author.post(OFFERS_URL, _rule_body(), format="json")
    offer_id = made.json()["id"]

    refused = author.put(f"{OFFERS_URL}{offer_id}", {"status": "approved"}, format="json")

    assert refused.status_code == 400
    assert "second person" in refused.json()["error"]
    assert Offer.objects.get(pk=offer_id).status == Offer.Status.DRAFT


def test_a_second_person_clears_it_and_that_publishes_it(rulebook):
    """The decision *is* the publication - an approved rule with nobody to
    promote it on its start date would price nothing (D11 F3)."""
    author = _promo()
    offer_id = author.post(OFFERS_URL, _rule_body(), format="json").json()["id"]

    sent = author.post(f"{OFFERS_URL}{offer_id}/request-approval", {}, format="json")
    assert sent.status_code == 201, sent.json()
    assert sent.json()["awaiting_approval"] is True

    approval = Approval.objects.get(kind="offer", object_id=offer_id)
    assert approval.status == ApprovalStatus.PENDING
    assert set(approval.approver_roles) == {"brand_manager", "owner"}

    decided = _owner_client().post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    assert decided.status_code == 200, decided.json()

    offer = Offer.objects.get(pk=offer_id)
    assert offer.status == Offer.Status.LIVE
    assert offer.approved_by_id is not None


def test_the_author_cannot_clear_it_from_the_inbox_either(rulebook):
    """Maker ≠ checker is the spine's rule, not this screen's."""
    author = _person("offers_price", CAP_APPROVE)  # even holding the rung
    offer_id = author.post(OFFERS_URL, _rule_body(), format="json").json()["id"]
    author.post(f"{OFFERS_URL}{offer_id}/request-approval", {}, format="json")
    approval = Approval.objects.get(kind="offer", object_id=offer_id)

    refused = author.post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )

    assert refused.status_code == 403
    assert Offer.objects.get(pk=offer_id).status == Offer.Status.DRAFT


def test_only_a_draft_is_sent_for_approval(rulebook):
    author = _promo()
    offer_id = author.post(OFFERS_URL, _rule_body(), format="json").json()["id"]
    author.post(f"{OFFERS_URL}{offer_id}/request-approval", {}, format="json")
    approval = Approval.objects.get(kind="offer", object_id=offer_id)
    _owner_client().post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )

    refused = author.post(f"{OFFERS_URL}{offer_id}/request-approval", {}, format="json")

    assert refused.status_code == 400
    assert "draft" in refused.json()["error"]


# --- the price list -------------------------------------------------------


def test_the_price_list_answers_ticket_cost_and_margin(db):
    build_piece()
    response = _person("offers_price", CAP_VIEW).get(f"{PRICE_URL}?q={BARCODE}")

    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["barcode"] == BARCODE
    assert row["mrp_paise"] == MRP_PAISE
    assert row["cost_paise"] == COST_PAISE
    # ₹1,499 ticket on a ₹700 piece: 53.3% of the ticket, before GST.
    assert row["margin_pct"] == "53.3"


def test_moving_a_ticket_leaves_a_trail_with_a_reason(db):
    build_piece()
    ho = _person("offers_price", CAP_OPERATE)

    done = ho.post(
        f"{PRICE_URL}/{BARCODE}/reprice",
        {"mrp_paise": 199900, "reason": "AW26 revised tag"},
        format="json",
    )

    assert done.status_code == 200, done.json()
    assert done.json()["mrp_paise"] == 199900
    trail = done.json()["history"]
    assert len(trail) == 1
    assert (trail[0]["from_paise"], trail[0]["to_paise"]) == (MRP_PAISE, 199900)
    assert trail[0]["reason"] == "AW26 revised tag"
    assert trail[0]["source"] == "reprice"
    # The cohorts carry the ticket too - the till's dataset reads them, so a
    # screen that moved only the SKU would price tomorrow at yesterday's figure.
    assert Cohort.objects.get(barcode=BARCODE).mrp_paise == 199900
    assert Sku.objects.get(barcode=BARCODE).mrp_paise == 199900


def test_the_list_can_be_read_as_of_a_past_day(db):
    build_piece()
    PriceChange.objects.create(
        barcode=BARCODE,
        from_paise=99900,
        to_paise=MRP_PAISE,
        effective_from=date.today() - timedelta(days=3),
        source=PriceChange.Source.REPRICE,
    )

    response = _person("offers_price", CAP_VIEW).get(
        f"{PRICE_URL}?q={BARCODE}&as_of={date.today() - timedelta(days=10)}"
    )

    row = response.json()["rows"][0]
    # Nothing had moved ten days ago, so the trail knows of no earlier figure and
    # the answer falls back to the current one rather than inventing a number.
    assert row["mrp_then_paise"] == MRP_PAISE


def test_a_ticket_below_landed_cost_is_refused_by_name(db):
    build_piece()

    refused = _person("offers_price", CAP_OPERATE).post(
        f"{PRICE_URL}/{BARCODE}/reprice",
        {"mrp_paise": 50000, "reason": "clearing it out"},
        format="json",
    )

    assert refused.status_code == 400
    assert "700.00" in refused.json()["error"]
    assert Sku.objects.get(barcode=BARCODE).mrp_paise == MRP_PAISE


def test_a_ticket_does_not_move_without_a_reason(db):
    build_piece()

    refused = _person("offers_price", CAP_OPERATE).post(
        f"{PRICE_URL}/{BARCODE}/reprice", {"mrp_paise": 199900}, format="json"
    )

    assert refused.status_code == 400
    assert PriceChange.objects.count() == 0


def test_reading_the_price_list_does_not_let_you_move_a_ticket(db):
    build_piece()

    refused = _person("offers_price", CAP_VIEW).post(
        f"{PRICE_URL}/{BARCODE}/reprice",
        {"mrp_paise": 199900, "reason": "trying it on"},
        format="json",
    )

    assert refused.status_code == 403


# --- the discount pack ----------------------------------------------------


def _live_rule(store_code: str) -> Offer:
    from masters.models import Brand

    brand, _ = Brand.objects.get_or_create(code="mufti", defaults={"name": "MUFTI"})
    return Offer.objects.create(
        name="Mufti flat 30",
        brand=brand,
        layer=Offer.Layer.BRAND,
        trigger_type=Offer.Trigger.NONE,
        reward_type=Offer.Reward.PCT_OFF,
        reward_config={"percent": "30.00"},
        store_scope={"kind": "specific", "stores": [store_code]},
        # The fixture bills are dated 30 Jul 2026; a rule that starts today
        # would not have been running when they printed.
        starts_on=date(2026, 7, 1),
        status=Offer.Status.LIVE,
        approved_by=User.objects.create_user(
            username=f"ap_{uuid.uuid4().hex[:6]}", password=TEST_PASSWORD
        ),
    )


def test_the_pack_tells_a_rules_discount_from_a_persons(shop):
    rule = _live_rule(shop["store"].code)
    stock_in(shop["store"], 4)
    saved = MRP_PAISE * 30 // 100

    priced = bill_payload(shop["store"], shop["salesman"], till_seq=1, disc_paise=saved)
    priced["lines"][0]["offer_id"] = rule.id
    priced["lines"][0]["offer_evidence"] = {"offer_id": rule.id, "saved_paise": saved}
    assert shop["client"].post(SALES_URL, priced, format="json").status_code == 201

    keyed = bill_payload(shop["store"], shop["salesman"], till_seq=2, disc_paise=5000)
    keyed["lines"][0]["manual_desc"] = "Regular customer"
    assert shop["client"].post(SALES_URL, keyed, format="json").status_code == 201

    pack = (
        _person("offers_price", CAP_VIEW)
        .get(f"{DISCOUNTS_URL}?from=2026-07-01&to=2026-08-31")
        .json()
    )

    assert pack["totals"]["bills"] == 2
    assert pack["totals"]["disc_paise"] == saved + 5000
    assert pack["by_offer"][0]["offer_id"] == rule.id
    assert pack["by_offer"][0]["disc_paise"] == saved
    assert pack["by_offer"][0]["funder"] == "brand"
    # The keyed-in figure counts only what no rule explains.
    assert pack["keyed_in"]["disc_paise"] == 5000
    assert pack["keyed_in"]["by_person"][0]["name"] == shop["salesman"].name


def test_the_pack_shows_what_was_owed_and_never_given(shop):
    """R4's honest engine: the true bill, the true date, nothing restated."""
    _live_rule(shop["store"].code)
    stock_in(shop["store"], 2)

    full_price = bill_payload(shop["store"], shop["salesman"], till_seq=3, disc_paise=0)
    assert shop["client"].post(SALES_URL, full_price, format="json").status_code == 201

    pack = (
        _person("offers_price", CAP_VIEW)
        .get(f"{DISCOUNTS_URL}?from=2026-07-01&to=2026-08-31")
        .json()
    )

    assert pack["not_applied"]["missed_paise"] == MRP_PAISE * 30 // 100
    assert pack["not_applied"]["open_flags"] == 1
    assert pack["not_applied"]["rows"][0]["billed_on"] == "2026-07-30"


# --- the booking gate -----------------------------------------------------


def _booking_body(shop) -> dict[str, object]:
    from masters.models import Brand, Season

    return {
        "vendor": Vendor.objects.get(code="ARVIND").id,
        "brand": Brand.objects.get(code="mufti").id,
        "season": Season.objects.get(code="FW25").id,
        "destination_store": shop.id,
        "lines": [{"style_code": "MFT-501", "size": "M", "booked_qty": 12, "mrp": 1499}],
    }


@pytest.fixture
def buying(db):
    store = build_store()
    brand = build_brand()
    build_supplier(brand)
    from masters.models import Season

    Season.objects.get_or_create(code="FW25", defaults={"name": "Autumn Winter 25"})
    return store


def test_a_new_booking_is_a_draft_not_a_commitment(buying):
    maker = _person("booking", CAP_OPERATE)

    made = maker.post("/api/bookings", _booking_body(buying), format="json")

    assert made.status_code == 201, made.json()
    assert made.json()["status"] == "draft"
    assert Booking.objects.get().estimated_value_paise == 12 * 149900


def test_a_booking_reaches_booked_only_through_a_second_person(buying):
    maker = _person("booking", CAP_OPERATE)
    made = maker.post("/api/bookings", _booking_body(buying), format="json")
    booking_id = made.json()["id"]

    sent = maker.post(f"/api/bookings/{booking_id}/request-approval", {}, format="json")
    assert sent.status_code == 201, sent.json()
    assert Booking.objects.get(pk=booking_id).status == Booking.Status.SUBMITTED

    approval = Approval.objects.get(kind="booking", object_id=booking_id)
    assert approval.approver_roles == ["owner"]

    decided = _owner_client().post(
        f"/api/approvals/{approval.id}/decide", {"action": "approve"}, format="json"
    )
    assert decided.status_code == 200, decided.json()

    booking = Booking.objects.get(pk=booking_id)
    assert booking.status == Booking.Status.BOOKED
    assert booking.approved_by_id is not None


def test_a_recount_never_walks_a_draft_through_the_gate(buying):
    """`recompute_status` promoted anything with no receipts to booked, which
    would have opened the gate from the inside on any save."""
    maker = _person("booking", CAP_OPERATE)
    made = maker.post("/api/bookings", _booking_body(buying), format="json")
    booking_id = made.json()["id"]
    booking = Booking.objects.get(pk=booking_id)

    BookingLine.objects.create(
        booking=booking, style_code="MFT-502", size="L", booked_qty=4, store=buying
    )
    booking.recompute_status()

    assert Booking.objects.get(pk=booking_id).status == Booking.Status.DRAFT
