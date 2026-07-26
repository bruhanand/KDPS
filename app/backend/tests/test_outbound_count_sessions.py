"""Blind count sessions + the merged variance report (#76).

The seams this suite holds, one test apiece:

- **Blind**: an open session's API answer carries no book quantity for any
  piece, scanned or not. Counting to the answer is impossible however the client
  is driven, because the number is not taken until submit.
- **Merge**: two counters' parallel sessions produce *one* variance report, with
  counts added and the book counted once — not once per counter.
- **Value**: the report answers in pieces *and* in rupees, unmasked, to the
  person counting their own location.
- **Cost seam (#103)**: the auto-adjustment's postings carry the books' unit
  cost — asserted as a **non-zero** ledger amount and a balanced GL voucher —
  and no cost the caller sends is ever used.
- **Mid-count movement**: a piece that moved between submit and apply refuses to
  apply until that barcode is confirmed by name.
- **Server-side variance**: the adjustment API derives ``book_qty`` and
  ``adj_qty`` itself; a client that sends its own is ignored.
"""

from __future__ import annotations

import pytest
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalStatus
from core.documents import DocStatus, VoucherSeries
from core.gl import GLEntry
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import CountScope, StockAdjustment
from stockledger.models import StockLedgerEntry, StockOnHand

FY = "26-27"

#: Two pieces at the same store, cheap enough that a small variance stays inside
#: the adjustment tolerance (₹2,000 at stake) and clears itself.
SHIRT = {"barcode": "CT-SHIRT", "brand": "CountBrand", "cost": 30000}  # ₹300
JEANS = {"barcode": "CT-JEANS", "brand": "OtherBrand", "cost": 40000}  # ₹400


def _stock(store, gstin, spec, qty):
    dims = {
        "design": spec["barcode"],
        "color": "Blue",
        "size": "M",
        "brand": spec["brand"],
        "season": "SS26",
        "item": "shirt",
        "hsn": "6205",
    }
    sku = Sku.objects.create(
        barcode=spec["barcode"],
        mrp_paise=99900,
        **{k: v for k, v in dims.items() if k != "season"},  # the SKU master has no season
    )
    Cohort.objects.create(
        sku=sku,
        barcode=spec["barcode"],
        season="SS26",
        unit_cost_paise=spec["cost"],
        mrp_paise=99900,
    )
    StockOnHand.objects.create(
        store=store,
        gstin=gstin,
        sku_code=spec["barcode"],
        net_qty=qty,
        net_value_paise=qty * spec["cost"],
        **dims,
    )
    StockLedgerEntry.objects.create(
        store=store,
        gstin=gstin,
        sku_code=spec["barcode"],
        qty=qty,
        amount=qty * spec["cost"],
        kind="pt_inward",
        doc_number=f"CT-SEED-{spec['barcode']}",
        line_no=1,
        **dims,
    )


@pytest.fixture()
def count_scaffold(db):
    """One store holding ten shirts and ten jeans, and the person who counts."""
    entity = LegalEntity.objects.create(code="cnt-ent", name="Count Entity", pan="AAACC1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACC1234C1ZS",
        state_code="20",
        state_name="Jharkhand",
        legal_entity=entity,
    )
    store = Store.objects.create(code="C-A", name="Count Store", gstin=gstin)
    for spec in (SHIRT, JEANS):
        Brand.objects.create(
            code=spec["brand"].lower(),
            name=spec["brand"],
            ownership=Brand.Ownership.OWNED,
            return_terms=Brand.ReturnTerms.NONE,
        )
        _stock(store, gstin, spec, 10)

    role = make_role("store_manager", "Store manager (count test)")
    counter = User.objects.create_user(
        username="cnt_a", password="Test@123", role=role, scope_type=ScopeType.STORE
    )
    counter.stores.add(store)
    second = User.objects.create_user(
        username="cnt_b", password="Test@123", role=role, scope_type=ScopeType.STORE
    )
    second.stores.add(store)

    VoucherSeries.objects.create(
        fy=FY, store_code="C-A", doc_type="ADJ", prefix=f"C-A/ADJ/{FY}/", next_seq=1
    )
    return {"store": store, "gstin": gstin, "counter": counter, "second": second}


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _open_count(scaffold, user=None) -> int:
    resp = _client(user or scaffold["counter"]).post(
        "/api/outbound/stocktakes", {"store": scaffold["store"].id}, format="json"
    )
    assert resp.status_code == 201, resp.data
    return resp.data["id"]


def _open_session(scaffold, take_id, *, scope=CountScope.STORE, value="", user=None) -> int:
    resp = _client(user or scaffold["counter"]).post(
        f"/api/outbound/stocktakes/{take_id}/sessions",
        {"scope": scope, "scope_value": value},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data["id"]


def _scan(scaffold, session_id, barcode, qty, user=None):
    resp = _client(user or scaffold["counter"]).post(
        f"/api/outbound/count-sessions/{session_id}/scan",
        {"scans": [{"barcode": barcode, "qty": qty}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    return resp.data


def _submit(scaffold, session_id, user=None):
    resp = _client(user or scaffold["counter"]).post(
        f"/api/outbound/count-sessions/{session_id}/submit", {}, format="json"
    )
    assert resp.status_code == 200, resp.data
    return resp.data


def _variance(scaffold, take_id, user=None):
    resp = _client(user or scaffold["counter"]).get(f"/api/outbound/stocktakes/{take_id}/variance")
    assert resp.status_code == 200, resp.data
    return resp.data


def _line(variance, barcode):
    return next(line for line in variance["lines"] if line["sku_code"] == barcode)


# ---------------------------------------------------------------------------
# Blind
# ---------------------------------------------------------------------------


def test_an_open_session_never_answers_with_the_book(count_scaffold):
    """The counter scans nine of ten shirts and the API tells them nothing about
    the missing one — not on the scanned line, and not as a line of its own."""
    take = _open_count(count_scaffold)
    session = _open_session(count_scaffold, take)

    body = _scan(count_scaffold, session, SHIRT["barcode"], 9)

    assert [line["counted_qty"] for line in body["lines"]] == [9]
    assert [line["book_qty"] for line in body["lines"]] == [None]
    # The count is blind, not the identity: the counter still sees what they hold.
    assert body["lines"][0]["brand"] == SHIRT["brand"]


def test_the_book_arrives_only_on_submit(count_scaffold):
    """Submitting is the moment counting stops being blind — and it brings the
    unscanned piece in with it, because a piece nobody found is the shortage."""
    take = _open_count(count_scaffold)
    session = _open_session(count_scaffold, take)
    _scan(count_scaffold, session, SHIRT["barcode"], 9)

    body = _submit(count_scaffold, session)

    booked = {line["sku_code"]: (line["counted_qty"], line["book_qty"]) for line in body["lines"]}
    assert booked == {SHIRT["barcode"]: (9, 10), JEANS["barcode"]: (0, 10)}


# ---------------------------------------------------------------------------
# Merge, pieces and value
# ---------------------------------------------------------------------------


def test_parallel_sessions_merge_into_one_variance_report(count_scaffold):
    """Two counters, two sections, one report. Counts add up; the book does not —
    it is one number per piece however many people looked at it."""
    take = _open_count(count_scaffold)
    first = _open_session(count_scaffold, take, scope=CountScope.SECTION, value="Rack A")
    second = _open_session(
        count_scaffold,
        take,
        scope=CountScope.SECTION,
        value="Rack B",
        user=count_scaffold["second"],
    )
    _scan(count_scaffold, first, SHIRT["barcode"], 4)
    _scan(count_scaffold, second, SHIRT["barcode"], 5, user=count_scaffold["second"])
    _submit(count_scaffold, first)
    _submit(count_scaffold, second, user=count_scaffold["second"])

    variance = _variance(count_scaffold, take)

    shirt = _line(variance, SHIRT["barcode"])
    assert (shirt["counted_qty"], shirt["book_qty"], shirt["adj_qty"]) == (9, 10, -1)
    # A section count speaks only about what it found, so the jeans nobody
    # scanned are not claimed as missing.
    assert JEANS["barcode"] not in [line["sku_code"] for line in variance["lines"]]


def test_the_variance_report_answers_in_pieces_and_in_rupees(count_scaffold):
    """Value is shown to the person counting their own location's stock: they can
    already read the PT that carries the rate."""
    take = _open_count(count_scaffold)
    session = _open_session(count_scaffold, take)
    _scan(count_scaffold, session, SHIRT["barcode"], 9)
    _scan(count_scaffold, session, JEANS["barcode"], 11)
    _submit(count_scaffold, session)

    variance = _variance(count_scaffold, take)

    shirt, jeans = _line(variance, SHIRT["barcode"]), _line(variance, JEANS["barcode"])
    assert shirt["variance_paise"] == -SHIRT["cost"]  # one shirt missing
    assert jeans["variance_paise"] == JEANS["cost"]  # one pair over
    assert variance["net_pieces"] == 0
    assert variance["net_variance_paise"] == JEANS["cost"] - SHIRT["cost"]


def test_a_brand_session_leaves_the_other_brand_alone(count_scaffold):
    """Scope decides the book set: counting one brand cannot report the other
    brand's untouched stock as missing."""
    take = _open_count(count_scaffold)
    session = _open_session(count_scaffold, take, scope=CountScope.BRAND, value=SHIRT["brand"])
    _scan(count_scaffold, session, SHIRT["barcode"], 8)
    _submit(count_scaffold, session)

    variance = _variance(count_scaffold, take)

    assert [line["sku_code"] for line in variance["lines"]] == [SHIRT["barcode"]]


# ---------------------------------------------------------------------------
# The correction — and its cost
# ---------------------------------------------------------------------------


def _count_and_apply(scaffold, *, shirt_counted: int, confirm: list[str] | None = None):
    take = _open_count(scaffold)
    session = _open_session(scaffold, take, scope=CountScope.BRAND, value=SHIRT["brand"])
    if shirt_counted:
        _scan(scaffold, session, SHIRT["barcode"], shirt_counted)
    _submit(scaffold, session)
    return take, _client(scaffold["counter"]).post(
        f"/api/outbound/stocktakes/{take}/apply", {"confirm": confirm or []}, format="json"
    )


def test_a_within_tolerance_variance_adjusts_itself_and_is_logged(count_scaffold):
    """One ₹300 shirt short is inside the adjustment tolerance, so the count
    corrects itself — and the approvals record says *why* nobody was asked."""
    _, resp = _count_and_apply(count_scaffold, shirt_counted=9)

    assert resp.status_code == 201, resp.data
    adjustment = StockAdjustment.objects.get(pk=resp.data["id"])
    assert adjustment.docstatus == DocStatus.SUBMITTED  # posted, not queued
    approval = Approval.objects.get(kind="adjustment", object_id=adjustment.pk)
    assert approval.status == ApprovalStatus.NOT_REQUIRED
    assert "tolerance" in approval.reason.lower()
    assert (
        StockOnHand.objects.get(store=count_scaffold["store"], sku_code=SHIRT["barcode"]).net_qty
        == 9
    )


def test_the_auto_adjustment_posts_at_the_books_cost_never_at_zero(count_scaffold):
    """The #103 seam, on the path this issue creates: the pieces move at the
    cohort's frozen P-RATE, and the money side is a balanced voucher for the same
    amount. A variance that posts at zero is financially invisible."""
    _, resp = _count_and_apply(count_scaffold, shirt_counted=9)
    assert resp.status_code == 201, resp.data

    doc_number = resp.data["doc_number"]
    entry = StockLedgerEntry.objects.get(doc_number=doc_number, sku_code=SHIRT["barcode"])
    assert entry.qty == -1
    assert entry.amount == -SHIRT["cost"] != 0

    gl = GLEntry.objects.filter(doc_number=doc_number)
    assert gl.exists(), "the correction never reached the value ledger"
    assert sum(leg.amount for leg in gl) == 0  # balanced
    assert {abs(leg.amount) for leg in gl} == {SHIRT["cost"]}


def test_a_big_variance_waits_for_a_person(count_scaffold):
    """Ten shirts and nothing found is ₹3,000 at stake — over the tolerance, so
    the document is made and left for a checker rather than posted. Recount and
    banded approval above tolerance are #78."""
    _, resp = _count_and_apply(count_scaffold, shirt_counted=0)

    assert resp.status_code == 201, resp.data
    adjustment = StockAdjustment.objects.get(pk=resp.data["id"])
    assert adjustment.docstatus == DocStatus.DRAFT
    assert Approval.objects.get(kind="adjustment", object_id=adjustment.pk).status == (
        ApprovalStatus.PENDING
    )
    assert not StockLedgerEntry.objects.filter(kind="adjustment").exists()


# ---------------------------------------------------------------------------
# Mid-count movement
# ---------------------------------------------------------------------------


def test_stock_that_moved_mid_count_is_never_overwritten_blind(count_scaffold):
    """A piece that moved between the count and the correction refuses to apply
    until someone confirms that barcode by name — and then applies the difference
    the *count* found, because the later movement is already on the books."""
    take = _open_count(count_scaffold)
    session = _open_session(count_scaffold, take, scope=CountScope.BRAND, value=SHIRT["brand"])
    _scan(count_scaffold, session, SHIRT["barcode"], 9)
    _submit(count_scaffold, session)

    # Somebody sells one while the variance is still on screen.
    on_hand = StockOnHand.objects.get(store=count_scaffold["store"], sku_code=SHIRT["barcode"])
    on_hand.net_qty = 9
    on_hand.net_value_paise = 9 * SHIRT["cost"]
    on_hand.save()

    refused = _client(count_scaffold["counter"]).post(
        f"/api/outbound/stocktakes/{take}/apply", {}, format="json"
    )
    assert refused.status_code == 409, refused.data
    assert [line["sku_code"] for line in refused.data["moved"]] == [SHIRT["barcode"]]
    assert StockAdjustment.objects.count() == 0

    confirmed = _client(count_scaffold["counter"]).post(
        f"/api/outbound/stocktakes/{take}/apply",
        {"confirm": [SHIRT["barcode"]]},
        format="json",
    )
    assert confirmed.status_code == 201, confirmed.data
    line = StockAdjustment.objects.get(pk=confirmed.data["id"]).lines.get()
    assert (line.book_qty, line.counted_qty, line.adj_qty) == (10, 9, -1)


# ---------------------------------------------------------------------------
# The variance is the server's arithmetic
# ---------------------------------------------------------------------------


def test_the_adjustment_api_derives_the_book_and_the_difference_itself(count_scaffold):
    """The old screen typed the book number and did the subtraction. A caller
    that still sends both is ignored: only the count comes from outside."""
    resp = _client(count_scaffold["counter"]).post(
        "/api/outbound/adjustments",
        {
            "store": count_scaffold["store"].id,
            "reason": "miscount",
            "lines": [
                {
                    "sku_code": SHIRT["barcode"],
                    "counted_qty": 7,
                    "book_qty": 999,
                    "adj_qty": 999,
                    "unit_cost_paise": 1,
                }
            ],
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data
    line = resp.data["lines"][0]
    assert (line["book_qty"], line["adj_qty"]) == (10, -3)
    assert line["unit_cost_paise"] == SHIRT["cost"]
