"""Preconditions for the live suites that spend seeded stock.

The RTV suites post real return-to-vendor documents against the target database
and draw the fixture stock down one unit at a time. `seed_outbound_demo` lays in
15 units per SKU, so they pass for a while and then start failing with

    Insufficient stock for LP-POLO-BLK-L at store 1: available=0, required=1

which reads like a defect and is not one (issue #93).

The fix is a precondition, not a teardown and *emphatically* not a reseed. These
suites share one Postgres with every other checkout on the machine, and another
workspace may be mid-run against it - a test that rebuilds the database to suit
itself is the exact failure this issue exists to prevent. So: check, and when the
stock is spent, **skip** and tell the operator the one command that fixes it.
Resetting is a decision a person makes, not a side effect of running tests.
"""

from __future__ import annotations

import pytest
import requests

RESET_HINT = (
    "Reseed it yourself when you are sure no other workspace is using the shared "
    "database: `npm run dev:reset && npm run dev` (the test run will never do this "
    "for you - see README, 'The shared database')"
)


def on_hand_qty(base_url: str, headers: dict[str, str], *, sku_code: str, store_code: str) -> int:
    """Units of ``sku_code`` currently on hand at ``store_code``, per the live API."""
    response = requests.get(
        f"{base_url}/api/stockledger/on-hand",
        params={"sku": sku_code, "store": store_code},
        headers=headers,
        timeout=30,
    )
    if response.status_code != 200:
        pytest.skip(
            f"cannot read stock on hand for {sku_code} at {store_code} "
            f"({response.status_code}) - the target is not a seeded server. {RESET_HINT}"
        )
    return sum(
        row.get("net_qty", 0)
        for row in response.json().get("rows", [])
        if row.get("store_code") == store_code
    )


def require_seed_stock(
    base_url: str,
    headers: dict[str, str],
    *,
    sku_code: str,
    store_code: str,
    qty: int = 1,
) -> None:
    """Skip - never fail, never reseed - when the fixture stock is not there."""
    available = on_hand_qty(base_url, headers, sku_code=sku_code, store_code=store_code)
    if available < qty:
        pytest.skip(
            f"outbound demo fixture short: {sku_code} at {store_code} has {available} on "
            f"hand, this test needs {qty}. Either `seed_outbound_demo` never ran against "
            f"this database, or earlier RTV runs spent it - each one posts a real return "
            f"that draws stock down. {RESET_HINT}"
        )
