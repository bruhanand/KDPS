"""Recount + value-banded approval for big count variances (#78).

Slice 10 (#76) made counting blind and gave the variance a value. This suite
holds the control that value exists for: a big variance is not somebody's typo
to post, it is a second person's job to confirm and a named senior's to approve.

The seams, one test apiece:

- **The gate**: a line worth more than the tolerance cannot reach the books at
  all until it has been recounted. Refused by name, like a piece that moved.
- **A different person**: the engine refuses a recount by anyone who counted
  that piece, and no policy row can be retuned to allow it.
- **The trail**: original count, recount, final — all three readable afterwards.
- **The reason**: a recount says *why* (theft / miscount / damage / found), and
  the reason travels onto the correction document.
- **The band**: within it the Store Manager may approve, above it only the
  Operations Head — read from the policy row, retunable as data (Rule 12).
- **One number**: the value that picks the band and the value that posts are the
  same books' cost (#103), never anything a caller sent.
- **The floor**: no retune of any policy column lets the maker approve their own
  correction.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalPolicy, ApprovalStatus
from core.documents import DocStatus, VoucherSeries
from core.gl import GLEntry
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.costing import book_unit_cost
from outbound.models import AdjustmentReason, CountScope, StockAdjustment
from stockledger.models import StockLedgerEntry, StockOnHand

FY = "26-27"

#: ₹300 a shirt, ten of them. Ten missing is ₹3,000 — over the ₹2,000 seeded
#: adjustment tolerance, which is what makes it this suite's *big* variance.
SHIRT = {"barcode": "RC-SHIRT", "brand": "RecountBrand", "cost": 30000}
TOLERANCE = 2_00_000  # ₹2,000, as seeded — read back from the row where it matters


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
        **{k: v for k, v in dims.items() if k != "season"},
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
        doc_number=f"RC-SEED-{spec['barcode']}",
        line_no=1,
        **dims,
    )


@pytest.fixture()
def recount_scaffold(db):
    """One store holding ten shirts, and the four people this control needs:
    the counter, a second person to recount, the one who applies, and the
    Operations Head an escalated variance ends up with."""
    entity = LegalEntity.objects.create(code="rc-ent", name="Recount Entity", pan="AAACR1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACR1234C1ZS",
        state_code="20",
        state_name="Jharkhand",
        legal_entity=entity,
    )
    store = Store.objects.create(code="R-A", name="Recount Store", gstin=gstin)
    Brand.objects.create(
        code=SHIRT["brand"].lower(),
        name=SHIRT["brand"],
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    _stock(store, gstin, SHIRT, 10)

    manager = make_role("store_manager", "Store manager (recount test)")
    counter = User.objects.create_user(
        username="rc_counter", password=TEST_PASSWORD, role=manager, scope_type=ScopeType.STORE
    )
    counter.stores.add(store)
    second = User.objects.create_user(
        username="rc_second", password=TEST_PASSWORD, role=manager, scope_type=ScopeType.STORE
    )
    second.stores.add(store)
    applier = User.objects.create_user(
        username="rc_applier",
        password=TEST_PASSWORD,
        role=make_role("owner", "Owner (recount test)"),
        scope_type=ScopeType.ALL,
    )
    ops_head = User.objects.create_user(
        username="rc_ops",
        password=TEST_PASSWORD,
        role=make_role("ho_ops", "Operations Head (recount test)"),
        scope_type=ScopeType.ALL,
    )

    VoucherSeries.objects.create(
        fy=FY, store_code="R-A", doc_type="ADJ", prefix=f"R-A/ADJ/{FY}/", next_seq=1
    )
    return {
        "store": store,
        "gstin": gstin,
        "counter": counter,
        "second": second,
        "applier": applier,
        "ops_head": ops_head,
    }


# ---------------------------------------------------------------------------
# Driving the count
# ---------------------------------------------------------------------------


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _count(scaffold, *, found: int, user=None) -> int:
    """Open a count, scan ``found`` shirts, submit. Returns the stocktake id."""
    counter = user or scaffold["counter"]
    resp = _client(counter).post(
        "/api/outbound/stocktakes", {"store": scaffold["store"].id}, format="json"
    )
    assert resp.status_code == 201, resp.data
    take = resp.data["id"]

    resp = _client(counter).post(
        f"/api/outbound/stocktakes/{take}/sessions",
        {"scope": CountScope.BRAND, "scope_value": SHIRT["brand"]},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    session = resp.data["id"]

    if found:
        resp = _client(counter).post(
            f"/api/outbound/count-sessions/{session}/scan",
            {"scans": [{"barcode": SHIRT["barcode"], "qty": found}]},
            format="json",
        )
        assert resp.status_code == 200, resp.data
    resp = _client(counter).post(
        f"/api/outbound/count-sessions/{session}/submit", {}, format="json"
    )
    assert resp.status_code == 200, resp.data
    return take


def _recount(scaffold, take, *, qty, reason=AdjustmentReason.SHRINKAGE, user=None, **extra):
    return _client(user or scaffold["second"]).post(
        f"/api/outbound/stocktakes/{take}/recount",
        {"sku_code": SHIRT["barcode"], "counted_qty": qty, "reason": reason, **extra},
        format="json",
    )


def _apply(scaffold, take, *, user=None, confirm=None):
    return _client(user or scaffold["applier"]).post(
        f"/api/outbound/stocktakes/{take}/apply", {"confirm": confirm or []}, format="json"
    )


def _variance(scaffold, take, *, user=None):
    resp = _client(user or scaffold["counter"]).get(f"/api/outbound/stocktakes/{take}/variance")
    assert resp.status_code == 200, resp.data
    return resp.data


def _shirt(variance):
    return next(line for line in variance["lines"] if line["sku_code"] == SHIRT["barcode"])


def _policy() -> ApprovalPolicy:
    return ApprovalPolicy.objects.get(kind="adjustment")


def _decide(user, approval_id, action="approve", reason=""):
    return _client(user).post(
        f"/api/approvals/{approval_id}/decide", {"action": action, "reason": reason}, format="json"
    )


def _submit_adjustment(user, adjustment_id):
    """A stock adjustment is an approve-*then*-post family: clearing the inbox
    unlocks the document, and its maker posts it."""
    return _client(user).post(
        f"/api/outbound/adjustments/{adjustment_id}/submit", {}, format="json"
    )


# ---------------------------------------------------------------------------
# The gate: above tolerance cannot post
# ---------------------------------------------------------------------------


def test_an_above_tolerance_line_cannot_post_until_it_is_recounted(recount_scaffold):
    """Ten shirts missing is ₹3,000 at stake. Nothing is written — not even a
    draft — until a second person has counted them again."""
    take = _count(recount_scaffold, found=0)

    resp = _apply(recount_scaffold, take)

    assert resp.status_code == 409, resp.data
    assert [line["sku_code"] for line in resp.data["needs_recount"]] == [SHIRT["barcode"]]
    assert StockAdjustment.objects.count() == 0
    assert not StockLedgerEntry.objects.filter(kind="adjustment").exists()


def test_a_within_tolerance_line_still_corrects_itself(recount_scaffold):
    """One ₹300 shirt short is below the tolerance, so slice 10's behaviour
    stands: no recount is asked for and the count corrects itself."""
    take = _count(recount_scaffold, found=9)

    assert _shirt(_variance(recount_scaffold, take))["needs_recount"] is False
    resp = _apply(recount_scaffold, take)

    assert resp.status_code == 201, resp.data
    assert StockAdjustment.objects.get(pk=resp.data["id"]).docstatus == DocStatus.SUBMITTED


def test_the_variance_report_says_which_lines_are_waiting_on_a_recount(recount_scaffold):
    """The screen does not work out the threshold — the server names the pieces,
    so the tolerance stays one number in one place (Rule 12)."""
    take = _count(recount_scaffold, found=0)

    variance = _variance(recount_scaffold, take)

    assert variance["awaiting_recount"] == [SHIRT["barcode"]]
    assert _shirt(variance)["needs_recount"] is True
    assert _shirt(variance)["recount"] is None


def test_retuning_the_tolerance_moves_the_gate_without_a_release(recount_scaffold):
    """Rule 12: the threshold is data. Raise it above ₹3,000 and the same count
    needs no recount at all."""
    policy = _policy()
    assert policy.tolerance_paise == TOLERANCE
    policy.tolerance_paise = 50_00_000
    policy.save(update_fields=["tolerance_paise"])
    take = _count(recount_scaffold, found=0)

    assert _shirt(_variance(recount_scaffold, take))["needs_recount"] is False
    assert _apply(recount_scaffold, take).status_code == 201


# ---------------------------------------------------------------------------
# A different person
# ---------------------------------------------------------------------------


def test_the_person_who_counted_it_may_not_recount_it(recount_scaffold):
    """The whole point of a recount is a second pair of eyes."""
    take = _count(recount_scaffold, found=0)

    refused = _recount(recount_scaffold, take, qty=0, user=recount_scaffold["counter"])

    assert refused.status_code == 403, refused.data
    assert "counted" in refused.data["error"].lower()
    assert _shirt(_variance(recount_scaffold, take))["recount"] is None


def test_a_second_person_may_recount_it(recount_scaffold):
    take = _count(recount_scaffold, found=0)

    resp = _recount(recount_scaffold, take, qty=4)

    assert resp.status_code == 200, resp.data
    assert _shirt(resp.data)["recount"]["counted_qty"] == 4
    assert _shirt(resp.data)["needs_recount"] is False


def test_no_policy_retune_can_let_the_original_counter_recount(recount_scaffold):
    """One of the actor model's four floor rules. Every column the business may
    retune is opened as wide as it goes; the refusal does not move."""
    policy = _policy()
    policy.tolerance_paise = 0
    policy.band_paise = 99_00_00_000
    policy.band_roles = ["store_manager", "ho_ops", "owner"]
    policy.escalated_roles = ["store_manager", "ho_ops", "owner"]
    policy.save()
    take = _count(recount_scaffold, found=0)

    refused = _recount(recount_scaffold, take, qty=0, user=recount_scaffold["counter"])

    assert refused.status_code == 403, refused.data


# ---------------------------------------------------------------------------
# The trail, and the reason
# ---------------------------------------------------------------------------


def test_the_recount_keeps_the_original_count_the_recount_and_the_final(recount_scaffold):
    """Three numbers survive: what the books said, what the first count found,
    and what the recount settled on — plus who did it and why."""
    take = _count(recount_scaffold, found=0)

    _recount(recount_scaffold, take, qty=4, reason=AdjustmentReason.DAMAGE)
    line = _shirt(_variance(recount_scaffold, take))

    assert line["book_qty"] == 10
    assert line["first_counted_qty"] == 0
    assert line["counted_qty"] == 4  # the recount is what the correction uses
    assert line["adj_qty"] == -6
    assert line["recount"]["counted_qty"] == 4
    assert line["recount"]["reason"] == AdjustmentReason.DAMAGE
    assert line["recount"]["recounted_by_name"] == "rc_second"


def test_a_recount_without_a_reason_is_refused(recount_scaffold):
    take = _count(recount_scaffold, found=0)

    assert _recount(recount_scaffold, take, qty=4, reason="").status_code == 400
    assert _recount(recount_scaffold, take, qty=4, reason="because").status_code == 400
    assert _shirt(_variance(recount_scaffold, take))["recount"] is None


def test_the_reason_reaches_the_correction_document(recount_scaffold):
    """A reason nobody can read afterwards is not a control. It rides the
    adjustment line the recount produced."""
    take = _count(recount_scaffold, found=0)
    _recount(recount_scaffold, take, qty=4, reason=AdjustmentReason.SHRINKAGE)

    resp = _apply(recount_scaffold, take)

    assert resp.status_code == 201, resp.data
    adjustment = StockAdjustment.objects.get(pk=resp.data["id"])
    assert adjustment.reason == AdjustmentReason.SHRINKAGE
    assert [line.reason for line in adjustment.lines.all()] == [AdjustmentReason.SHRINKAGE]


def test_the_recount_is_what_posts_not_the_first_count(recount_scaffold):
    """The first count said nothing was there; the recount found four. Six
    pieces leave the books, not ten."""
    take = _count(recount_scaffold, found=0)
    _recount(recount_scaffold, take, qty=4)
    adjustment_id = _apply(recount_scaffold, take).data["id"]
    approval = Approval.objects.get(kind="adjustment", object_id=adjustment_id)

    assert _decide(recount_scaffold["second"], approval.pk).status_code == 200
    assert _submit_adjustment(recount_scaffold["applier"], adjustment_id).status_code == 200

    adjustment = StockAdjustment.objects.get(pk=adjustment_id)
    assert adjustment.docstatus == DocStatus.SUBMITTED
    entry = StockLedgerEntry.objects.get(doc_number=adjustment.doc_number)
    assert entry.qty == -6
    on_hand = StockOnHand.objects.get(store=recount_scaffold["store"], sku_code=SHIRT["barcode"])
    assert on_hand.net_qty == 4


# ---------------------------------------------------------------------------
# The band
# ---------------------------------------------------------------------------


def test_a_recounted_variance_inside_the_band_is_the_store_managers_to_approve(recount_scaffold):
    """₹1,800 at stake, well inside the ₹25,00,000 band."""
    take = _count(recount_scaffold, found=0)
    _recount(recount_scaffold, take, qty=4)
    approval = Approval.objects.get(object_id=_apply(recount_scaffold, take).data["id"])

    assert approval.status == ApprovalStatus.PENDING
    assert approval.approver_roles == _policy().band_roles
    assert "store_manager" in approval.approver_roles
    assert _decide(recount_scaffold["second"], approval.pk).status_code == 200


def test_a_recounted_variance_above_the_band_is_the_operations_heads_alone(recount_scaffold):
    """Retune the band down to ₹1,000 and the same ₹1,800 escalates: the Store
    Manager is refused and the Operations Head decides."""
    policy = _policy()
    policy.band_paise = 1_00_000
    policy.save(update_fields=["band_paise"])
    take = _count(recount_scaffold, found=0)
    _recount(recount_scaffold, take, qty=4)
    approval = Approval.objects.get(object_id=_apply(recount_scaffold, take).data["id"])

    assert approval.approver_roles == policy.escalated_roles
    assert "store_manager" not in approval.approver_roles
    assert _decide(recount_scaffold["second"], approval.pk).status_code == 403
    assert _decide(recount_scaffold["ops_head"], approval.pk).status_code == 200


def test_it_admin_is_not_an_approver_of_a_stock_correction(recount_scaffold):
    """Named in the issue: IT Admin holds the keys, not the stock."""
    policy = _policy()

    assert "it_admin" not in policy.band_roles
    assert "it_admin" not in policy.escalated_roles


# ---------------------------------------------------------------------------
# One number
# ---------------------------------------------------------------------------


def test_the_band_value_and_the_posted_value_are_the_same_books_number(recount_scaffold):
    """The heart of #78 over #103. If the band were picked on a different number
    from the one that posts, every big variance could be routed away from the
    Operations Head silently."""
    take = _count(recount_scaffold, found=0)
    # A caller trying to price its own recount — ignored, whatever it sends.
    _recount(recount_scaffold, take, qty=4, unit_cost_paise=1, variance_paise=1)
    adjustment_id = _apply(recount_scaffold, take).data["id"]
    approval = Approval.objects.get(object_id=adjustment_id)

    books = 6 * book_unit_cost(recount_scaffold["store"].id, SHIRT["barcode"], "SS26")
    assert books == 6 * SHIRT["cost"] != 0
    assert approval.value_paise == books

    assert _decide(recount_scaffold["second"], approval.pk).status_code == 200
    assert _submit_adjustment(recount_scaffold["applier"], adjustment_id).status_code == 200
    adjustment = StockAdjustment.objects.get(pk=adjustment_id)
    assert [line.unit_cost_paise for line in adjustment.lines.all()] == [SHIRT["cost"]]
    posted = StockLedgerEntry.objects.get(doc_number=adjustment.doc_number)
    assert abs(posted.amount) == books
    gl = GLEntry.objects.filter(doc_number=adjustment.doc_number)
    assert sum(leg.amount for leg in gl) == 0
    assert {abs(leg.amount) for leg in gl} == {books}


# ---------------------------------------------------------------------------
# The floor
# ---------------------------------------------------------------------------


def test_no_policy_retune_can_let_the_maker_approve_their_own_correction(recount_scaffold):
    """The other floor rule. Self-approval is not a band: open every retunable
    column and the maker is still refused their own document.

    This test fails the moment the refusal becomes configurable.
    """
    policy = _policy()
    policy.band_paise = 99_00_00_000
    policy.band_roles = ["store_manager", "ho_ops", "owner"]
    policy.escalated_roles = ["store_manager", "ho_ops", "owner"]
    policy.save(update_fields=["band_paise", "band_roles", "escalated_roles"])
    take = _count(recount_scaffold, found=0)
    _recount(recount_scaffold, take, qty=4)
    maker = recount_scaffold["applier"]
    approval = Approval.objects.get(object_id=_apply(recount_scaffold, take, user=maker).data["id"])

    refused = _decide(maker, approval.pk)

    assert refused.status_code == 403, refused.data
    assert Approval.objects.get(pk=approval.pk).status == ApprovalStatus.PENDING
    assert not StockLedgerEntry.objects.filter(kind="adjustment").exists()


def test_the_makers_own_correction_never_reaches_their_inbox(recount_scaffold):
    """Fail-closed the other way round too: a decision that can never succeed is
    never offered."""
    take = _count(recount_scaffold, found=0)
    _recount(recount_scaffold, take, qty=4)
    maker = recount_scaffold["applier"]
    _apply(recount_scaffold, take, user=maker)

    inbox = _client(maker).get("/api/approvals/inbox")

    assert inbox.status_code == 200, inbox.data
    assert [row for row in inbox.data if row["kind"] == "adjustment"] == []
