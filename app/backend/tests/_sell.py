"""Building a store that can sell, and a bill it could plausibly have sold.

Every sale test needs the same five things standing up — a registration, a store,
a counter person, somebody whose name goes on the line, and a priced piece — and
each one of them is boring in its own way. They live here so a test can say what
it is actually about.

The bill helper is the load-bearing one. A bill has to add up before the server
will look at it (gross less discount is the line, tax is what is inside the line
at the rate quoted, tenders come to the total), so a test that wants a *wrong*
bill has to start from a right one and break exactly one thing. `bill_payload`
is that right one.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any

from _creds import TEST_PASSWORD
from _rbac import make_role
from django.db import transaction
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from accounts.sections import CAP_APPROVE
from core.documents import VoucherSeries
from masters.models import Cohort, Gstin, GstSlab, LegalEntity, Season, Sku, Store
from sell.models import Salesman
from stockledger.models import StockLedgerEntry
from stockledger.projections import post_on_hand_movement

SALES_URL = "/api/sell/sales"
FY = "26-27"

#: ₹1,499 shirt that cost ₹700 — an ordinary KDPS line, in paise.
MRP_PAISE = 149900
COST_PAISE = 70000

#: How the fixture piece describes itself, everywhere it is described.
_SKU_DIMS = {
    "design": "SHIRT-01",
    "color": "NAVY",
    "size": "M",
    "brand": "MUFTI",
    "item": "Shirt",
    "hsn": "6205",
}


def gst_on(inclusive_paise: int, rate: str = "5") -> int:
    """The tax inside a GST-inclusive amount, the way the till computes it."""
    base = (Decimal(inclusive_paise) * 100 / (100 + Decimal(rate))).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return inclusive_paise - int(base)


def build_store(code: str = "SEL-DEO", state: str = "10") -> Store:
    entity, _ = LegalEntity.objects.get_or_create(
        code="sell-ent", defaults={"name": "Sell Entity", "pan": "AAACS1234B"}
    )
    gstin, _ = Gstin.objects.get_or_create(
        gstin=f"{state}AAACS1234B1Z{state[0]}",
        defaults={
            "state_code": state,
            "state_name": "Bihar" if state == "10" else "Jharkhand",
            "legal_entity": entity,
        },
    )
    store, _ = Store.objects.get_or_create(
        code=code, defaults={"name": f"Sell {code}", "gstin": gstin}
    )
    for doc_type in ("SAL", "CRN", "SRT"):
        VoucherSeries.objects.get_or_create(fy=FY, store_code=store.code, doc_type=doc_type)
    GstSlab.objects.get_or_create(
        name="Apparel (sell tests)",
        defaults={
            "threshold_paise": 250000,
            "rate_below": 5,
            "rate_above": 18,
            "effective_from": "2025-09-22",
        },
    )
    Season.objects.get_or_create(
        code="FW25", defaults={"name": "Autumn/Winter 2025", "status": "open", "sort_order": 2}
    )
    return store


def build_piece(
    barcode: str = "8901000000011",
    season: str = "FW25",
    cost_paise: int = COST_PAISE,
    mrp_paise: int = MRP_PAISE,
) -> Cohort:
    sku, _ = Sku.objects.update_or_create(
        barcode=barcode, defaults={**_SKU_DIMS, "mrp_paise": mrp_paise}
    )
    cohort, _ = Cohort.objects.update_or_create(
        barcode=barcode,
        season=season,
        defaults={"sku": sku, "unit_cost_paise": cost_paise, "mrp_paise": mrp_paise},
    )
    return cohort


def stock_in(
    store: Store,
    qty: int,
    *,
    barcode: str = "8901000000011",
    cost_paise: int = COST_PAISE,
    doc_number: str = "26-27/SEL-DEO/PT/1",
) -> None:
    """Put `qty` on the shelf the way an inward puts it there — through the ledger.

    Writing `StockOnHand` straight would be shorter and would be a lie: the
    projection is a cache of the ledger, so a fixture that seeds one without the
    other cannot be checked against a rebuild, and any test that tried would be
    measuring the fixture.
    """
    cohort = build_piece(barcode=barcode, cost_paise=cost_paise)
    # A movement locks the projection row it is about to change, so it needs a
    # transaction of its own here: the suites that drive real threads run outside
    # one, and in the ordinary suites this nests harmlessly.
    with transaction.atomic():
        post_on_hand_movement(
            store=store,
            gstin=store.gstin,
            sku_code=barcode,
            source=SimpleNamespace(season=cohort.season, **_SKU_DIMS),
            qty=qty,
            unit_cost_paise=cost_paise,
            kind=StockLedgerEntry.Kind.PT_INWARD,
            doc_number=doc_number,
            line_no=1,
        )


def build_cashier(store: Store, username: str = "sell_cashier") -> User:
    """A store person: `sell: operate`, scoped to this store and no other."""
    user = User.objects.create_user(
        username=username,
        password=TEST_PASSWORD,
        role=make_role("store_staff", "Store staff (sell tests)"),
        scope_type=ScopeType.STORE,
    )
    user.stores.add(store)
    return user


def build_manager(store: Store, username: str = "sell_manager") -> User:
    """A store manager holding `sell: approve` — the second eye at this counter.

    The rung is granted here the way an access administrator grants it: by
    writing the cell on the stored role row, which is the authority every gate
    reads (#173 made the matrix editable data, and its contract test asserts
    gates against *the stored matrix, whatever it says*).

    It has to be granted, because the ratified sheet does not: it predates the POS
    and gives both store seats `sell: operate`, so out of the box nobody who is
    ever standing at a counter holds the rung the sale contract calls "a manager
    of this store". That is a gap in the seed, not in this code — filed
    separately, and the pipeline is written against the contract's rung.
    """
    role = make_role("store_manager", "Store manager (sell tests)")
    role.section_access = {
        **role.section_access,
        "sell": {"capability": CAP_APPROVE, "label": "Approve counter exceptions"},
    }
    role.save(update_fields=["section_access"])
    user = User.objects.create_user(
        username=username,
        password=TEST_PASSWORD,
        role=role,
        scope_type=ScopeType.STORE,
    )
    user.stores.add(store)
    return user


def build_salesman(store: Store, code: str = "ALIE") -> Salesman:
    salesman, _ = Salesman.objects.get_or_create(
        store=store, code=code, defaults={"name": "Ali E."}
    )
    return salesman


def client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def bill_payload(
    store: Store,
    salesman: Salesman,
    *,
    till_seq: int,
    barcode: str = "8901000000011",
    season: str = "FW25",
    qty: int = 1,
    mrp_paise: int = MRP_PAISE,
    disc_paise: int = 0,
    gst_rate: str = "5",
    idempotency_uuid: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """One clean cash sale that adds up. Break one thing at a time from here."""
    net = mrp_paise * qty - disc_paise
    gst = gst_on(net, gst_rate)
    payload: dict[str, Any] = {
        "idempotency_uuid": idempotency_uuid or str(uuid.uuid4()),
        "store": store.code,
        "fy": FY,
        "till_seq": till_seq,
        "origin": "offline",
        "billed_at": "2026-07-30T12:31:00Z",
        "customer": {"name": "Mrs Sharma", "mobile": "9876543210", "gstin": ""},
        "lines": [
            {
                "line_no": 1,
                "direction": "sale",
                "barcode": barcode,
                "season": season,
                "qty": qty,
                "mrp_paise": mrp_paise,
                "disc_paise": disc_paise,
                "net_paise": net,
                "gst_rate": gst_rate,
                "gst_paise": gst,
                "salesman": salesman.id,
                "offer_evidence": {},
            }
        ],
        "tenders": [{"mode": "cash", "amount_paise": net}],
        "totals": {
            "gross_paise": mrp_paise * qty,
            "discount_paise": disc_paise,
            "net_paise": net,
            "gst_paise": gst,
            "round_paise": 0,
        },
    }
    payload.update(overrides)
    return payload
