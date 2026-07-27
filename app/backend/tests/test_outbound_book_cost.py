"""Outbound money postings are valued from the books, never from the payload (#103).

Four documents — write-off, stock adjustment, return-to-vendor, V-flip — used to
take ``unit_cost_paise`` straight off the request and default it to zero. None of
the four New-* screens sends a cost, so every document made through the app
relieved *quantity* at *zero value*: the pieces left, the rupees stayed, and the
stock row ended at 0 pieces still holding money. Two of the four wrote no GL
voucher at all, because their derived total was zero.

Every test here drives the path the **screen** drives — POST the create endpoint
with no cost, approve through the inbox, submit — and asserts the value that was
actually posted. That is the point: the old suite built its lines directly in the
ORM with ``unit_cost_paise`` pre-filled, which is exactly why this shipped green.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ActorPolicy, ScopeType, User
from approvals.models import Approval, ApprovalStatus
from core.gl import GLAccount, GLEntry
from finledger.models import VendorLedgerEntry
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import (
    ReturnToVendor,
    ReturnToVendorLine,
    StockAdjustment,
    VFlip,
    WriteOff,
)
from outbound.posting import OutboundPostingError, post_writeoff
from stockledger.models import StockLedgerEntry, StockOnHand
from vendors.models import Vendor

FY = "26-27"

#: SKU priced by its cohort's frozen P-RATE — what a real inward leaves behind.
COHORT_COST = 45_000  # ₹450 a piece
#: SKU with no cohort: the books fall back to the on-hand average.
AVERAGE_COST = 30_000  # ₹300 a piece


@pytest.fixture()
def books(db):
    """One store holding two priced SKUs, a maker, and a checker.

    ``BC-COHORT`` has a frozen cohort cost; ``BC-AVG`` has none, so the books
    price it by dividing on-hand value by on-hand quantity. Both routes must
    reach the posting engine intact.
    """
    from core.documents import VoucherSeries

    entity = LegalEntity.objects.create(code="bc-ent", name="Book Cost Co", pan="AAACB1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACB1234C1ZT", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    store = Store.objects.create(code="BC-A", name="Book Cost Store", gstin=gstin)

    brand_owned = Brand.objects.create(
        code="bc-own",
        name="BcOwned",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    brand_sor = Brand.objects.create(
        code="bc-sor",
        name="BcSOR",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    vendor = Vendor.objects.create(name="Book Cost Vendor", code="bcvnd")

    def _stock(sku_code, brand_name, qty, unit_cost):
        StockOnHand.objects.create(
            store=store,
            gstin=gstin,
            sku_code=sku_code,
            design="Shirt",
            color="Blue",
            size="M",
            brand=brand_name,
            season="SS26",
            item="shirt",
            hsn="6205",
            net_qty=qty,
            net_value_paise=qty * unit_cost,
        )
        StockLedgerEntry.objects.create(
            store=store,
            gstin=gstin,
            sku_code=sku_code,
            design="Shirt",
            color="Blue",
            size="M",
            brand=brand_name,
            season="SS26",
            item="shirt",
            hsn="6205",
            qty=qty,
            amount=qty * unit_cost,
            kind="pt_inward",
            doc_number=f"BC-SEED-{sku_code}",
            line_no=1,
        )

    _stock("BC-COHORT", "BcOwned", 10, COHORT_COST)
    _stock("BC-AVG", "BcSOR", 10, AVERAGE_COST)

    def _registered(barcode, unit_cost, mrp):
        sku = Sku.objects.create(
            barcode=barcode,
            design="Shirt",
            color="Blue",
            size="M",
            brand="BcOwned",
            item="shirt",
            hsn="6205",
            mrp_paise=mrp,
        )
        Cohort.objects.create(
            sku=sku, barcode=barcode, season="SS26", unit_cost_paise=unit_cost, mrp_paise=mrp
        )

    _registered("BC-COHORT", COHORT_COST, 99_900)
    # A piece the store holds none of, but the books can still price — the
    # stocktake-surplus case (a found piece with a known buying cohort).
    _registered("BC-FOUND", 12_000, 49_900)

    def _user(username, role_code):
        return User.objects.create_user(
            username=username,
            password=TEST_PASSWORD,
            role=make_role(role_code),
            entity=entity,
            scope_type=ScopeType.ALL,
        )

    # Warehouse makes each draft; Accounts executes the approved V-flip; Owner
    # checks. These remain three different people.
    maker = _user("bc_maker", "warehouse")
    executor = _user("bc_executor", "accounts")
    checker = _user("bc_checker", "owner")

    for doc_type in ["WRO", "VFL", "ADJ", "RTV", "STO"]:
        VoucherSeries.objects.create(
            fy=FY,
            store_code=store.code,
            doc_type=doc_type,
            prefix=f"{store.code}/{doc_type}/{FY}/",
            next_seq=1,
        )
    VoucherSeries.objects.get_or_create(
        fy=FY,
        store_code="HO",
        doc_type="VEND",
        defaults={"prefix": f"HO/VEND/{FY}/", "next_seq": 1},
    )

    return {
        "store": store,
        "brand_owned": brand_owned,
        "brand_sor": brand_sor,
        "vendor": vendor,
        "maker": maker,
        "executor": executor,
        "checker": checker,
    }


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _approve(books, kind, doc_id):
    """Clear the document through the inbox, as the second person."""
    approval = Approval.objects.get(kind=kind, object_id=doc_id)
    if approval.status != ApprovalStatus.PENDING:
        return
    resp = _client(books["checker"]).post(
        f"/api/approvals/{approval.pk}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 200, resp.data


def _posted_value(doc_number, kind) -> int:
    """What the stock ledger says this document moved, in paise."""
    return sum(e.amount for e in StockLedgerEntry.objects.filter(doc_number=doc_number, kind=kind))


# ---------------------------------------------------------------------------
# Write-off — the document the bug was found on
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_writeoff_created_without_a_cost_posts_at_the_book_cost(books):
    """The New Write-off screen sends sku/dims/qty and no cost. The line must
    still be born priced, and the posting must relieve value, not just pieces."""
    create = _client(books["maker"]).post(
        "/api/outbound/writeoffs",
        {
            "store": books["store"].id,
            "reason": "Dead stock clearance",
            "lines": [{"sku_code": "BC-COHORT", "design": "Shirt", "size": "M", "qty": 2}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == COHORT_COST

    wo_id = create.data["id"]
    _approve(books, "writeoff", wo_id)
    submit = _client(books["maker"]).post(f"/api/outbound/writeoffs/{wo_id}/submit")
    assert submit.status_code == 200, submit.data

    doc_number = submit.data["doc_number"]
    assert _posted_value(doc_number, "write_off") == -2 * COHORT_COST

    # The rupees left with the pieces — the exact failure in the reported row.
    on_hand = StockOnHand.objects.get(store=books["store"], sku_code="BC-COHORT")
    assert on_hand.net_qty == 8
    assert on_hand.net_value_paise == 8 * COHORT_COST

    gl = list(GLEntry.objects.filter(doc_number=doc_number))
    assert sum(e.amount for e in gl) == 0
    assert [e for e in gl if e.amount > 0][0].account == GLAccount.SUSPENSE
    assert [e for e in gl if e.amount > 0][0].amount == 2 * COHORT_COST


@pytest.mark.django_db(transaction=True)
def test_a_typed_unit_cost_is_not_honoured(books):
    """The other half of the defect: one row posted at ₹300 a piece, a maker's
    number matching no cohort in the SKU's history. A payload cost is now
    read-only on every one of the four — it is ignored, and the books win."""
    create = _client(books["maker"]).post(
        "/api/outbound/writeoffs",
        {
            "store": books["store"].id,
            "reason": "Dead stock clearance",
            "lines": [{"sku_code": "BC-COHORT", "qty": 2, "unit_cost_paise": 1}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == COHORT_COST


@pytest.mark.django_db(transaction=True)
def test_the_books_price_by_on_hand_average_when_there_is_no_cohort(books):
    """The second pricing route. Both must reach the ledger."""
    create = _client(books["maker"]).post(
        "/api/outbound/writeoffs",
        {
            "store": books["store"].id,
            "reason": "Soiled",
            "lines": [{"sku_code": "BC-AVG", "qty": 3}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == AVERAGE_COST

    _approve(books, "writeoff", create.data["id"])
    submit = _client(books["maker"]).post(f"/api/outbound/writeoffs/{create.data['id']}/submit")
    assert submit.status_code == 200, submit.data
    assert _posted_value(submit.data["doc_number"], "write_off") == -3 * AVERAGE_COST


@pytest.mark.django_db(transaction=True)
def test_a_writeoff_the_books_cannot_price_is_refused(books):
    """A money posting is the deliberate exception to flag-don't-block: it
    refuses rather than posting a wrong number as if it were a right one."""
    resp = _client(books["maker"]).post(
        "/api/outbound/writeoffs",
        {
            "store": books["store"].id,
            "reason": "Dead stock",
            "lines": [{"sku_code": "NEVER-BOUGHT", "qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "cannot price NEVER-BOUGHT" in str(resp.data)
    assert not WriteOff.objects.filter(store=books["store"]).exists()


@pytest.mark.django_db(transaction=True)
def test_the_posting_engine_refuses_a_costless_line_whatever_made_it(books):
    """The serializer prices the line, but the engine is the wall — a document
    built in a shell or left over from before this fix still cannot post free
    stock."""
    from outbound.maker_checker import request_document_approval
    from outbound.models import WriteOffLine

    wo = WriteOff.objects.create(
        store=books["store"], reason="legacy draft", created_by=books["maker"]
    )
    WriteOffLine.objects.create(writeoff=wo, sku_code="BC-COHORT", qty=1, unit_cost_paise=0)
    request_document_approval(wo, requested_by=books["maker"])
    _approve(books, "writeoff", wo.id)

    with pytest.raises(OutboundPostingError, match="carries no unit cost"):
        post_writeoff(wo, user=books["maker"])


# ---------------------------------------------------------------------------
# Stock adjustment — wrote no GL voucher at all when the total came out zero
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_shrinkage_adjustment_writes_a_balanced_gl_voucher(books):
    """``total_debit_paise == 0`` meant no voucher, so shrinkage never reached
    the books at all."""
    create = _client(books["maker"]).post(
        "/api/outbound/adjustments",
        {
            "store": books["store"].id,
            "reason": "shrinkage",
            "lines": [{"sku_code": "BC-COHORT", "book_qty": 10, "counted_qty": 7, "adj_qty": -3}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == COHORT_COST

    _approve(books, "adjustment", create.data["id"])
    submit = _client(books["maker"]).post(f"/api/outbound/adjustments/{create.data['id']}/submit")
    assert submit.status_code == 200, submit.data

    doc_number = submit.data["doc_number"]
    assert _posted_value(doc_number, "adjustment") == -3 * COHORT_COST

    gl = list(GLEntry.objects.filter(doc_number=doc_number))
    assert len(gl) == 2, "shrinkage used to write no GL voucher at all"
    assert sum(e.amount for e in gl) == 0
    assert [e for e in gl if e.amount > 0][0].account == GLAccount.SUSPENSE
    assert [e for e in gl if e.amount > 0][0].amount == 3 * COHORT_COST

    on_hand = StockOnHand.objects.get(store=books["store"], sku_code="BC-COHORT")
    assert (on_hand.net_qty, on_hand.net_value_paise) == (7, 7 * COHORT_COST)


@pytest.mark.django_db(transaction=True)
def test_a_found_piece_is_priced_from_its_cohort(books):
    """A surplus for a SKU the store holds none of has no on-hand average to
    read, so the books answer from the buying cohort instead."""
    create = _client(books["maker"]).post(
        "/api/outbound/adjustments",
        {
            "store": books["store"].id,
            "reason": "surplus_found",
            "lines": [
                {
                    "sku_code": "BC-FOUND",
                    "season": "SS26",
                    "book_qty": 0,
                    "counted_qty": 2,
                    "adj_qty": 2,
                }
            ],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == 12_000

    _approve(books, "adjustment", create.data["id"])
    submit = _client(books["maker"]).post(f"/api/outbound/adjustments/{create.data['id']}/submit")
    assert submit.status_code == 200, submit.data

    on_hand = StockOnHand.objects.get(store=books["store"], sku_code="BC-FOUND")
    assert (on_hand.net_qty, on_hand.net_value_paise) == (2, 2 * 12_000)
    gl = list(GLEntry.objects.filter(doc_number=submit.data["doc_number"]))
    assert [e for e in gl if e.amount > 0][0].account == GLAccount.INVENTORY


@pytest.mark.django_db(transaction=True)
def test_a_found_piece_the_books_never_bought_is_refused(books):
    """No on-hand row and no cohort is genuinely unknown — and unknown does not
    get posted at zero."""
    resp = _client(books["maker"]).post(
        "/api/outbound/adjustments",
        {
            "store": books["store"].id,
            "reason": "surplus_found",
            "lines": [{"sku_code": "BC-MYSTERY", "book_qty": 0, "counted_qty": 1, "adj_qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "cannot price BC-MYSTERY" in str(resp.data)
    assert not StockAdjustment.objects.filter(store=books["store"]).exists()


# ---------------------------------------------------------------------------
# Return to vendor — no GL and no vendor credit, so the payable never fell
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_owned_rtv_reduces_the_payable_at_the_book_cost(books):
    """``total_value_paise == 0`` meant no GL and no vendor credit: the goods
    went back and we still owed for them."""
    create = _client(books["maker"]).post(
        "/api/outbound/rtvs",
        {
            "store": books["store"].id,
            "vendor": books["vendor"].id,
            "brand": books["brand_owned"].id,
            "return_type": "defective",
            "logistics_route": "warehouse",
            "lines": [{"sku_code": "BC-COHORT", "qty": 2}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == COHORT_COST

    submit = _client(books["maker"]).post(f"/api/outbound/rtvs/{create.data['id']}/submit")
    assert submit.status_code == 200, submit.data
    doc_number = submit.data["doc_number"]

    assert _posted_value(doc_number, "rtv_out") == -2 * COHORT_COST

    gl = list(GLEntry.objects.filter(doc_number=doc_number))
    assert len(gl) == 2, "an owned RTV used to write no GL at all"
    assert sum(e.amount for e in gl) == 0
    payable = [e for e in gl if e.account == GLAccount.VENDOR_PAYABLE][0]
    assert payable.amount == 2 * COHORT_COST  # debit — reduces what we owe

    credit = VendorLedgerEntry.objects.get(reference=doc_number)
    assert credit.amount == -2 * COHORT_COST
    assert credit.vendor_id == books["vendor"].id


@pytest.mark.django_db(transaction=True)
def test_brand_owned_rtv_still_writes_no_gl_but_relieves_value(books):
    """SOR value stays off-book, so no GL — that is by design. What must change
    is the stock ledger, which used to relieve the pieces for nothing."""
    create = _client(books["maker"]).post(
        "/api/outbound/rtvs",
        {
            "store": books["store"].id,
            "vendor": books["vendor"].id,
            "brand": books["brand_sor"].id,
            "return_type": "seasonal",
            "season": "SS26",
            "lines": [{"sku_code": "BC-AVG", "qty": 4}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data

    submit = _client(books["maker"]).post(f"/api/outbound/rtvs/{create.data['id']}/submit")
    assert submit.status_code == 200, submit.data
    doc_number = submit.data["doc_number"]

    assert _posted_value(doc_number, "seasonal_ret") == -4 * AVERAGE_COST
    assert GLEntry.objects.filter(doc_number=doc_number).count() == 0
    assert VendorLedgerEntry.objects.filter(reference=doc_number).count() == 0

    on_hand = StockOnHand.objects.get(store=books["store"], sku_code="BC-AVG")
    assert (on_hand.net_qty, on_hand.net_value_paise) == (6, 6 * AVERAGE_COST)


@pytest.mark.django_db(transaction=True)
def test_an_rtv_the_books_cannot_price_is_refused(books):
    resp = _client(books["maker"]).post(
        "/api/outbound/rtvs",
        {
            "store": books["store"].id,
            "vendor": books["vendor"].id,
            "brand": books["brand_owned"].id,
            "return_type": "defective",
            "lines": [{"sku_code": "NEVER-BOUGHT", "qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert not ReturnToVendor.objects.filter(store=books["store"]).exists()
    assert not ReturnToVendorLine.objects.exists()


# ---------------------------------------------------------------------------
# V-flip — both legs derive from one cost, and the reclass must actually post
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_vflip_posts_both_legs_and_the_gl_reclass(books):
    """The SOR reversal and the owned-stock booking never posted: ownership
    flipped in stock only. Both stock legs and all four GL legs must carry the
    one derived cost."""
    create = _client(books["maker"]).post(
        "/api/outbound/vflips",
        {
            "store": books["store"].id,
            "original_brand": books["brand_sor"].id,
            "season": "SS26",
            "lines": [{"sku_code": "BC-AVG", "qty": 2}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == AVERAGE_COST

    _approve(books, "vflip", create.data["id"])
    submit = _client(books["executor"]).post(f"/api/outbound/vflips/{create.data['id']}/submit")
    assert submit.status_code == 200, submit.data
    doc_number = submit.data["doc_number"]

    # Deriving once covers both legs: out under the old identity, in under "V ".
    assert _posted_value(doc_number, "vflip_out") == -2 * AVERAGE_COST
    assert _posted_value(doc_number, "vflip_in") == 2 * AVERAGE_COST

    gl = {e.account: e.amount for e in GLEntry.objects.filter(doc_number=doc_number)}
    assert len(gl) == 4, "a V-flip used to write no GL at all"
    assert sum(gl.values()) == 0
    assert gl[GLAccount.SOR_CONTRA] == 2 * AVERAGE_COST
    assert gl[GLAccount.SOR_STOCK] == -2 * AVERAGE_COST
    assert gl[GLAccount.INVENTORY] == 2 * AVERAGE_COST
    assert gl[GLAccount.SUSPENSE] == -2 * AVERAGE_COST

    # Ownership flipped; quantity and value both unmoved.
    on_hand = StockOnHand.objects.get(store=books["store"], sku_code="BC-AVG")
    assert (on_hand.net_qty, on_hand.net_value_paise) == (10, 10 * AVERAGE_COST)
    assert on_hand.brand == "V BcSOR"


@pytest.mark.django_db(transaction=True)
def test_zero_cost_vflip_still_hits_the_immutable_actor_floor(books):
    create = _client(books["maker"]).post(
        "/api/outbound/vflips",
        {
            "store": books["store"].id,
            "original_brand": books["brand_sor"].id,
            "season": "SS26",
            "lines": [{"sku_code": "BC-AVG", "qty": 1}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    _approve(books, "vflip", create.data["id"])
    vflip = VFlip.objects.get(pk=create.data["id"])
    vflip.lines.update(unit_cost_paise=0)  # legacy/malformed row: no GL legs
    ActorPolicy.objects.filter(action="outbound.execute_vflip").update(roles=["warehouse"])

    response = _client(books["maker"]).post(f"/api/outbound/vflips/{vflip.pk}/submit")

    assert response.status_code == 403
    vflip.refresh_from_db()
    assert vflip.docstatus == 0
    assert not StockLedgerEntry.objects.filter(kind__startswith="vflip_").exists()


# ---------------------------------------------------------------------------
# The state that must never exist again
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_writing_off_every_piece_leaves_no_stranded_value(books):
    """The reported row: 0 pieces, ₹7,200. Take the whole on-hand out and the
    value must go to zero with it — and books-health must say so."""
    create = _client(books["maker"]).post(
        "/api/outbound/writeoffs",
        {
            "store": books["store"].id,
            "reason": "Fire damage — whole line",
            "lines": [{"sku_code": "BC-COHORT", "qty": 10}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    _approve(books, "writeoff", create.data["id"])
    submit = _client(books["maker"]).post(f"/api/outbound/writeoffs/{create.data['id']}/submit")
    assert submit.status_code == 200, submit.data

    on_hand = StockOnHand.objects.get(store=books["store"], sku_code="BC-COHORT")
    assert on_hand.net_qty == 0
    assert on_hand.net_value_paise == 0, "zero pieces must not carry rupees"

    health = _client(books["checker"]).get("/api/finledger/health")
    assert health.status_code == 200, health.data
    assert health.data["stranded_stock_value"]["clean"] is True
    assert health.data["stranded_stock_value"]["value_paise"] == 0


@pytest.mark.django_db(transaction=True)
def test_books_health_names_a_stranded_row(books):
    """The guard is a read, not a lock: an append-only ledger cannot un-post a
    bad historical entry, so the state has to be *visible* instead. Simulate the
    reported row and check it is reported."""
    StockOnHand.objects.filter(store=books["store"], sku_code="BC-AVG").update(
        net_qty=0, net_value_paise=720_000
    )

    health = _client(books["checker"]).get("/api/finledger/health")
    assert health.status_code == 200, health.data
    stranded = health.data["stranded_stock_value"]
    assert stranded["clean"] is False
    assert stranded["row_count"] == 1
    assert stranded["value_paise"] == 720_000
    assert stranded["rows"][0]["sku_code"] == "BC-AVG"
    assert stranded["rows"][0]["store_code"] == "BC-A"


# ---------------------------------------------------------------------------
# Which buying cohort priced it — a season nobody named must not be guessed
# ---------------------------------------------------------------------------


def _cohort(barcode, season, unit_cost, mrp=99_900):
    """Register another buying cohort for a barcode the store holds none of."""
    sku = Sku.objects.filter(barcode=barcode).first() or Sku.objects.create(
        barcode=barcode,
        design="Shirt",
        color="Blue",
        size="M",
        brand="BcOwned",
        item="shirt",
        hsn="6205",
        mrp_paise=mrp,
    )
    Cohort.objects.create(
        sku=sku, barcode=barcode, season=season, unit_cost_paise=unit_cost, mrp_paise=mrp
    )


@pytest.mark.django_db(transaction=True)
def test_a_found_piece_bought_in_two_seasons_is_refused_when_no_season_is_named(books):
    """The same SKU can be bought across seasons at different locked costs. A
    surplus that names no season is not "price it from whichever cohort sorts
    first" — that is a guess wearing the clothes of a book value. The screen
    sends no season at all, so this is the ordinary path, not an edge."""
    _cohort("BC-TWICE", "AW25", 5_000)
    _cohort("BC-TWICE", "SS26", 90_000)

    resp = _client(books["maker"]).post(
        "/api/outbound/adjustments",
        {
            "store": books["store"].id,
            "reason": "surplus_found",
            "lines": [{"sku_code": "BC-TWICE", "book_qty": 0, "counted_qty": 1, "adj_qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "AW25" in str(resp.data) and "SS26" in str(resp.data)
    assert not StockAdjustment.objects.filter(store=books["store"]).exists()


@pytest.mark.django_db(transaction=True)
def test_a_found_piece_bought_once_is_priced_without_naming_a_season(books):
    """One cohort is not a guess — there is only one answer the books can give,
    so a surplus that names no season is still priced rather than refused."""
    create = _client(books["maker"]).post(
        "/api/outbound/adjustments",
        {
            "store": books["store"].id,
            "reason": "surplus_found",
            "lines": [{"sku_code": "BC-FOUND", "book_qty": 0, "counted_qty": 2, "adj_qty": 2}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == 12_000


@pytest.mark.django_db(transaction=True)
def test_naming_the_season_prices_a_twice_bought_piece(books):
    """Naming it removes the ambiguity — and the answer is that season's cost,
    not the other one."""
    _cohort("BC-TWICE", "AW25", 5_000)
    _cohort("BC-TWICE", "SS26", 90_000)

    create = _client(books["maker"]).post(
        "/api/outbound/adjustments",
        {
            "store": books["store"].id,
            "reason": "surplus_found",
            "lines": [
                {
                    "sku_code": "BC-TWICE",
                    "season": "AW25",
                    "book_qty": 0,
                    "counted_qty": 1,
                    "adj_qty": 1,
                }
            ],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    assert create.data["lines"][0]["unit_cost_paise"] == 5_000


@pytest.mark.django_db(transaction=True)
def test_a_cohort_carrying_no_cost_falls_through_to_the_on_hand_average(books):
    """A registered cohort with no P-RATE on it is a gap in the books, not a
    piece that cost nothing — the on-hand average is what the books can still
    honestly say."""
    from outbound.posting import book_unit_cost

    _cohort("BC-AVG", "SS26", 0, mrp=99_900)

    assert book_unit_cost(books["store"].id, "BC-AVG") == AVERAGE_COST


# ---------------------------------------------------------------------------
# One number: what the approver was shown is what the engine posts
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_approval_band_reads_the_cost_frozen_on_the_line(books):
    """The line is born with its cost of record, so the amount at stake must be
    read from it — not derived again later. Re-derivation lets the books move
    between drafting and approving, and then the approver is shown one number
    while the engine posts another."""
    create = _client(books["maker"]).post(
        "/api/outbound/writeoffs",
        {
            "store": books["store"].id,
            "reason": "Water damage",
            "lines": [{"sku_code": "BC-COHORT", "qty": 4}],
        },
        format="json",
    )
    assert create.status_code == 201, create.data
    frozen = 4 * COHORT_COST
    approval = Approval.objects.get(kind="writeoff", object_id=create.data["id"])
    assert approval.value_paise == frozen

    resp = _client(books["checker"]).post(
        f"/api/approvals/{approval.pk}/decide",
        {"action": "reject", "reason": "Check the count first"},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    # The books move underneath the draft — a re-costed cohort, exactly what a
    # correction to the inward would do.
    Cohort.objects.filter(barcode="BC-COHORT").update(unit_cost_paise=90_000)

    again = _client(books["maker"]).post(
        f"/api/outbound/writeoffs/{create.data['id']}/request-approval"
    )
    assert again.status_code == 200, again.data

    fresh = Approval.objects.filter(kind="writeoff", object_id=create.data["id"]).order_by("-id")[0]
    assert fresh.value_paise == frozen, "the band must read the line's frozen cost"

    cleared = _client(books["checker"]).post(
        f"/api/approvals/{fresh.pk}/decide", {"action": "approve"}, format="json"
    )
    assert cleared.status_code == 200, cleared.data
    submit = _client(books["maker"]).post(f"/api/outbound/writeoffs/{create.data['id']}/submit")
    assert submit.status_code == 200, submit.data
    assert _posted_value(submit.data["doc_number"], "write_off") == -frozen
