"""The offer engine against its golden carts, plus the invariants no cart states.

The vector run below is the money test of this slice. Its TypeScript twin
(`app/frontend/src/till/offers.vectors.test.ts`) reads the same files and asserts
the same numbers, so the two engines cannot drift apart without one of the two
suites going red - which is the only way "the same cart always prices the same,
at the counter and at head office" can be a fact rather than an intention.

Nothing here touches the database: the engine has no ORM imports and must keep
none, or it stops being portable to the till at all.
"""

from __future__ import annotations

from datetime import date

import pytest

from offers.resolution import (
    Cart,
    CartLine,
    Rule,
    hundredths,
    percent_of,
    resolve,
)
from offers.vectors import Vector, load_all

DAY = date(2026, 7, 31)


# --- the golden carts ------------------------------------------------------


@pytest.mark.parametrize("vector", load_all(), ids=lambda v: v.name)
def test_golden_vector(vector: Vector) -> None:
    assert vector.run().as_dict() == vector.expected, vector.note


def test_every_named_mechanic_has_a_vector() -> None:
    """The acceptance criteria name seven things; none may quietly go missing.

    A golden suite is only as good as its coverage, and coverage is the easiest
    thing in the world to lose one file at a time. This is the tripwire.
    """
    names = {vector.name for vector in load_all()}
    for wanted in (
        "spend-slabs",
        "qty-slabs-tie-on-priority",
        "b2g1-cheapest-free",
        "gift-earned",
        "gift-declined-falls-back",
        "storewide-and-bank-stack",
        "add-ons-do-not-stack-by-default",
        "no-discount-piece-is-untouchable",
    ):
        assert wanted in names, f"the {wanted} vector has gone missing"


# --- the invariants no single cart can state -------------------------------


def _line(line_no: int, mrp: int, **kw: object) -> CartLine:
    fields: dict[str, object] = {"brand": "MUFTI", "item": "Shirt", "season": "FW25"}
    fields.update(kw)
    return CartLine(line_no=line_no, mrp_paise=mrp, **fields)  # type: ignore[arg-type]


def _rule(rule_id: int, **kw: object) -> Rule:
    fields: dict[str, object] = {
        "name": f"rule {rule_id}",
        "layer": "brand",
        "brand": "MUFTI",
        "starts_on": date(2026, 1, 1),
    }
    fields.update(kw)
    return Rule(id=rule_id, **fields)  # type: ignore[arg-type]


def _cart(*lines: CartLine, day: date = DAY) -> Cart:
    return Cart(lines=lines, day=day)


def test_no_line_is_ever_discounted_below_nought() -> None:
    """Three rules that together want more than the shirt costs.

    Only the first can have it - the brand layer claims the line - but the point
    stands for the stacked ones too: a discount larger than the piece would post
    negative revenue against a garment somebody walked out with.
    """
    cart = _cart(_line(1, 100000))
    rules = [
        _rule(1, reward_type="amt_off", reward_config={"amount_paise": 500000}),
        _rule(2, layer="storewide", brand="", combinable=True, reward_config={"percent": "90.00"}),
        _rule(3, layer="bank", brand="", combinable=True, reward_config={"percent": "90.00"}),
    ]
    outcome = resolve(cart, rules).by_line()[1]
    assert outcome.discount_paise == 100000


def test_the_same_cart_prices_the_same_however_the_rulebook_is_ordered() -> None:
    """Determinism, stated directly.

    The dataset arrives in whatever order the delta happened to produce, and the
    server reads its rulebook in primary-key order. If those two orderings could
    price a cart differently, every bill would be a coin toss between the
    receipt and the books.
    """
    cart = _cart(_line(1, 199900), _line(2, 149900), _line(3, 249900))
    rules = [
        _rule(1, reward_config={"percent": "20.00"}),
        _rule(
            2, trigger_type="group", reward_type="item_free", trigger_config={"buy": 2, "get": 1}
        ),
        _rule(3, item_scope={"categories": ["Shirt"]}, reward_config={"percent": "20.00"}),
        _rule(4, layer="storewide", brand="", combinable=True, reward_config={"percent": "5.00"}),
    ]
    first = resolve(cart, rules).as_dict()
    for rotation in range(1, len(rules)):
        shuffled = rules[rotation:] + rules[:rotation]
        assert resolve(cart, shuffled).as_dict() == first


def test_a_rule_never_reaches_outside_its_own_brand() -> None:
    cart = _cart(_line(1, 100000, brand="MUFTI"), _line(2, 100000, brand="SPYKAR"))
    outcomes = resolve(cart, [_rule(1, reward_config={"percent": "50.00"})]).by_line()
    assert outcomes[1].discount_paise == 50000
    assert outcomes[2].discount_paise == 0
    assert outcomes[2].evidence == {}


def test_a_brand_is_matched_however_it_is_spelled() -> None:
    """`Sku.brand` is free text off a price tag; `Brand.name` is what HO typed.

    A rule that matched only one spelling would under-discount a bill in a way
    nobody at the counter could see or explain.
    """
    cart = _cart(_line(1, 100000, brand="U.S. POLO ASSN."))
    rules = [_rule(1, brand="US Polo Assn", reward_config={"percent": "10.00"})]
    assert resolve(cart, rules).by_line()[1].discount_paise == 10000


def test_at_most_one_brand_offer_reaches_a_line() -> None:
    cart = _cart(_line(1, 100000))
    rules = [
        _rule(1, reward_config={"percent": "50.00"}),
        _rule(2, reward_config={"percent": "40.00"}),
        _rule(3, reward_config={"percent": "30.00"}),
    ]
    outcome = resolve(cart, rules).by_line()[1]
    assert outcome.discount_paise == 50000
    assert outcome.offer_id == 1
    assert [beat["offer_id"] for beat in outcome.evidence["beat"]] == [2, 3]


def test_an_unpriced_line_takes_no_offer() -> None:
    """A piece the books have no MRP for is not a free piece (contract, step 3)."""
    cart = _cart(_line(1, 0))
    assert resolve(cart, [_rule(1, reward_config={"percent": "50.00"})]).by_line()[1].evidence == {}


def test_a_ladder_that_was_never_reached_is_no_offer_at_all() -> None:
    cart = _cart(_line(1, 100000))
    rules = [
        _rule(
            1,
            trigger_type="spend",
            reward_type="amt_off",
            trigger_config={"slabs": [{"min_paise": 699900, "amount_paise": 60000}]},
        )
    ]
    assert resolve(cart, rules).total_discount_paise == 0


def test_a_lump_sum_is_shared_out_to_the_last_paisa() -> None:
    """Three lines and a prime-ish lump: the parts must sum to the whole."""
    cart = _cart(_line(1, 33333), _line(2, 33333), _line(3, 33334))
    rules = [_rule(1, reward_type="amt_off", reward_config={"amount_paise": 10_000})]
    assert resolve(cart, rules).total_discount_paise == 10_000


def test_percentages_round_half_up_and_never_touch_a_float() -> None:
    assert percent_of(100, 5000) == 50
    assert percent_of(101, 5000) == 51  # 50.5 goes up, not to the even number
    assert percent_of(103, 5000) == 52  # 51.5 goes up too - banker's would say 52 here by luck
    assert percent_of(105, 5000) == 53  # ...and 52.5 here, where banker's would say 52
    assert percent_of(0, 5000) == 0
    assert percent_of(1000, 0) == 0


def test_a_percentage_string_never_becomes_a_float() -> None:
    assert hundredths("7.50") == 750
    assert hundredths("30") == 3000
    assert hundredths("0.05") == 5
    assert hundredths("") == 0
    with pytest.raises(ValueError):
        hundredths("half")


def test_evidence_names_the_layer_that_won_and_what_stacked_on_it() -> None:
    cart = _cart(_line(1, 100000))
    rules = [
        _rule(1, reward_config={"percent": "50.00"}),
        _rule(9, layer="storewide", brand="", combinable=True, reward_config={"percent": "10.00"}),
    ]
    evidence = resolve(cart, rules).by_line()[1].evidence
    assert evidence["offer_id"] == 1
    assert evidence["layer"] == "brand"
    assert evidence["saved_paise"] == 55000
    assert evidence["stack"] == [
        {"offer_id": 9, "offer_name": "rule 9", "layer": "storewide", "saved_paise": 5000}
    ]


def test_an_add_on_can_reach_a_line_no_brand_offer_wanted() -> None:
    """Storewide is storewide: it does not need a brand offer to sit on top of."""
    cart = _cart(_line(1, 100000, brand="SPYKAR"))
    rules = [
        _rule(9, layer="storewide", brand="", combinable=True, reward_config={"percent": "10.00"})
    ]
    outcome = resolve(cart, rules).by_line()[1]
    assert outcome.discount_paise == 10000
    # The FK on the sale line is the *brand* winner, and there wasn't one.
    assert outcome.offer_id is None
    assert outcome.evidence["stack"][0]["offer_id"] == 9


def test_an_add_on_that_cannot_work_on_a_reduced_price_makes_no_proposal() -> None:
    """A "buy 2 get 1" on the storewide layer is a rulebook mistake, not a discount.

    It is refused rather than approximated: the alternative is giving a piece
    away twice, once by the brand rule and once by an add-on that thought the
    piece was still there.
    """
    cart = _cart(_line(1, 100000), _line(2, 100000), _line(3, 100000))
    rules = [
        _rule(
            9,
            layer="storewide",
            brand="",
            combinable=True,
            trigger_type="group",
            reward_type="item_free",
            trigger_config={"buy": 2, "get": 1},
        ),
    ]
    assert resolve(cart, rules).total_discount_paise == 0


def test_the_engine_imports_no_orm() -> None:
    """The engine has to run in a browser tab as well as in Django.

    Stated as a test because the day somebody reaches for `Sku.objects` inside
    `resolution.py` is the day the TypeScript port stops being a port.
    """
    import offers.resolution as engine

    source = engine.__file__
    assert source is not None
    text = open(source).read()
    for forbidden in ("django", "models", "objects.", "from masters", "from sell"):
        assert forbidden not in text, f"the engine reached for {forbidden!r}"
