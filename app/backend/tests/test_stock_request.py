"""The pull side of a transfer — a store's ask, gated separately from the move
it pre-fills (#74).

Two gates, not one (Anand's ruling of 26 July): approving a stock request
approves the *ask* — the Operations Head still gates the transfer it pre-fills
before anything dispatches (#137, already covered by
``test_transfer_approval_gate.py``). This suite covers the request's own life:

- **API seam (primary)**: raise → lands in the asking store's inbox (the route
  added by #172 starts with that store's own manager; the chain itself is
  covered by ``test_approval_routes.py``) →
  unapproved requests refuse to fulfil → approved ones pre-fill a draft
  transfer that still needs its own gate → partial fulfilment and an explicit
  close read back as "partly fulfilled" → full receipt closes automatically →
  a decline carries its reason.
- **Scope seam**: the cross-location search shows quantity and identity
  everywhere, and cost/landed value/margin only for the caller's own store.
"""

from __future__ import annotations

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalStatus
from core.documents import DocStatus, VoucherSeries
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import StockRequest, StoreTransfer
from stockledger.models import StockLedgerEntry, StockOnHand

FY = "26-27"


@pytest.fixture()
def rig(db):
    """A warehouse (the fulfilling store), two stores, and the people around
    them: ``requester`` (store A, raises the ask), ``fulfiller`` (warehouse,
    answers it), ``ops`` (Operations Head, decides both gates), ``owner``.
    """
    entity = LegalEntity.objects.create(code="sr-ent", name="Request Entity", pan="AAACR1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACR1234C1ZS", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    warehouse = Store.objects.create(
        code="SR-WH", name="Request Warehouse", gstin=gstin, store_type="warehouse"
    )
    store_a = Store.objects.create(code="SR-A", name="Request Store A", gstin=gstin)
    store_b = Store.objects.create(code="SR-B", name="Request Store B", gstin=gstin)

    Brand.objects.create(
        code="sr-br",
        name="RequestBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    def _user(username, role_code, scope=ScopeType.ALL, stores=()):
        u = User.objects.create_user(
            username=username,
            password=TEST_PASSWORD,
            role=make_role(role_code),
            entity=entity,
            scope_type=scope,
        )
        for s in stores:
            u.stores.add(s)
        return u

    requester = _user("sr_requester", "store_manager", scope=ScopeType.STORE, stores=[store_a])
    fulfiller = _user("sr_fulfiller", "warehouse", scope=ScopeType.STORE, stores=[warehouse])
    ops = _user("sr_ops", "ho_ops")
    owner = _user("sr_owner", "owner")

    for barcode, design, qty, unit_cost in [("SR001", "Shirt", 20, 45000)]:
        sku = Sku.objects.create(
            barcode=barcode,
            design=design,
            color="Blue",
            size="M",
            brand="RequestBrand",
            item="shirt",
            hsn="6205",
            mrp_paise=99900,
        )
        Cohort.objects.create(
            sku=sku, barcode=barcode, season="SS26", unit_cost_paise=unit_cost, mrp_paise=99900
        )
        dims = dict(
            sku_code=barcode,
            design=design,
            color="Blue",
            size="M",
            brand="RequestBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
        )
        for store in (warehouse, store_b):
            StockOnHand.objects.create(
                store=store, gstin=gstin, net_qty=qty, net_value_paise=qty * unit_cost, **dims
            )
            StockLedgerEntry.objects.create(
                store=store,
                gstin=gstin,
                qty=qty,
                amount=qty * unit_cost,
                kind="pt_inward",
                doc_number=f"SR-SEED-{store.code}",
                line_no=1,
                **dims,
            )

    for code, doc_type in [
        ("SR-WH", "STO"),
        ("SR-A", "STO"),
        ("SR-A", "SRQ"),
        ("SR-B", "SRQ"),
    ]:
        VoucherSeries.objects.create(
            fy=FY, store_code=code, doc_type=doc_type, prefix=f"{code}/{doc_type}/{FY}/", next_seq=1
        )

    return {
        "warehouse": warehouse,
        "store_a": store_a,
        "store_b": store_b,
        "requester": requester,
        "fulfiller": fulfiller,
        "ops": ops,
        "owner": owner,
    }


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _raise(g, qty=10, requesting_store=None, fulfilling_store=None, **extra) -> dict:
    resp = _client(g["requester"]).post(
        "/api/outbound/stock-requests",
        {
            "requesting_store": (requesting_store or g["store_a"]).id,
            "fulfilling_store": (fulfilling_store or g["warehouse"]).id,
            "lines": [
                {
                    "sku_code": "SR001",
                    "design": "Shirt",
                    "color": "Blue",
                    "size": "M",
                    "brand": "RequestBrand",
                    "season": "SS26",
                    "item": "shirt",
                    "hsn": "6205",
                    "qty": qty,
                }
            ],
            **extra,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data


def _decide(kind, object_id, actor, action="approve", reason=""):
    approval = Approval.objects.get(kind=kind, object_id=object_id, status="pending")
    return _client(actor).post(
        f"/api/approvals/{approval.pk}/decide",
        {"action": action, "reason": reason},
        format="json",
    )


def _fulfil(g, request_id, lines, actor=None):
    return _client(actor or g["fulfiller"]).post(
        f"/api/outbound/stock-requests/{request_id}/fulfil",
        {"lines": lines},
        format="json",
    )


def _line_id(request_data, sku="SR001"):
    return next(line["id"] for line in request_data["lines"] if line["sku_code"] == sku)


# ---------------------------------------------------------------------------
# Raise → inbox → the fulfil gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_request_is_born_waiting_in_the_asking_stores_inbox(rig):
    """The ask hangs off the store that raised it, not the one holding the stock.

    It hung off the *fulfilling* store until D10 (#172) put a route in front of
    it: step 1 is the asking store's own manager, step 2 the Operations Head,
    and the holding store's manager is a phone call rather than a gate. So the
    row has to be visible where step 1's approver actually is. Nothing is taken
    from the holding store — no store role was ever on this family's approver
    list — and what the ask is *worth* is still priced from their books, which
    are the only ones holding the pieces.
    """
    g = rig
    data = _raise(g)

    assert data["status"] == "pending_approval"
    assert data["approval"]["status"] == ApprovalStatus.PENDING
    assert data["approval"]["kind"] == "stock_request"
    assert data["approval"]["title"].startswith("From SR-WH")

    approval = Approval.objects.get(kind="stock_request", object_id=data["id"])
    assert approval.store_id == g["store_a"].id
    # Priced from the warehouse's books: 10 pieces at ₹450 each.
    assert approval.value_paise == 10 * 45000


@pytest.mark.django_db(transaction=True)
def test_an_unapproved_request_cannot_be_fulfilled(rig):
    g = rig
    data = _raise(g)

    resp = _fulfil(g, data["id"], [{"line_id": _line_id(data), "qty": 5}])
    assert resp.status_code == 400
    assert "approv" in str(resp.data).lower()
    assert not StoreTransfer.objects.filter(fulfils_request_id=data["id"]).exists()

    sr = StockRequest.objects.get(pk=data["id"])
    assert sr.docstatus == DocStatus.DRAFT
    assert not sr.doc_number


@pytest.mark.django_db(transaction=True)
def test_an_approved_request_prefills_a_transfer_that_still_needs_its_own_gate(rig):
    """Two gates, not one: approving the ask does not approve the move."""
    g = rig
    data = _raise(g, qty=10)
    assert _decide("stock_request", data["id"], g["ops"]).status_code == 200

    resp = _fulfil(g, data["id"], [{"line_id": _line_id(data), "qty": 6}])
    assert resp.status_code == 201, resp.data
    transfer = resp.data
    assert transfer["source_store"] == g["warehouse"].id
    assert transfer["destination_store"] == g["store_a"].id
    assert transfer["docstatus"] == DocStatus.DRAFT
    # The default rig asks a warehouse, not another store — the pre-filled
    # transfer must read as a store split, not an inter-store move.
    assert transfer["transfer_type"] == "store_split"
    # Pre-filled, not dispatched: the plan line carries the fulfiller's qty.
    assert transfer["lines"][0]["qty_planned"] == 6
    assert transfer["lines"][0]["qty_dispatched"] == 0

    # The request now carries its own number, minted at the first fulfilment.
    sr = StockRequest.objects.get(pk=data["id"])
    assert sr.doc_number

    # The transfer's own gate is untouched — dispatch refuses until the
    # Operations Head clears it, same as any other transfer (#137).
    dispatch = _client(g["fulfiller"]).post(
        f"/api/outbound/transfers/{transfer['id']}/dispatch",
        {"scans": [{"barcode": "SR001", "qty": 6}]},
        format="json",
    )
    assert dispatch.status_code == 400
    assert "approv" in str(dispatch.data).lower()


@pytest.mark.django_db(transaction=True)
def test_fulfilling_more_than_remains_is_refused(rig):
    g = rig
    data = _raise(g, qty=5)
    _decide("stock_request", data["id"], g["ops"])

    resp = _fulfil(g, data["id"], [{"line_id": _line_id(data), "qty": 6}])
    assert resp.status_code == 400
    assert "5" in str(resp.data)


# ---------------------------------------------------------------------------
# Honest status: being fulfilled → partly fulfilled / closed
# ---------------------------------------------------------------------------


def _dispatch_and_receive(g, transfer_id, qty):
    _decide("transfer", transfer_id, g["ops"])
    d = _client(g["fulfiller"]).post(
        f"/api/outbound/transfers/{transfer_id}/dispatch",
        {"scans": [{"barcode": "SR001", "qty": qty}]},
        format="json",
    )
    assert d.status_code == 200, d.data
    r = _client(g["requester"]).post(
        f"/api/outbound/transfers/{transfer_id}/receive",
        {"scans": [{"barcode": "SR001", "qty": qty}]},
        format="json",
    )
    assert r.status_code == 200, r.data
    return r.data


@pytest.mark.django_db(transaction=True)
def test_partial_receive_then_close_reads_as_partly_fulfilled(rig):
    g = rig
    data = _raise(g, qty=10)
    _decide("stock_request", data["id"], g["ops"])
    transfer = _fulfil(g, data["id"], [{"line_id": _line_id(data), "qty": 6}]).data

    mid = _client(g["requester"]).get(f"/api/outbound/stock-requests/{data['id']}").data
    assert mid["status"] == "being_fulfilled"

    _dispatch_and_receive(g, transfer["id"], 6)

    still_open = _client(g["requester"]).get(f"/api/outbound/stock-requests/{data['id']}").data
    assert still_open["status"] == "being_fulfilled"  # 6 of 10, no closure yet

    close = _client(g["fulfiller"]).post(
        f"/api/outbound/stock-requests/{data['id']}/close",
        {"note": "Rest is out of stock this season."},
        format="json",
    )
    assert close.status_code == 200, close.data
    assert close.data["status"] == "partly_fulfilled"
    assert close.data["lines"][0]["qty_fulfilled"] == 6

    # The fulfiller said no more is coming — a later fulfil attempt must not
    # quietly reopen what closing settled.
    again = _fulfil(g, data["id"], [{"line_id": _line_id(data), "qty": 1}])
    assert again.status_code == 400
    assert "closed" in str(again.data).lower()


@pytest.mark.django_db(transaction=True)
def test_a_duplicated_line_id_cannot_double_commit_past_what_remains(rig):
    """One fulfil call sending the same line twice must not let the two
    entries each check against the same "remaining" figure and together
    commit more than the request actually has left (#74)."""
    g = rig
    data = _raise(g, qty=6)
    _decide("stock_request", data["id"], g["ops"])
    line_id = _line_id(data)

    resp = _fulfil(
        g,
        data["id"],
        [{"line_id": line_id, "qty": 5}, {"line_id": line_id, "qty": 5}],
    )
    assert resp.status_code == 400
    # The second entry sees only 1 left (6 − 5 already committed this call) —
    # not 6, which is what a stale-snapshot bug would have allowed through.
    assert "at most 1 left" in str(resp.data)
    assert not StoreTransfer.objects.filter(fulfils_request_id=data["id"]).exists()


@pytest.mark.django_db(transaction=True)
def test_a_second_pass_cannot_over_commit_before_the_first_is_received(rig):
    """The first fulfil's transfer is still an unreceived draft — its promise
    must count against what a second, separate pass may still claim, or two
    passes together could commit more than the request ever asked for (#74)."""
    g = rig
    data = _raise(g, qty=6)
    _decide("stock_request", data["id"], g["ops"])
    line_id = _line_id(data)

    first = _fulfil(g, data["id"], [{"line_id": line_id, "qty": 5}])
    assert first.status_code == 201, first.data

    second = _fulfil(g, data["id"], [{"line_id": line_id, "qty": 5}])
    assert second.status_code == 400
    assert "at most 1 left" in str(second.data)


@pytest.mark.django_db(transaction=True)
def test_full_receive_closes_automatically(rig):
    g = rig
    data = _raise(g, qty=6)
    _decide("stock_request", data["id"], g["ops"])
    transfer = _fulfil(g, data["id"], [{"line_id": _line_id(data), "qty": 6}]).data

    _dispatch_and_receive(g, transfer["id"], 6)

    done = _client(g["requester"]).get(f"/api/outbound/stock-requests/{data['id']}").data
    assert done["status"] == "closed"


@pytest.mark.django_db(transaction=True)
def test_a_declined_request_carries_its_reason_and_cannot_be_fulfilled(rig):
    g = rig
    data = _raise(g)

    resp = _decide(
        "stock_request", data["id"], g["ops"], "reject", "Warehouse needs this for EOSS."
    )
    assert resp.status_code == 200

    read = _client(g["requester"]).get(f"/api/outbound/stock-requests/{data['id']}").data
    assert read["status"] == "declined"
    assert read["decline_reason"] == "Warehouse needs this for EOSS."

    fulfil = _fulfil(g, data["id"], [{"line_id": _line_id(read), "qty": 1}])
    assert fulfil.status_code == 400


# ---------------------------------------------------------------------------
# Scope: the cross-location search hides cost outside the caller's own store
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_cross_location_search_shows_stock_everywhere_but_cost_only_at_home(rig):
    g = rig
    resp = _client(g["requester"]).get("/api/outbound/stock-search?q=SR001")
    assert resp.status_code == 200
    rows = {row["store_code"]: row for row in resp.data["rows"]}

    # Identity + quantity, at a store the caller does not belong to.
    assert rows["SR-B"]["qty"] == 20
    assert rows["SR-B"]["sku_code"] == "SR001"
    assert rows["SR-B"]["is_own"] is False
    for money_field in ("unit_cost_paise", "landed_value_paise", "margin_paise"):
        assert money_field not in rows["SR-B"]

    # SR-A itself holds no stock in this fixture, so prove ownership the other
    # way round: the warehouse row is likewise foreign to a store-scoped caller.
    assert "unit_cost_paise" not in rows["SR-WH"]

    # The fulfiller, standing in the warehouse, sees its own cost.
    as_fulfiller = _client(g["fulfiller"]).get("/api/outbound/stock-search?q=SR001").data
    wh_row = next(r for r in as_fulfiller["rows"] if r["store_code"] == "SR-WH")
    assert wh_row["is_own"] is True
    assert wh_row["unit_cost_paise"] == 45000
    assert wh_row["landed_value_paise"] == 20 * 45000
    b_row = next(r for r in as_fulfiller["rows"] if r["store_code"] == "SR-B")
    assert "unit_cost_paise" not in b_row
