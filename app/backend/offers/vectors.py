"""Loading the golden carts in `offers/vectors/`.

These twelve JSON files are the contract between two engines written in two
languages. Python reads them here; TypeScript reads the very same files from
`app/frontend/src/till/offers.vectors.test.ts`. Neither directory owns them, and
neither engine may be "fixed" by editing one - a vector changes only when the
rulebook's meaning changes, and then it changes for both at once.

Each file is hand-written, expectations included. There is no regeneration
switch, deliberately: a golden file that recomputes its own expectations from
the code it is testing asserts only that the code has not changed today, which
is a different and much smaller claim than the one this slice needs to make.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from offers.resolution import Cart, CartLine, Resolution, Rule, resolve

VECTOR_DIR = Path(__file__).resolve().parent / "vectors"


def _day(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def rule_from_dict(raw: dict[str, Any]) -> Rule:
    """A rule as it rides in the dataset payload, back into engine terms.

    The same shape the till reads off IndexedDB, so this function is the one
    place the wire format is spelled out on the Python side.
    """
    starts = _day(raw.get("starts_on"))
    assert starts is not None, "an offer without a start date cannot be dated"
    return Rule(
        id=int(raw["id"]),
        name=str(raw.get("name") or ""),
        layer=str(raw.get("layer") or ""),
        brand=str(raw.get("brand") or ""),
        trigger_type=str(raw.get("trigger_type") or "none"),
        trigger_config=dict(raw.get("trigger_config") or {}),
        reward_type=str(raw.get("reward_type") or ""),
        reward_config=dict(raw.get("reward_config") or {}),
        item_scope=dict(raw.get("item_scope") or {}),
        starts_on=starts,
        ends_on=_day(raw.get("ends_on")),
        combinable=bool(raw.get("combinable")),
        priority=int(raw.get("priority", 100)),
    )


def cart_line_from_dict(raw: dict[str, Any]) -> CartLine:
    return CartLine(
        line_no=int(raw["line_no"]),
        brand=str(raw.get("brand") or ""),
        item=str(raw.get("item") or ""),
        design=str(raw.get("design") or ""),
        barcode=str(raw.get("barcode") or ""),
        season=str(raw.get("season") or ""),
        qty=int(raw.get("qty", 1)),
        mrp_paise=int(raw.get("mrp_paise", 0)),
        no_discount=bool(raw.get("no_discount")),
    )


@dataclass(frozen=True)
class Vector:
    name: str
    note: str
    cart: Cart
    rules: tuple[Rule, ...]
    expected: dict[str, Any]

    def run(self) -> Resolution:
        return resolve(self.cart, self.rules)


def load(path: Path) -> Vector:
    raw = json.loads(path.read_text())
    day = _day(raw["day"])
    assert day is not None, f"{path.name} has no day"
    return Vector(
        name=str(raw["name"]),
        note=str(raw.get("note") or ""),
        cart=Cart(
            lines=tuple(cart_line_from_dict(line) for line in raw["lines"]),
            day=day,
            declined_gifts=frozenset(int(i) for i in raw.get("declined_gifts") or []),
        ),
        rules=tuple(rule_from_dict(offer) for offer in raw["offers"]),
        expected=dict(raw["expect"]),
    )


def load_all() -> list[Vector]:
    return [load(path) for path in sorted(VECTOR_DIR.glob("*.json"))]
