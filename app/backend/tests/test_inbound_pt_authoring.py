"""Non-brand PT authoring + GRN↔PT flow linkage (D2 slice, July 2026).

Covers:
  * POST /ptmapper/files/from-grn/<grn_id> — seeds an authored DRAFT PtFile from
    the GRN's counted lines (Free Size fallback Q29, qty from the GRN count,
    brand/colour resolved through the lookup tables, damaged-only lines skipped),
    one live PT per GRN, role-gated;
  * the invoice AI prefill merge (monkeypatched agent) — blank money cells filled
    with provenance 'inferred', the counted QTY never touched, failure annotates;
  * re-run is refused for authored files (no brand file to re-map);
  * send gates: every row needs BARCODE + SEASON before Patna (Q39);
  * GET /inbound/queue — arrivals awaiting a PT, PTs in progress, role-gated;
  * the derived GRN lifecycle: received → sent_to_ho → inwarded, rolling back on
    recall and on reversal (never stored — the GRN is an immutable posted doc).
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import Role, User
from core.documents import VoucherSeries
from files.models import StoredFile
from inbound.models import Grn, GrnLine
from masters.models import Brand, Gstin, LegalEntity, Season, Store
from ptmapper.models import ControlledValue, Lookup, PtFile
from stockledger.posting import financial_year
from vendors.models import Booking, Vendor

# ---------------------------------------------------------------- fixtures


@pytest.fixture
def world(db):
    entity = LegalEntity.objects.create(code="kdps", name="KDPS")
    gstin = Gstin.objects.create(
        legal_entity=entity, gstin="10ABCDE1234F1Z5", state_code="10", state_name="Bihar"
    )
    wh = Store.objects.create(
        code="RAN-WH", name="Ranchi WH", store_type=Store.StoreType.WAREHOUSE, gstin=gstin
    )
    fy = financial_year(date.today())
    VoucherSeries.objects.get_or_create(fy=fy, store_code=wh.code, doc_type="GRN")
    return {"wh": wh}


@pytest.fixture
def vocab(db):
    for dim, values in {
        "brand": ["LOCALWEAR", "JOCKEY"],
        "color": ["BLUE", "RED", "PREMIUM", "MEDIUM", "ECONOMY"],
        "size": ["M", "L", "XL", "FREE SIZE"],
        "season": ["SPRING SUMMER(Jun-26)"],
        "gst": ["5", "18"],
    }.items():
        for v in values:
            ControlledValue.objects.get_or_create(dimension=dim, value=v)
    # identity + alias lookups, as seed_ptmapper writes them
    for dim, key, target in [
        ("brand", "LOCALWEAR", "LOCALWEAR"),
        ("brand", "LOCALWEAR TRADERS", "LOCALWEAR"),
        ("color", "BLUE", "BLUE"),
        ("size", "M", "M"),
        ("size", "FREE SIZE", "FREE SIZE"),
    ]:
        Lookup.objects.get_or_create(dimension=dim, source_key=key, target_value=target, brand="")


def _user(username: str, role_code: str) -> User:
    role, _ = Role.objects.get_or_create(code=role_code, defaults={"name": role_code})
    user = User.objects.create_user(username=username, password="x", role=role)
    user.scope_type = "all"
    user.save(update_fields=["scope_type"])
    return user


@pytest.fixture
def warehouse_client(db):
    c = APIClient()
    c.force_authenticate(_user("wh-op", "warehouse"))
    return c


@pytest.fixture
def patna_client(db):
    c = APIClient()
    c.force_authenticate(_user("patna-acct", "accounts"))
    return c


@pytest.fixture
def store_client(db):
    c = APIClient()
    c.force_authenticate(_user("shop-floor", "store_staff"))
    return c


def _grn(
    world, *, lines, invoice_file=None, vendor_name="Localwear Traders", kind=Grn.Kind.NON_BRANDED
) -> Grn:
    grn = Grn.objects.create(
        store=world["wh"],
        received_at=Grn.ReceivedAt.WAREHOUSE,
        kind=kind,
        is_direct=True,
        vendor_name_raw=vendor_name,
        invoice_number="INV-77",
        invoice_file=invoice_file,
    )
    for raw in lines:
        GrnLine.objects.create(grn=grn, **raw)
    grn.post()
    return grn


LINES = [
    {"style_code": "KURTA-01", "size": "M", "color": "Blue", "received_qty": 4},
    {"style_code": "SAREE-02", "size": "", "color": "Zari Gold", "received_qty": 2},
    {"style_code": "DAMAGED-03", "size": "L", "color": "", "received_qty": 0, "damaged_qty": 1},
]


# ------------------------------------------------- brand PT ↔ GRN link at upload (D3)

_BRAND_CSV = b"STYLE,SIZE,COLOR,QTY\nKURTA-01,M,Blue,4\n"


def _upload_brand_pt(client: APIClient, grn_id: int | None = None):
    payload: dict = {"file": SimpleUploadedFile("brand.csv", _BRAND_CSV, content_type="text/csv")}
    if grn_id is not None:
        payload["grn"] = grn_id
    return client.post("/api/ptmapper/files", payload, format="multipart")


def test_brand_pt_links_to_grn_at_upload(world, vocab, warehouse_client):
    grn = _grn(world, lines=LINES)
    r = _upload_brand_pt(warehouse_client, grn.id)
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["source"] == "brand_file"
    assert body["grn"] == grn.id
    assert PtFile.objects.get(pk=body["id"]).grn_id == grn.id


def test_brand_pt_link_conflicts_with_a_live_pt(world, vocab, warehouse_client):
    grn = _grn(world, lines=LINES)
    first = _upload_brand_pt(warehouse_client, grn.id)
    assert first.status_code == 201, first.content
    again = _upload_brand_pt(warehouse_client, grn.id)
    assert again.status_code == 409
    assert again.json()["pt_file_id"] == first.json()["id"]


def test_brand_pt_upload_without_grn_still_works(world, vocab, warehouse_client):
    r = _upload_brand_pt(warehouse_client)
    assert r.status_code == 201, r.content
    assert r.json()["grn"] is None


def test_brand_pt_link_to_missing_grn_is_404(world, vocab, warehouse_client):
    r = _upload_brand_pt(warehouse_client, 999_999)
    assert r.status_code == 404


# ---------------------------------------------------------------- from-grn seeding


def test_from_grn_seeds_rows_from_counted_lines(world, vocab, warehouse_client):
    grn = _grn(world, lines=LINES)
    r = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["source"] == "invoice"
    assert body["grn"] == grn.id
    assert body["grn_number"] == grn.doc_number
    assert body["row_count"] == 2  # the damaged-only line never becomes stock

    row1, row2 = body["rows"]
    # counted facts land as 'direct' and the qty is the GRN count
    assert row1["data"]["DESIGN"] == "KURTA-01"
    assert row1["data"]["QTY"] == 4
    assert row1["data"]["NAG"] == 4
    assert row1["data"]["SIZE"] == "M"
    assert row1["data"]["COLOR"] == "BLUE"  # resolved through the lookup table
    assert row1["data"]["BRAND"] == "LOCALWEAR"  # vendor alias → Master brand
    assert row1["provenance"]["QTY"] == "direct"
    # sizeless goods are FREE SIZE (Q29), a derived value — never blank
    assert row2["data"]["SIZE"] == "FREE SIZE"
    assert row2["provenance"]["SIZE"] == "derived"
    # an unknown colour stays blank for the editor, with the raw kept as a hint
    assert row2["data"]["COLOR"] == ""
    assert row2["raw"]["COLOR"] == "Zari Gold"
    assert "COLOR" in row2["blanks"]
    # authoring never floods the review queue
    from ptmapper.models import ReviewItem

    assert ReviewItem.objects.count() == 0


def test_from_grn_is_one_live_pt_per_grn(world, vocab, warehouse_client):
    grn = _grn(world, lines=LINES)
    first = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert first.status_code == 201
    again = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert again.status_code == 409
    assert again.json()["pt_file_id"] == first.json()["id"]


def test_from_grn_role_gate(world, vocab, store_client):
    grn = _grn(world, lines=LINES)
    r = store_client.post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert r.status_code == 403


def test_authored_file_cannot_be_rerun(world, vocab, warehouse_client):
    grn = _grn(world, lines=LINES)
    pt_id = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}").json()["id"]
    r = warehouse_client.post(f"/api/ptmapper/files/{pt_id}/rerun", {}, format="json")
    assert r.status_code == 409
    assert "no brand file" in r.json()["detail"]


# ---------------------------------------------------------------- invoice AI prefill


def _fake_extract(*_args, **_kwargs):
    return {
        "invoice_number": "INV-77",
        "vendor_name": "Localwear Traders",
        "confidence": 0.9,
        "lines": [
            {
                "style_code": "KURTA-01",
                "size": "M",
                "quantity": 99,  # must NOT win over the counted 4
                "rate": 450.5,
                "mrp": 999,
                "hsn": "6204",
                "gst_percent": 5.0,
            }
        ],
    }


def test_invoice_prefill_fills_blank_money_cells_only(world, vocab, warehouse_client, monkeypatch):
    monkeypatch.setattr("inbound.agents.read_invoice_for_pt", _fake_extract)
    stored = StoredFile.objects.create(
        filename="inv.pdf",
        content_type="application/pdf",
        size=4,
        content=b"%PDF",
        kind=StoredFile.Kind.INVOICE,
    )
    grn = _grn(world, lines=LINES, invoice_file=stored)
    r = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert r.status_code == 201, r.content
    body = r.json()
    row1 = body["rows"][0]
    assert row1["data"]["P RATE"] == 450.5
    assert row1["data"]["BASIC"] == 450.5
    assert row1["data"]["MRP"] == 999
    assert row1["data"]["HSN"] == "6204"
    assert row1["data"]["INPUT TAX"] == 5  # 5.0 collapses to the Master-comparable 5
    assert row1["provenance"]["MRP"] == "inferred"  # AI is never final (Rule 8)
    assert row1["data"]["QTY"] == 4  # the human count always wins
    assert body["meta"]["invoice_extract"]["cells_filled"] == 6
    # the unmatched row was left alone
    assert body["rows"][1]["data"]["P RATE"] == ""


def test_invoice_prefill_failure_never_blocks_authoring(
    world, vocab, warehouse_client, monkeypatch
):
    def boom(*_a, **_k):
        raise RuntimeError("gemini down")

    monkeypatch.setattr("inbound.agents.read_invoice_for_pt", boom)
    stored = StoredFile.objects.create(
        filename="inv.jpg",
        content_type="image/jpeg",
        size=3,
        content=b"JPG",
        kind=StoredFile.Kind.INVOICE,
    )
    grn = _grn(world, lines=LINES, invoice_file=stored)
    r = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert r.status_code == 201
    assert "gemini down" in r.json()["meta"]["invoice_extract_error"]
    assert r.json()["row_count"] == 2


# ---------------------------------------------------------------- send gates (Q39)


def _fill_for_send(pt_id: int, client: APIClient) -> None:
    """Give every row a barcode + season (+ valued money cells for posting)."""
    pt = PtFile.objects.get(pk=pt_id)
    for row in pt.rows.all():
        row.data = {
            **row.data,
            "BARCODE": row.data.get("BARCODE") or f"BC-{row.line_no}",
            "SEASON": "SPRING SUMMER(Jun-26)",
            "MRP": 999,
            "P RATE": 450,
        }
        row.save(update_fields=["data"])


def test_send_blocks_until_barcode_and_season(world, vocab, warehouse_client):
    grn = _grn(world, lines=LINES)
    pt_id = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}").json()["id"]
    r = warehouse_client.post(f"/api/ptmapper/files/{pt_id}/send")
    assert r.status_code == 409
    rows = r.json()["rows"]
    assert all("BARCODE" in p["missing"] and "SEASON" in p["missing"] for p in rows)

    _fill_for_send(pt_id, warehouse_client)
    ok = warehouse_client.post(f"/api/ptmapper/files/{pt_id}/send")
    assert ok.status_code == 200
    assert ok.json()["stage"] == "sent"


def test_brand_file_send_is_unaffected_by_the_gate(db, vocab, warehouse_client):
    pt = PtFile.objects.create(original_filename="brand.xlsx", row_count=1)
    from ptmapper.models import PtRow

    PtRow.objects.create(pt_file=pt, line_no=1, data={"QTY": 1, "NAG": 1}, blanks=[])
    r = warehouse_client.post(f"/api/ptmapper/files/{pt.id}/send")
    assert r.status_code == 200  # no barcode/season on the row, still sendable


# ---------------------------------------------------------------- the work queue (Q9)


def test_queue_lists_arrivals_and_clears_on_pt(world, vocab, warehouse_client):
    grn = _grn(world, lines=LINES)
    q = warehouse_client.get("/api/inbound/queue").json()
    assert q["counts"] == {"awaiting_pt": 1, "pt_in_progress": 0}
    assert q["awaiting_pt"][0]["number"] == grn.doc_number
    assert q["awaiting_pt"][0]["status"] == "received"

    pt_id = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}").json()["id"]
    q = warehouse_client.get("/api/inbound/queue").json()
    assert q["counts"] == {"awaiting_pt": 0, "pt_in_progress": 1}
    assert q["pt_in_progress"][0]["id"] == pt_id
    assert q["pt_in_progress"][0]["grn_number"] == grn.doc_number


def test_queue_is_a_warehouse_ho_screen(world, vocab, store_client):
    r = store_client.get("/api/inbound/queue")
    assert r.status_code == 403


# ------------------------------------------------- derived GRN lifecycle (full walk)


def test_grn_status_walks_the_d2_lifecycle(world, vocab, warehouse_client, patna_client):
    grn = _grn(world, lines=LINES)

    def grn_status() -> str:
        return warehouse_client.get(f"/api/inbound/grns/{grn.id}").json()["status"]

    assert grn_status() == "received"
    pt_id = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}").json()["id"]
    assert grn_status() == "received"  # mapping in progress is still 'received'

    _fill_for_send(pt_id, warehouse_client)
    warehouse_client.post(f"/api/ptmapper/files/{pt_id}/send")
    assert grn_status() == "sent_to_ho"

    patna_client.post(f"/api/ptmapper/files/{pt_id}/recall")
    assert grn_status() == "received"  # a recalled PT rolls the arrival back

    warehouse_client.post(f"/api/ptmapper/files/{pt_id}/send")
    posted = patna_client.post(f"/api/ptmapper/files/{pt_id}/post", {}, format="json")
    assert posted.status_code == 200, posted.content
    assert grn_status() == "inwarded"

    reversed_ = patna_client.post(f"/api/ptmapper/files/{pt_id}/reverse")
    assert reversed_.status_code == 200, reversed_.content
    assert grn_status() == "received"  # a reversed PT re-opens the arrival
    # …and the queue offers the arrival again (the reversed PT freed the slot)
    q = warehouse_client.get("/api/inbound/queue").json()
    assert q["counts"]["awaiting_pt"] == 1
    again = warehouse_client.post(f"/api/ptmapper/files/from-grn/{grn.id}")
    assert again.status_code == 201


# ------------------------------------------------- kind discriminator (branded/non-branded, #44)


@pytest.fixture
def store(world):
    """A selling store (not a warehouse) — where branded goods land."""
    s = Store.objects.create(
        code="DEO-01", name="Deoghar", store_type=Store.StoreType.STORE, gstin=world["wh"].gstin
    )
    VoucherSeries.objects.get_or_create(
        fy=financial_year(date.today()), store_code=s.code, doc_type="GRN"
    )
    return s


def _create_grn(client: APIClient, *, store: Store, kind: str):
    return client.post(
        "/api/inbound/grns",
        {
            "store_id": store.id,
            "kind": kind,
            "invoice_number": "INV-K",
            "lines": [{"style_code": "TEE-1", "size": "M", "color": "Blue", "received_qty": 3}],
        },
        format="json",
    )


def test_kind_roundtrips_on_create_and_read(world, store, warehouse_client):
    r = _create_grn(warehouse_client, store=store, kind=Grn.Kind.BRANDED)
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "branded"
    detail = warehouse_client.get(f"/api/inbound/grns/{r.json()['id']}").json()
    assert detail["kind"] == "branded"


def test_kind_defaults_to_branded_when_omitted(world, store, warehouse_client):
    r = warehouse_client.post(
        "/api/inbound/grns",
        {"store_id": store.id, "lines": [{"style_code": "T", "received_qty": 1}]},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "branded"


def test_non_branded_create_rejected_at_non_warehouse(world, store, warehouse_client):
    r = _create_grn(warehouse_client, store=store, kind=Grn.Kind.NON_BRANDED)
    assert r.status_code == 400
    assert "warehouse" in r.json()["detail"].lower()


def test_non_branded_create_allowed_at_any_warehouse(world, warehouse_client):
    other = Store.objects.create(
        code="PAT-WH",
        name="Patna WH",
        store_type=Store.StoreType.WAREHOUSE,
        gstin=world["wh"].gstin,
    )
    VoucherSeries.objects.get_or_create(
        fy=financial_year(date.today()), store_code=other.code, doc_type="GRN"
    )
    r = _create_grn(warehouse_client, store=other, kind=Grn.Kind.NON_BRANDED)
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "non_branded"


def test_grn_list_filters_by_kind(world, store, warehouse_client):
    _create_grn(warehouse_client, store=store, kind=Grn.Kind.BRANDED)
    _create_grn(warehouse_client, store=world["wh"], kind=Grn.Kind.NON_BRANDED)
    branded = warehouse_client.get("/api/inbound/grns?kind=branded").json()
    assert branded and {g["kind"] for g in branded} == {"branded"}
    non_branded = warehouse_client.get("/api/inbound/grns?kind=non_branded").json()
    assert non_branded and {g["kind"] for g in non_branded} == {"non_branded"}
    assert len(warehouse_client.get("/api/inbound/grns").json()) == 2  # no filter → all visible


def test_awaiting_pt_queue_excludes_branded(world, store, vocab, warehouse_client):
    _create_grn(warehouse_client, store=store, kind=Grn.Kind.BRANDED)
    nb = _create_grn(warehouse_client, store=world["wh"], kind=Grn.Kind.NON_BRANDED).json()
    q = warehouse_client.get("/api/inbound/queue").json()
    assert q["counts"]["awaiting_pt"] == 1  # the branded store arrival is NOT in this bucket
    assert [g["id"] for g in q["awaiting_pt"]] == [nb["id"]]


def test_backfill_keys_off_is_direct_not_booking(world):
    import importlib

    from django.apps import apps as django_apps
    from django.db import connection

    vendor = Vendor.objects.create(code="v1", name="V1")
    brand = Brand.objects.create(code="b1", name="B1")
    season = Season.objects.create(code="SS26", name="SS26")
    booking = Booking.objects.create(number="BK-1", vendor=vendor, brand=brand, season=season)
    # simulate pre-migration rows (everything defaulted to branded)
    linked = Grn.objects.create(
        store=world["wh"], booking=booking, is_direct=False, kind=Grn.Kind.BRANDED
    )
    direct = Grn.objects.create(store=world["wh"], is_direct=True, kind=Grn.Kind.BRANDED)
    # a branded receipt whose booking was later deleted (SET_NULL): booking is now null
    # but is_direct stays False — it must NOT be reclassified as non-branded.
    deleted_booking = Grn.objects.create(
        store=world["wh"], booking=None, is_direct=False, kind=Grn.Kind.BRANDED
    )
    # A SUBMITTED direct receipt — the real shape on the deployed alpha (rows created via
    # the API, which posts them). The kernel FSM trigger forbids updating a submitted row,
    # so the backfill must neutralise it; this row is the regression for the Render
    # "may only move to cancelled" build failure that the draft rows above never exercised.
    submitted = _grn(world, lines=LINES, kind=Grn.Kind.BRANDED)
    assert submitted.docstatus == 1  # SUBMITTED — the state the FSM guard locks down

    mod = importlib.import_module("inbound.migrations.0005_grn_kind")
    with connection.schema_editor(atomic=False) as schema_editor:
        mod.backfill_kind(django_apps, schema_editor)  # must not raise the FSM ProgrammingError

    for grn in (linked, direct, deleted_booking, submitted):
        grn.refresh_from_db()
    assert linked.kind == Grn.Kind.BRANDED  # booking-linked → branded
    assert direct.kind == Grn.Kind.NON_BRANDED  # direct receipt → non-branded
    assert deleted_booking.kind == Grn.Kind.BRANDED  # null booking but not direct → stays branded
    assert submitted.kind == Grn.Kind.NON_BRANDED  # submitted direct receipt flips despite the FSM
