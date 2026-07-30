"""Cross-store availability — "who has this shirt in L?" (#175, D10 §3).

The one read that deliberately steps outside `masters.scoping`, so the suite is
built around the two halves of that decision:

- **it really does cross the boundary** — a store-scoped person sees stock held
  at stores they can see nothing else about, and the top-bar switcher does not
  narrow it away;
- **and it carries nothing it promised not to** — no cost, value, MRP or margin
  field anywhere in the payload, asserted against the registered exception's own
  ``withholds`` list rather than against a hand-written field list that would
  drift away from it.

Plus the ordinary contract: how a term is resolved, what the filters do, where
the cap falls, and who is refused.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from masters.models import Gstin, LegalEntity, Sku, Store
from masters.scope_exceptions import (
    CROSS_STORE_AVAILABILITY,
    REGISTERED_SCOPE_EXCEPTIONS,
)
from stockledger.models import StockOnHand
from stockledger.views import StockAvailabilityView

URL = "/api/stock/availability"


@pytest.fixture()
def rig(db):
    """Three locations holding overlapping stock, and the people who ask about it.

    ``asker`` is scoped to one store and nothing else — the whole point of the
    endpoint is that they can still see the other two locations' quantities.
    """
    entity = LegalEntity.objects.create(code="av-ent", name="Availability Co", pan="AAACA1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACA1234C1ZS", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    store_a = Store.objects.create(code="AV-A", name="Availability Store A", gstin=gstin)
    store_b = Store.objects.create(code="AV-B", name="Availability Store B", gstin=gstin)
    warehouse = Store.objects.create(
        code="AV-WH", name="Availability Warehouse", gstin=gstin, store_type="warehouse"
    )
    shut = Store.objects.create(
        code="AV-SHUT", name="Availability Closed Store", gstin=gstin, is_active=False
    )

    def _user(username, role_code, scope=ScopeType.ALL, stores=()):
        user = User.objects.create_user(
            username=username,
            password=TEST_PASSWORD,
            role=make_role(role_code),
            entity=entity,
            scope_type=scope,
        )
        for store in stores:
            user.stores.add(store)
        return user

    asker = _user("av_asker", "store_manager", scope=ScopeType.STORE, stores=[store_a])
    ops = _user("av_ops", "ho_ops")
    # An unknown role code resolves to no access at all (fail-closed), which is
    # exactly the "holds nothing on Stock" person this endpoint must refuse.
    outsider = _user("av_outsider", "zz_no_sections")

    def _stock(store, barcode, design, size, qty, brand="AvBrand", item="Chinos"):
        Sku.objects.get_or_create(
            barcode=barcode,
            defaults=dict(
                design=design,
                color="Blue",
                size=size,
                brand=brand,
                item=item,
                hsn="6203",
                mrp_paise=249900,
            ),
        )
        StockOnHand.objects.create(
            store=store,
            gstin=gstin,
            sku_code=barcode,
            design=design,
            color="Blue",
            size=size,
            brand=brand,
            season="SS26",
            item=item,
            hsn="6203",
            net_qty=qty,
            net_value_paise=qty * 120000,
        )

    # One style, three sizes, spread across the network.
    _stock(store_a, "AV-CH-M", "CH8801", "M", 4)
    _stock(store_b, "AV-CH-L", "CH8801", "L", 3)
    _stock(warehouse, "AV-CH-L-WH", "CH8801", "L", 7)
    _stock(shut, "AV-CH-L-SHUT", "CH8801", "L", 99)
    # A second style, another brand, to prove the filters bite.
    _stock(warehouse, "AV-SH-M", "SH2200", "M", 5, brand="OtherBrand", item="Shirt")

    return {
        "store_a": store_a,
        "store_b": store_b,
        "warehouse": warehouse,
        "shut": shut,
        "asker": asker,
        "ops": ops,
        "outsider": outsider,
    }


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _get(user, **params):
    return _client(user).get(URL, params)


def _stores_for(payload, design="CH8801", size="L"):
    entry = next(r for r in payload["results"] if r["design"] == design)
    sizes = next(s for s in entry["sizes"] if s["size"] == size)
    return {s["store"]: s["qty"] for s in sizes["stores"]}


# ---------------------------------------------------------------------------
# The exception itself
# ---------------------------------------------------------------------------


def test_the_cross_store_read_is_a_registered_exception_with_a_reason():
    """Reaching past `masters.scoping` is a recorded decision, not a diff.

    The whole set is asserted, both directions: a second endpoint that quietly
    goes cross-store has to come through this registry and write down why, and a
    stale entry for a read that no longer exists has to be removed.
    """
    assert set(REGISTERED_SCOPE_EXCEPTIONS) == {"stockledger.cross_store_availability"}
    for name, entry in REGISTERED_SCOPE_EXCEPTIONS.items():
        assert entry.reason.strip(), f"{name} has no written reason"
        assert entry.withholds, f"{name} does not say what it withholds"


@pytest.mark.django_db
def test_a_store_scoped_person_sees_every_other_locations_quantity(rig):
    """The boundary is suspended on purpose — that is the feature.

    The asker is scoped to AV-A alone. Without the exception this answer would
    be AV-A's four pieces in M and silence about the L the customer wants.
    """
    resp = _get(rig["asker"], q="CH8801")

    assert resp.status_code == 200, resp.data
    assert _stores_for(resp.data) == {"AV-B": 3, "AV-WH": 7}
    assert resp.data["truncated"] is False


@pytest.mark.django_db
def test_no_cost_or_value_field_reaches_the_wire(rig):
    """Quantities only, by construction — the narrow half of the exception.

    Asserted against the registry's own ``withholds`` rather than a list written
    out here: the guarantee and its test cannot then drift apart, and widening
    one is visibly widening the other.
    """
    resp = _get(rig["asker"], q="CH8801")

    assert CROSS_STORE_AVAILABILITY.leaked_fields(resp.data) == []


@pytest.mark.django_db
def test_a_result_names_the_piece_well_enough_to_ask_for_it(rig):
    """ "Request this" has to build a stock-request line, and a line needs a
    barcode. So the innermost entry is one SKU at one store — its colour and its
    tag included — rather than a size's colours summed into a number nobody can
    act on."""
    resp = _get(rig["asker"], q="CH8801")

    size_l = next(s for s in resp.data["results"][0]["sizes"] if s["size"] == "L")
    at_warehouse = next(s for s in size_l["stores"] if s["store"] == "AV-WH")
    assert at_warehouse["sku_code"] == "AV-CH-L-WH"
    assert at_warehouse["color"] == "Blue"
    assert at_warehouse["store_name"] == "Availability Warehouse"
    assert at_warehouse["qty"] == 7


@pytest.mark.django_db
def test_two_colours_of_one_size_stay_two_askable_rows(rig):
    """A customer wants the navy one. Folding the colours of a size together
    would read tidier and leave the counter unable to say which piece."""
    StockOnHand.objects.create(
        store=rig["warehouse"],
        sku_code="AV-CH-L-WH-RED",
        design="CH8801",
        color="Red",
        size="L",
        brand="AvBrand",
        season="SS26",
        item="Chinos",
        hsn="6203",
        net_qty=2,
        net_value_paise=240000,
    )
    Sku.objects.create(
        barcode="AV-CH-L-WH-RED",
        design="CH8801",
        color="Red",
        size="L",
        brand="AvBrand",
        item="Chinos",
        hsn="6203",
        mrp_paise=249900,
    )

    resp = _get(rig["asker"], q="CH8801")

    size_l = next(s for s in resp.data["results"][0]["sizes"] if s["size"] == "L")
    at_warehouse = [s for s in size_l["stores"] if s["store"] == "AV-WH"]
    assert {(s["color"], s["qty"]) for s in at_warehouse} == {("Blue", 7), ("Red", 2)}


@pytest.mark.django_db
def test_the_switcher_cannot_narrow_the_answer_away(rig):
    """A unit picked in the top bar filters what you are looking at; it must not
    filter this. An HO person standing in AV-A still needs the network's answer,
    or the search silently becomes the on-hand screen."""
    resp = _client(rig["ops"]).get(URL, {"q": "CH8801"}, HTTP_X_KDPS_UNIT="AV-A")

    assert resp.status_code == 200, resp.data
    assert _stores_for(resp.data) == {"AV-B": 3, "AV-WH": 7}


# ---------------------------------------------------------------------------
# Resolving the term
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "term,expected_designs",
    [
        ("AV-CH-L", ["CH8801"]),  # a scanned tag means that tag
        ("CH88", ["CH8801"]),  # design read left to right off the label
        ("Chinos", ["CH8801"]),  # only knows it by name
    ],
)
def test_three_ways_in(rig, term, expected_designs):
    resp = _get(rig["asker"], q=term)

    assert resp.status_code == 200, resp.data
    assert [r["design"] for r in resp.data["results"]] == expected_designs


@pytest.mark.django_db
def test_a_scanned_tag_answers_with_that_tag_alone(rig):
    """The barcode is a scan-alias and stock is a count under it: a whole
    barcode is not a substring question."""
    resp = _get(rig["asker"], q="AV-CH-M")

    sizes = resp.data["results"][0]["sizes"]
    assert [s["size"] for s in sizes] == ["M"]
    assert [s["store"] for s in sizes[0]["stores"]] == ["AV-A"]


@pytest.mark.django_db
@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "CH"}, {"q": "  a  "}])
def test_a_term_under_three_characters_is_refused(rig, params):
    resp = _get(rig["asker"], **params)

    assert resp.status_code == 400
    assert resp.data["code"] == "VALIDATION"


@pytest.mark.django_db
def test_a_term_that_matches_nothing_answers_empty_not_everything(rig):
    resp = _get(rig["asker"], q="ZZZZ-NOTHING")

    assert resp.status_code == 200, resp.data
    assert resp.data == {"results": [], "truncated": False}


# ---------------------------------------------------------------------------
# Filters, closed stores, the cap
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_brand_and_size_narrow_within_the_match(rig):
    both = _get(rig["asker"], q="CH8801")
    assert {s["size"] for s in both.data["results"][0]["sizes"]} == {"M", "L"}

    only_l = _get(rig["asker"], q="CH8801", size="l")
    assert [s["size"] for s in only_l.data["results"][0]["sizes"]] == ["L"]

    wrong_brand = _get(rig["asker"], q="CH8801", brand="OtherBrand")
    assert wrong_brand.data["results"] == []


@pytest.mark.django_db
def test_a_closed_stores_stock_is_never_offered(rig):
    """AV-SHUT holds 99 pieces of exactly what is being hunted. Nobody can be
    sent there, so quoting it would send a customer away for nothing."""
    resp = _get(rig["asker"], q="CH8801")

    assert "AV-SHUT" not in _stores_for(resp.data)


@pytest.mark.django_db
def test_the_cap_falls_on_designs_and_says_so(rig, monkeypatch):
    """A design with twelve sizes across six stores is still *one* answer to the
    person reading it, so the cap counts designs — and when it bites, the answer
    says it was cut rather than reading as the whole truth."""
    Sku.objects.filter(barcode="AV-SH-M").update(item="Chinos shirt")
    StockOnHand.objects.filter(sku_code="AV-SH-M").update(item="Chinos shirt")

    full = _get(rig["asker"], q="Chinos")
    assert len(full.data["results"]) == 2
    assert full.data["truncated"] is False

    monkeypatch.setattr(StockAvailabilityView, "MAX_DESIGNS", 1)
    capped = _get(rig["asker"], q="Chinos")
    assert len(capped.data["results"]) == 1
    assert capped.data["truncated"] is True


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_someone_without_stock_view_is_refused(rig):
    resp = _get(rig["outsider"], q="CH8801")

    assert resp.status_code == 403


def test_an_anonymous_caller_is_refused(db):
    assert APIClient().get(URL, {"q": "CH8801"}).status_code in (401, 403)
