"""The whole vertical, once: a PT file becomes a barcode the counter can scan.

Every stage of this journey is already covered somewhere — mapping in the
ptmapper suites, posting in `test_iteration11`, dispatch in the outbound slices,
the till payload in `test_sell_dataset`. What no suite asserts is that the
stages *join up*: that the file the warehouse sends is the stock Patna posts, is
the carton the store receives, is the row the till can price. A break in any
joint shows up in the shop as "the new stock will not scan", which is the one
failure nobody can diagnose from a unit test.

So this walks it end to end through the API, as the four people actually do it,
and then walks the same endpoints again as the wrong person to show which gates
hold. Two routes, because KDPS has two: branded goods land at the selling store
and never move, non-branded land at the warehouse and are transferred out.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from _transfers import approve_transfer
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from core.documents import VoucherSeries
from masters.models import Cohort, Gstin, GstSlab, LegalEntity, Sku, Store
from outbound.models import StoreTransfer
from ptmapper.models import ControlledValue, Lookup
from stockledger.models import StockOnHand
from stockledger.posting import financial_year

BARCODE = "FLOW-0001"
SEASON = "SPRING SUMMER(Jun-26)"

#: One brand PT line, in the brand's own sheet — the shape the engine reads.
PT_CSV = (
    "BARCODE,QTY,MRP,RATE,SEASON,BRAND,COLOR,SIZE,ITEM,HSN,DESIGN\n"
    f"{BARCODE},4,1499,700,{SEASON},LOCALWEAR,BLUE,M,T-SHIRT,6109,DSG-1\n"
).encode()


def _series(store: Store) -> None:
    fy = financial_year(date.today())
    for doc_type in ("GRN", "PT", "STO"):
        VoucherSeries.objects.get_or_create(fy=fy, store_code=store.code, doc_type=doc_type)


@pytest.fixture
def world(db) -> dict[str, Any]:
    entity = LegalEntity.objects.create(code="kdps", name="KDPS")
    gstin = Gstin.objects.create(
        legal_entity=entity, gstin="10ABCDE1234F1Z5", state_code="10", state_name="Bihar"
    )
    warehouse = Store.objects.create(
        code="RAN-WH", name="Ranchi WH", store_type=Store.StoreType.WAREHOUSE, gstin=gstin
    )
    store = Store.objects.create(
        code="DEO-01", name="Deoghar", store_type=Store.StoreType.STORE, gstin=gstin
    )
    _series(warehouse)
    _series(store)
    GstSlab.objects.get_or_create(effective_from=date(2020, 1, 1))
    return {"entity": entity, "gstin": gstin, "warehouse": warehouse, "store": store}


@pytest.fixture
def vocab(db) -> None:
    for dimension, values in {
        "brand": ["LOCALWEAR"],
        "color": ["BLUE"],
        "size": ["M"],
        "season": [SEASON],
        "item": ["T-SHIRT"],
        "gst": ["5"],
    }.items():
        for value in values:
            ControlledValue.objects.get_or_create(dimension=dimension, value=value)
    # `source_key` is the *normalised* raw (upper, trimmed) — the engine looks the
    # brand's word up in that shape, so a mixed-case key here would never match.
    for dimension, value in [
        ("brand", "LOCALWEAR"),
        ("color", "BLUE"),
        ("size", "M"),
        ("season", SEASON),
    ]:
        Lookup.objects.get_or_create(
            dimension=dimension, source_key=value.upper(), target_value=value, brand=""
        )


def _client(role_code: str, *, store: Store | None = None) -> APIClient:
    """One signed-in person. A till login is scoped to its one store (that is what
    makes it a till); everybody else in this flow works network-wide."""
    user = User.objects.create_user(
        username=f"flow_{role_code}", password=TEST_PASSWORD, role=make_role(role_code)
    )
    user.scope_type = ScopeType.STORE if store is not None else ScopeType.ALL
    user.save(update_fields=["scope_type"])
    if store is not None:
        user.stores.add(store)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def people(world) -> dict[str, APIClient]:
    return {
        "store": _client("store_staff", store=world["store"]),
        "warehouse": _client("warehouse"),
        "accounts": _client("accounts"),
        "promo": _client("promo"),
    }


def _make_grn(client: APIClient, store: Store, *, kind: str = "branded") -> int:
    response = client.post(
        "/api/inbound/grns",
        {
            "store_id": store.id,
            "kind": kind,
            "invoice_number": "INV-FLOW-1",
            "lines": [{"style_code": "DSG-1", "size": "M", "color": "Blue", "received_qty": 4}],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return int(response.json()["id"])


def _upload_pt(client: APIClient, grn_id: int) -> dict[str, Any]:
    upload = SimpleUploadedFile("brand-pt.csv", PT_CSV, content_type="text/csv")
    response = client.post(
        "/api/ptmapper/files",
        {"file": upload, "grn": str(grn_id), "brand": "LOCALWEAR"},
        format="multipart",
    )
    assert response.status_code in (200, 201), response.content
    return dict(response.json())


def _post_pt(people: dict[str, APIClient], pt_id: int) -> dict[str, Any]:
    sent = people["warehouse"].post(f"/api/ptmapper/files/{pt_id}/send", {}, format="json")
    assert sent.status_code == 200, sent.content
    assert sent.json()["stage"] == "sent"
    posted = people["accounts"].post(f"/api/ptmapper/files/{pt_id}/post", {}, format="json")
    assert posted.status_code == 200, posted.content
    body = posted.json()
    assert body["stage"] == "posted"
    return dict(body["post_result"])


# --------------------------------------------------------------- the branded route


def test_branded_arrival_reaches_the_counter(world, vocab, people):
    """Store receives → warehouse maps → Patna posts → the till can price the scan."""
    grn_id = _make_grn(people["store"], world["store"])

    pt = _upload_pt(people["warehouse"], grn_id)
    assert pt["row_count"] == 1
    assert pt["stage"] == "mapping"

    result = _post_pt(people, pt["id"])
    assert result["entries"] == 1
    assert result["doc_number"]

    # The identity spine: one SKU, one buying cohort, one shelf row.
    assert Sku.objects.filter(barcode=BARCODE).exists()
    assert Cohort.objects.filter(barcode=BARCODE, season=SEASON).exists()
    on_hand = StockOnHand.objects.get(store=world["store"], sku_code=BARCODE)
    assert on_hand.net_qty == 4

    # The counter's own copy — the last joint in the chain.
    dataset = people["store"].get("/api/sell/dataset").json()
    item = next(row for row in dataset["items"] if row["barcode"] == BARCODE)
    assert item["mrp_paise"] == 149900
    assert {row["barcode"]: row["qty"] for row in dataset["stock"]}[BARCODE] == 4
    # H2: the shop knows the ticket price and never the cost.
    assert not [key for key in item if "cost" in key]


# --------------------------------------------------------------- the warehouse route


def test_warehouse_arrival_reaches_the_counter_through_a_transfer(world, vocab, people):
    """Non-branded goods land at the warehouse and only sell after a transfer lands."""
    grn_id = _make_grn(people["warehouse"], world["warehouse"], kind="non_branded")
    pt = _upload_pt(people["warehouse"], grn_id)
    _post_pt(people, pt["id"])

    assert StockOnHand.objects.get(store=world["warehouse"], sku_code=BARCODE).net_qty == 4
    # Nothing at the shop yet — this is the step people forget.
    assert not StockOnHand.objects.filter(store=world["store"], sku_code=BARCODE).exists()
    assert BARCODE not in {
        row["barcode"] for row in people["store"].get("/api/sell/dataset").json()["items"]
    }

    draft = people["warehouse"].post(
        "/api/outbound/transfers",
        {
            "source_store": world["warehouse"].id,
            "destination_store": world["store"].id,
            "transfer_type": "store_split",
            "transport_mode": "public_bus",
        },
        format="json",
    )
    assert draft.status_code == 201, draft.content
    transfer_id = draft.json()["id"]
    approve_transfer(StoreTransfer.objects.get(pk=transfer_id))

    dispatched = people["warehouse"].post(
        f"/api/outbound/transfers/{transfer_id}/dispatch",
        {"scans": [{"barcode": BARCODE, "qty": 3}]},
        format="json",
    )
    assert dispatched.status_code == 200, dispatched.content

    received = people["store"].post(
        f"/api/outbound/transfers/{transfer_id}/receive",
        {"scans": [{"barcode": BARCODE, "qty": 3}]},
        format="json",
    )
    assert received.status_code == 200, received.content

    assert StockOnHand.objects.get(store=world["store"], sku_code=BARCODE).net_qty == 3
    assert StockOnHand.objects.get(store=world["warehouse"], sku_code=BARCODE).net_qty == 1
    dataset = people["store"].get("/api/sell/dataset").json()
    assert {row["barcode"]: row["qty"] for row in dataset["stock"]}[BARCODE] == 3


# --------------------------------------------------------------- the gates


def test_only_the_warehouse_may_make_a_pt(world, vocab, people):
    """`receive_goods: approve` — the rung PT-making rose to in #119."""
    grn_id = _make_grn(people["store"], world["store"])
    for who in ("store", "accounts", "promo"):
        upload = SimpleUploadedFile("brand-pt.csv", PT_CSV, content_type="text/csv")
        refused = people[who].post(
            "/api/ptmapper/files", {"file": upload, "grn": str(grn_id)}, format="multipart"
        )
        assert refused.status_code == 403, f"{who} could upload a PT: {refused.status_code}"


def test_only_accounts_or_owner_may_post_a_pt(world, vocab, people):
    """The money gate: posting is what turns paperwork into stock the books own."""
    grn_id = _make_grn(people["store"], world["store"])
    pt = _upload_pt(people["warehouse"], grn_id)
    people["warehouse"].post(f"/api/ptmapper/files/{pt['id']}/send", {}, format="json")
    for who in ("store", "warehouse", "promo"):
        refused = people[who].post(f"/api/ptmapper/files/{pt['id']}/post", {}, format="json")
        assert refused.status_code == 403, f"{who} could post a PT: {refused.status_code}"


#: The gap these two record. Making a PT needs `receive_goods: approve` (#119),
#: and the sidebar shows PT Files to nobody below it — but `PtFileSendView` and
#: `PtRowsUpdateView` carry no section gate of their own (both sit on the
#: `UNGATED_VIEWS` register in `test_rbac_gate_contract`), so the *edit* and the
#: *hand-over* behind that screen answer to authentication alone. A store
#: cashier, or the promo author holding `receive_goods: none`, can rewrite a
#: mapped file and send it to Patna over the API. Strict xfail, so whoever
#: closes the hole is told to delete the marker rather than left guessing.
UNGATED_PT_WRITE = pytest.mark.xfail(
    strict=True,
    reason="PtFileSendView / PtRowsUpdateView name no section gate — the screen "
    "is warehouse-only, the endpoints behind it are not",
)


@UNGATED_PT_WRITE
@pytest.mark.parametrize("who", ["store", "promo"])
def test_only_the_warehouse_may_send_a_pt_to_patna(world, vocab, people, who):
    grn_id = _make_grn(people["store"], world["store"])
    pt = _upload_pt(people["warehouse"], grn_id)
    sent = people[who].post(f"/api/ptmapper/files/{pt['id']}/send", {}, format="json")
    assert sent.status_code == 403


@UNGATED_PT_WRITE
@pytest.mark.parametrize("who", ["store", "promo"])
def test_only_the_warehouse_may_edit_pt_rows(world, vocab, people, who):
    grn_id = _make_grn(people["store"], world["store"])
    pt = _upload_pt(people["warehouse"], grn_id)
    edited = people[who].patch(
        f"/api/ptmapper/files/{pt['id']}/rows",
        {"fills": [{"column": "COLOR", "value": "BLUE", "scope": "all"}]},
        format="json",
    )
    assert edited.status_code == 403


def test_a_posted_pt_is_locked(world, vocab, people):
    grn_id = _make_grn(people["store"], world["store"])
    pt = _upload_pt(people["warehouse"], grn_id)
    _post_pt(people, pt["id"])
    locked = people["warehouse"].patch(
        f"/api/ptmapper/files/{pt['id']}/rows",
        {"fills": [{"column": "COLOR", "value": "BLUE", "scope": "all"}]},
        format="json",
    )
    assert locked.status_code == 409
