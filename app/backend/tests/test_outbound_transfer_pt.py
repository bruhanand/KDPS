"""Outbound slice 5 — every transfer carries its own PT (#72).

Seams:
- **Format seam**: ``build_transfer_pt_rows`` turns dispatched lines into KDPS
  PT rows, and the CSV those rows export to is compared byte-for-byte with a
  checked-in golden file (the PT-mapper golden-file pattern). A column that
  moves, a value that changes shape, or a money format that drifts fails here.
- **Document seam**: dispatch generates the PT and stores it against the
  transfer. There is no write path — the PT is regenerated from the scanned
  lines or it does not change, so document and carton cannot disagree.
- **Boundary seam**: a transfer PT is not an inbound PT. It books no money and
  raises no vendor liability, and no inbound-PT right is consulted to make one —
  locked here so a later tightening of those rights cannot silently stop stores
  transferring stock.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from core.documents import DocStatus, VoucherSeries
from finledger.models import VendorLedgerEntry
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import StoreTransfer, StoreTransferLine, TransferPT
from outbound.transfer_pt import KDPS_COLUMNS, build_transfer_pt_rows
from ptmapper.models import PtFile
from ptmapper.views import MAPPING_STEWARD_ROLES, PATNA_ROLES
from stockledger.models import StockLedgerEntry, StockOnHand

FY = "26-27"
GOLDEN = Path(__file__).parent / "golden" / "transfer-pt.csv"


@pytest.fixture()
def pt_scaffold(db):
    """Two same-state stores, seeded stock, and a store person who may transfer.

    ``BC001`` is fully known — a Master SKU with an MRP and a frozen cohort cost.
    ``BC002`` deliberately is not: it has stock (so it can be scanned and priced
    from the on-hand average) but no Master row, which is how a PT ends up with
    a blank MRP. Both shapes belong in the golden file.
    """
    entity = LegalEntity.objects.create(code="pt-ent", name="PT Entity", pan="AAACT1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACT1234C1ZS",
        state_code="20",
        state_name="Jharkhand",
        legal_entity=entity,
    )
    store_a = Store.objects.create(code="PT-A", name="PT Store A", gstin=gstin)
    store_b = Store.objects.create(code="PT-B", name="PT Store B", gstin=gstin)

    Brand.objects.create(
        code="pt-br",
        name="PtBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    # A store person: transfer:operate, no inbound-PT rights of any kind.
    store_user = User.objects.create_user(
        username="pt_store_mgr",
        password="Test@123",
        role=make_role("store_manager", "Store Manager (PT test)"),
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    store_user.stores.set([store_a])

    sku1 = Sku.objects.create(
        barcode="BC001",
        design="Shirt",
        color="Blue",
        size="M",
        brand="PtBrand",
        item="shirt",
        hsn="6205",
        mrp_paise=99900,
    )
    Cohort.objects.create(
        sku=sku1, barcode="BC001", season="SS26", unit_cost_paise=45000, mrp_paise=99900
    )

    seed = [
        ("BC001", "Shirt", "Blue", "M", "shirt", 10, 45000),
        ("BC002", "Jeans", "Black", "L", "trouser", 6, 30000),
    ]
    for barcode, design, color, size, item, qty, unit_cost in seed:
        dims = dict(
            sku_code=barcode,
            design=design,
            color=color,
            size=size,
            brand="PtBrand",
            season="SS26",
            item=item,
            hsn="6205",
        )
        StockOnHand.objects.create(
            store=store_a, gstin=gstin, net_qty=qty, net_value_paise=qty * unit_cost, **dims
        )
        StockLedgerEntry.objects.create(
            store=store_a,
            gstin=gstin,
            qty=qty,
            amount=qty * unit_cost,
            kind="pt_inward",
            doc_number="PT-SEED",
            line_no=1,
            **dims,
        )

    for code in ["PT-A", "PT-B"]:
        VoucherSeries.objects.create(
            fy=FY, store_code=code, doc_type="STO", prefix=f"{code}/STO/{FY}/", next_seq=1
        )

    return {"gstin": gstin, "store_a": store_a, "store_b": store_b, "user": store_user}


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _draft(s, plan=None) -> StoreTransfer:
    transfer = StoreTransfer.objects.create(
        source_store=s["store_a"],
        destination_store=s["store_b"],
        transfer_type="inter_store",
        created_by=s["user"],
    )
    for barcode, qty in plan or ():
        StoreTransferLine.objects.create(
            transfer=transfer, sku_code=barcode, qty_planned=qty, qty_dispatched=0
        )
    return transfer


def _dispatch(s, transfer, scans) -> None:
    resp = _client(s["user"]).post(
        f"/api/outbound/transfers/{transfer.pk}/dispatch",
        {"scans": [{"barcode": b, "qty": q} for b, q in scans]},
        format="json",
    )
    assert resp.status_code == 200, resp.data


# ---------------------------------------------------------------------------
# The PT is generated at dispatch, from the scans
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_dispatch_generates_the_pt(pt_scaffold):
    """One transfer, one PT — built from what was scanned, not what was planned."""
    s = pt_scaffold
    transfer = _draft(s, plan=[("BC001", 5)])
    _dispatch(s, transfer, [("BC001", 3)])

    pt = TransferPT.objects.get(transfer=transfer)
    assert [r["BARCODE"] for r in pt.rows] == ["BC001"]
    assert pt.rows[0]["QTY"] == 3  # the scan, never the plan
    assert pt.rows[0]["NAG"] == 3
    assert pt.rows[0]["P RATE"] == "450.00"
    assert pt.rows[0]["MRP"] == "999.00"
    assert pt.generated_by_id == s["user"].pk


@pytest.mark.django_db(transaction=True)
def test_planned_but_unscanned_lines_stay_off_the_pt(pt_scaffold):
    """The PT lists what is in the carton. A plan line nobody scanned is not."""
    s = pt_scaffold
    transfer = _draft(s, plan=[("BC001", 3), ("BC002", 2)])
    _dispatch(s, transfer, [("BC001", 3)])

    pt = TransferPT.objects.get(transfer=transfer)
    assert [r["BARCODE"] for r in pt.rows] == ["BC001"]


@pytest.mark.django_db(transaction=True)
def test_no_pt_before_dispatch(pt_scaffold):
    """A draft has scanned nothing, so there is nothing to print."""
    s = pt_scaffold
    transfer = _draft(s, plan=[("BC001", 3)])

    assert not TransferPT.objects.filter(transfer=transfer).exists()
    resp = _client(s["user"]).get(f"/api/outbound/transfers/{transfer.pk}/pt")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# The format — golden file
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_pt_csv_matches_the_golden_kdps_file(pt_scaffold):
    """The exported PT is byte-for-byte the checked-in KDPS-format golden file."""
    s = pt_scaffold
    transfer = _draft(s)  # scan-to-build: no plan at all
    _dispatch(s, transfer, [("BC001", 3), ("BC002", 2)])

    resp = _client(s["user"]).get(f"/api/outbound/transfers/{transfer.pk}/pt.csv")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")

    # Byte-for-byte but for the line ending: the CSV writer emits CRLF, and a
    # golden file checked into the repo with CRLF is one editor away from a
    # meaningless diff. Every character that matters — column order, blanks,
    # money to two places — is still compared exactly.
    produced = resp.content.decode("utf-8").replace("\r\n", "\n")
    assert produced == GOLDEN.read_text(encoding="utf-8")


@pytest.mark.django_db(transaction=True)
def test_golden_file_is_in_kdps_column_order(pt_scaffold):
    """The golden file itself is checked against the KDPS format, so a golden
    file edited to match a broken generator still fails."""
    header = next(csv.reader(io.StringIO(GOLDEN.read_text(encoding="utf-8"))))
    assert header == KDPS_COLUMNS


@pytest.mark.django_db(transaction=True)
def test_pt_downloads_as_excel(pt_scaffold):
    """The file that travels with the goods is downloadable as a real .xlsx."""
    s = pt_scaffold
    transfer = _draft(s)
    _dispatch(s, transfer, [("BC001", 3)])

    resp = _client(s["user"]).get(f"/api/outbound/transfers/{transfer.pk}/pt.xlsx")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp["Content-Type"]
    # The slash-bearing voucher number must not leak into the filename.
    assert "/" not in resp["Content-Disposition"].split("filename=")[1]


@pytest.mark.django_db(transaction=True)
def test_pt_endpoint_serves_the_printable_document(pt_scaffold):
    """The screen that prints the PT reads it whole — columns, rows and the
    route the carton is taking."""
    s = pt_scaffold
    transfer = _draft(s)
    _dispatch(s, transfer, [("BC001", 3)])

    resp = _client(s["user"]).get(f"/api/outbound/transfers/{transfer.pk}/pt")
    transfer.refresh_from_db()
    assert resp.status_code == 200
    assert resp.data["columns"] == KDPS_COLUMNS
    assert resp.data["doc_number"] == transfer.doc_number
    assert resp.data["source_store_code"] == "PT-A"
    assert resp.data["destination_store_code"] == "PT-B"
    assert len(resp.data["rows"]) == 1


# ---------------------------------------------------------------------------
# Never typed, never edited
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_pt_cannot_be_hand_edited(pt_scaffold):
    """There is no write path. The PT endpoint answers reads and nothing else."""
    s = pt_scaffold
    transfer = _draft(s)
    _dispatch(s, transfer, [("BC001", 3)])
    c = _client(s["user"])
    url = f"/api/outbound/transfers/{transfer.pk}/pt"

    for method in (c.post, c.put, c.patch, c.delete):
        assert method(url, {"rows": []}, format="json").status_code == 405


@pytest.mark.django_db(transaction=True)
def test_stored_pt_equals_a_fresh_regeneration(pt_scaffold):
    """Document and carton cannot disagree: what is stored is exactly what the
    scanned lines regenerate to."""
    s = pt_scaffold
    transfer = _draft(s)
    _dispatch(s, transfer, [("BC001", 3), ("BC002", 2)])

    pt = TransferPT.objects.get(transfer=transfer)
    transfer.refresh_from_db()
    assert pt.rows == build_transfer_pt_rows(transfer)


# ---------------------------------------------------------------------------
# A transfer PT is not an inbound PT
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_store_gets_its_transfer_pt_without_any_inbound_pt_right(pt_scaffold):
    """A store dispatching store-to-store gets its transfer PT, and no
    inbound-PT permission is consulted to give it.

    The rulings that took PT-*making* away from stores (#119) and reserved
    PT-*inwarding* for Patna (#124) both concern the inbound PT — the one that
    turns a brand's goods into stock and raises what KDPS owes. Tightening
    either of them must never stop a store sending a carton to a sister store,
    so the absence of both rights is asserted here alongside the PT it still
    gets.
    """
    s = pt_scaffold
    role_code = s["user"].role.code
    assert role_code not in PATNA_ROLES  # may not inward a PT
    assert role_code not in MAPPING_STEWARD_ROLES  # may not make an inbound PT

    transfer = _draft(s)
    _dispatch(s, transfer, [("BC001", 3)])

    pt = TransferPT.objects.get(transfer=transfer)
    assert len(pt.rows) == 1
    assert _client(s["user"]).get(f"/api/outbound/transfers/{transfer.pk}/pt").status_code == 200


@pytest.mark.django_db(transaction=True)
def test_transfer_pt_books_no_money_and_no_inbound_document(pt_scaffold):
    """It is a packing document, not a purchase: no vendor liability, no
    ``PtFile`` that could be pushed into stock a second time."""
    s = pt_scaffold
    transfer = _draft(s)
    _dispatch(s, transfer, [("BC001", 3)])

    assert TransferPT.objects.filter(transfer=transfer).exists()
    assert not VendorLedgerEntry.objects.exists()
    assert not PtFile.objects.exists()
    # Stock moved out and into the in-transit bucket — and nowhere else.
    kinds = set(
        StockLedgerEntry.objects.exclude(doc_number="PT-SEED").values_list("kind", flat=True)
    )
    assert kinds == {"transfer_out", "transit_in"}


@pytest.mark.django_db(transaction=True)
def test_dispatched_transfer_is_submitted_with_its_pt(pt_scaffold):
    """The PT rides the same posting: a dispatched transfer always has one."""
    s = pt_scaffold
    transfer = _draft(s)
    _dispatch(s, transfer, [("BC001", 3)])

    transfer.refresh_from_db()
    assert transfer.docstatus == DocStatus.SUBMITTED
    assert transfer.pt.generated_at is not None
