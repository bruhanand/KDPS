"""Outbound slice 4 — receive exceptions + the gaps list (#71).

Seams (agreed in the PRD, issue #67):
- **API seam**: receive with short / extra / damaged payloads → structured
  exceptions on the receipt, the shortfall note stored, an open gap; the gaps
  list; raise → approve → post a closure.
- **Stock-ledger seam**: where each exception's pieces end up. Damaged land in
  *quarantine* at the destination, never in free-to-sell. Short pieces stay in
  the in-transit bucket until the closure drains it, and the closure drains it
  differently per reason. Conservation holds throughout — the only reason a
  piece may leave the total is a lost-in-transit closure, which says so in the GL.

Rulings exercised here:
- Damaged pieces count as **received** (they arrived), so they leave in-transit.
- An extra the books can price is accepted into stock as a surplus; one they
  cannot is recorded and deliberately NOT posted (#103 — never at zero).
- The way out of a shortfall is the closure, not a second receive.
- "Found later" posts the resolving entries directly (the #80 sub-decision).
- The receiving store can never close its own gap, at either end of the decision.
"""

from __future__ import annotations

import pytest
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.models import Approval, ApprovalStatus
from core.documents import DocStatus, VoucherSeries
from core.gl import GLAccount, GLEntry
from masters.models import Brand, Cohort, Gstin, LegalEntity, Sku, Store
from outbound.models import (
    StoreTransfer,
    StoreTransferLine,
    TransferGapClosure,
    TransferReceipt,
)
from stockledger.models import InTransitStock, QuarantineStock, StockLedgerEntry, StockOnHand

FY = "26-27"


@pytest.fixture()
def gap_scaffold(db):
    """Warehouse + destination store, seeded stock, and the four people this
    slice needs: the receiving store's manager, the HO maker, the HO checker,
    and a second store's manager (who is *not* the receiver)."""
    entity = LegalEntity.objects.create(code="gap-ent", name="Gap Entity", pan="AAACG1234C")
    gstin = Gstin.objects.create(
        gstin="20AAACG1234C1ZS", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    warehouse = Store.objects.create(
        code="GP-WH", name="Gap Warehouse", gstin=gstin, store_type="warehouse"
    )
    store = Store.objects.create(code="GP-A", name="Gap Store A", gstin=gstin)

    Brand.objects.create(
        code="gap-br",
        name="GapBrand",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )

    # Roles carry the matrix's access (#85/#94), so a gate here answers the way
    # the live install answers. The checker is the Owner rather than Accounts:
    # the sheet gives Accounts only *view* on transfers, so it cannot clear a
    # gap closure — the seniority for that comes from ``transfer: approve``.
    ho = make_role("ho_ops", "HO Ops (gap test)")
    owner = make_role("owner", "Owner (gap test)")
    manager = make_role("store_manager", "Store manager (gap test)")

    def _user(username, role, scope=ScopeType.ALL, stores=()):
        u = User.objects.create_user(
            username=username, password="Test@123", role=role, entity=entity, scope_type=scope
        )
        for s in stores:
            u.stores.add(s)
        return u

    maker = _user("gap_maker", ho)
    checker = _user("gap_checker", owner)
    receiver = _user("gap_receiver", manager, ScopeType.STORE, [store])
    # A senior whose entitlement happens to include the receiving store — the
    # person the self-closure rule must still refuse.
    ho_at_store = _user("gap_ho_at_store", ho, ScopeType.STORE, [store, warehouse])

    for barcode, design, color, size, qty, unit_cost in [
        ("GB001", "Shirt", "Blue", "M", 10, 45000),
        ("GB002", "Jeans", "Black", "L", 8, 30000),
    ]:
        sku = Sku.objects.create(
            barcode=barcode,
            design=design,
            color=color,
            size=size,
            brand="GapBrand",
            item="shirt",
            hsn="6205",
            mrp_paise=99900,
        )
        Cohort.objects.create(
            sku=sku, barcode=barcode, season="SS26", unit_cost_paise=unit_cost, mrp_paise=99900
        )
        StockOnHand.objects.create(
            store=warehouse,
            gstin=gstin,
            sku_code=barcode,
            design=design,
            color=color,
            size=size,
            brand="GapBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
            net_qty=qty,
            net_value_paise=qty * unit_cost,
        )
        StockLedgerEntry.objects.create(
            store=warehouse,
            gstin=gstin,
            sku_code=barcode,
            design=design,
            color=color,
            size=size,
            brand="GapBrand",
            season="SS26",
            item="shirt",
            hsn="6205",
            qty=qty,
            amount=qty * unit_cost,
            kind="pt_inward",
            doc_number="GAP-SEED",
            line_no=1,
        )

    # A barcode the destination will see arrive without it ever being sent: one
    # the books can price (a cohort exists), one they cannot, and one whose brand
    # is not in the masters at all.
    priced = Sku.objects.create(
        barcode="GX001", design="Kurta", color="Red", size="S", brand="GapBrand", hsn="6205"
    )
    Cohort.objects.create(
        sku=priced, barcode="GX001", season="SS26", unit_cost_paise=22000, mrp_paise=59900
    )
    Sku.objects.create(barcode="GX999", design="Mystery", brand="GapBrand")
    stranger = Sku.objects.create(barcode="GX777", design="Stranger", brand="NoSuchBrand")
    Cohort.objects.create(
        sku=stranger, barcode="GX777", season="SS26", unit_cost_paise=15000, mrp_paise=39900
    )

    # A brand-owned (SOR) line, dispatched alongside the owned one, so the value
    # postings can be checked for the model-blind-liability trap.
    Brand.objects.create(
        code="gap-sor",
        name="GapSorBrand",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    sor_sku = Sku.objects.create(
        barcode="GS001", design="Blazer", color="Grey", size="40", brand="GapSorBrand", hsn="6203"
    )
    Cohort.objects.create(
        sku=sor_sku, barcode="GS001", season="SS26", unit_cost_paise=60000, mrp_paise=249900
    )
    StockOnHand.objects.create(
        store=warehouse,
        gstin=gstin,
        sku_code="GS001",
        design="Blazer",
        color="Grey",
        size="40",
        brand="GapSorBrand",
        season="SS26",
        hsn="6203",
        net_qty=5,
        net_value_paise=5 * 60000,
    )
    StockLedgerEntry.objects.create(
        store=warehouse,
        gstin=gstin,
        sku_code="GS001",
        design="Blazer",
        color="Grey",
        size="40",
        brand="GapSorBrand",
        season="SS26",
        hsn="6203",
        qty=5,
        amount=5 * 60000,
        kind="pt_inward",
        doc_number="GAP-SEED",
        line_no=2,
    )

    for code in ["GP-WH", "GP-A"]:
        for doc_type in ["STO", "GAP"]:
            VoucherSeries.objects.create(
                fy=FY, store_code=code, doc_type=doc_type, prefix=f"{code}/{doc_type}/{FY}/"
            )

    return {
        "gstin": gstin,
        "warehouse": warehouse,
        "store": store,
        "maker": maker,
        "checker": checker,
        "receiver": receiver,
        "ho_at_store": ho_at_store,
    }


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _dispatched(s, plan=(("GB001", 4),)) -> StoreTransfer:
    """A submitted warehouse→store transfer with everything scanned out."""
    transfer = StoreTransfer.objects.create(
        source_store=s["warehouse"],
        destination_store=s["store"],
        transfer_type="store_split",
        created_by=s["maker"],
    )
    for barcode, qty in plan:
        StoreTransferLine.objects.create(transfer=transfer, sku_code=barcode, qty_planned=qty)
    resp = _client(s["maker"]).post(
        f"/api/outbound/transfers/{transfer.pk}/dispatch",
        {"scans": [{"barcode": b, "qty": q} for b, q in plan]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    transfer.refresh_from_db()
    return transfer


def _total_qty(barcode: str) -> int:
    """Conservation probe: at a location, in quarantine, or in transit."""
    return (
        sum(StockOnHand.objects.filter(sku_code=barcode).values_list("net_qty", flat=True))
        + sum(QuarantineStock.objects.filter(sku_code=barcode).values_list("qty", flat=True))
        + sum(InTransitStock.objects.filter(sku_code=barcode).values_list("qty", flat=True))
    )


def _exceptions(transfer: StoreTransfer) -> dict[str, list]:
    """The receipt's exceptions, grouped by kind."""
    grouped: dict[str, list] = {}
    for e in TransferReceipt.objects.get(transfer=transfer).exceptions.all():
        grouped.setdefault(e.kind, []).append(e)
    return grouped


# ---------------------------------------------------------------------------
# Short
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_short_receive_records_the_exception_and_keeps_the_pieces_in_transit(gap_scaffold):
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 4),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "GB001", "qty": 3}], "notes": "One piece missing from carton 2."},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["gap_state"] == "gap"
    assert resp.data["qty_in_transit"] == 1

    receipt = TransferReceipt.objects.get(transfer=transfer)
    assert receipt.receipt_status == "shortfall"
    # The note the old payload dropped now reaches the server and is stored.
    assert receipt.shortfall_notes == "One piece missing from carton 2."
    assert resp.data["receipt"]["shortfall_notes"] == "One piece missing from carton 2."

    short = _exceptions(transfer)["short"]
    assert len(short) == 1
    assert (short[0].sku_code, short[0].qty) == ("GB001", 1)
    assert short[0].unit_cost_paise == 45000

    # The missing piece is still in the bucket, at the sender's answerability.
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 1
    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 3
    assert _total_qty("GB001") == 10


@pytest.mark.django_db(transaction=True)
def test_a_shortfall_cannot_be_fixed_by_receiving_twice(gap_scaffold):
    """The way out of a gap is the closure — #80's stranded-stock guard stays,
    and now says what to do instead."""
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 4),))
    c = _client(s["receiver"])
    c.post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "GB001", "qty": 3}]},
        format="json",
    )

    resp = c.post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "GB001", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "gaps list" in str(resp.data)
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 1


# ---------------------------------------------------------------------------
# Damaged on arrival
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_damaged_on_arrival_lands_in_quarantine_not_sellable_stock(gap_scaffold):
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 4),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {
            "scans": [{"barcode": "GB001", "qty": 3}],
            "damaged": [{"barcode": "GB001", "qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data
    # All four arrived, so nothing is short and nothing is left in transit.
    assert resp.data["gap_state"] == "received"
    assert resp.data["qty_in_transit"] == 0
    assert TransferReceipt.objects.get(transfer=transfer).receipt_status == "complete"

    # Three sellable at the store, one in quarantine at the store.
    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 3
    quarantine = QuarantineStock.objects.get(store=s["store"], sku_code="GB001")
    assert quarantine.qty == 1
    assert quarantine.value_paise == 45000
    # …written as a quarantine leg, never as free-to-sell stock.
    assert (
        StockLedgerEntry.objects.get(doc_number=transfer.doc_number, kind="quarantine_in").qty == 1
    )
    # The whole carton left the bucket: four pieces, one drain leg.
    assert not InTransitStock.objects.filter(transfer_doc_number=transfer.doc_number).exists()
    assert (
        StockLedgerEntry.objects.get(doc_number=transfer.doc_number, kind="transit_out").qty == -4
    )

    damaged = _exceptions(transfer)["damaged"]
    assert (damaged[0].sku_code, damaged[0].qty) == ("GB001", 1)
    assert _total_qty("GB001") == 10


@pytest.mark.django_db(transaction=True)
def test_damaged_and_short_together(gap_scaffold):
    """Sent 4, two arrived intact, one broken, one never turned up."""
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 4),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {
            "scans": [{"barcode": "GB001", "qty": 2}],
            "damaged": [{"barcode": "GB001", "qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["gap_state"] == "gap"

    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 2
    assert QuarantineStock.objects.get(store=s["store"], sku_code="GB001").qty == 1
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 1

    exceptions = _exceptions(transfer)
    assert exceptions["short"][0].qty == 1
    assert exceptions["damaged"][0].qty == 1
    assert _total_qty("GB001") == 10


@pytest.mark.django_db(transaction=True)
def test_good_plus_damaged_may_not_exceed_what_was_sent(gap_scaffold):
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 2),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {
            "scans": [{"barcode": "GB001", "qty": 2}],
            "damaged": [{"barcode": "GB001", "qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "more than was sent" in str(resp.data)
    assert not TransferReceipt.objects.filter(transfer=transfer).exists()
    assert not QuarantineStock.objects.exists()


# ---------------------------------------------------------------------------
# Extra / wrong item
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_priceable_extra_is_accepted_in_with_a_flag(gap_scaffold):
    """A piece that arrived without being sent is real stock appearing with no
    document behind it — so it posts as a surplus, flagged, never swallowed."""
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 2),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {
            "scans": [{"barcode": "GB001", "qty": 2}],
            "extras": [{"barcode": "GX001", "qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data

    extra = _exceptions(transfer)["extra"][0]
    assert (extra.sku_code, extra.qty, extra.unit_cost_paise) == ("GX001", 1, 22000)
    assert "accepted into stock" in extra.note
    # In stock at the destination, at the book cost — dims from the item master.
    on_hand = StockOnHand.objects.get(store=s["store"], sku_code="GX001")
    assert on_hand.net_qty == 1
    assert on_hand.net_value_paise == 22000
    assert on_hand.design == "Kurta"
    # …and balanced on the value side, like a stocktake surplus.
    legs = {
        e.account: e.amount
        for e in GLEntry.objects.filter(doc_number=transfer.doc_number, doc_type="STO")
    }
    assert legs == {GLAccount.INVENTORY: 22000, GLAccount.SUSPENSE: -22000}


@pytest.mark.django_db(transaction=True)
def test_an_unpriceable_extra_is_recorded_but_never_posted_at_zero(gap_scaffold):
    """The books cannot price a piece they never bought, and zero is the one
    value a stock movement may not fall back to (#103) — so the extra is on the
    record, with a note saying what has to happen, and no ledger row."""
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 2),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {
            "scans": [{"barcode": "GB001", "qty": 2}],
            "extras": [{"barcode": "GX999", "qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data

    extra = _exceptions(transfer)["extra"][0]
    assert (extra.sku_code, extra.qty, extra.unit_cost_paise) == ("GX999", 1, 0)
    assert "cannot price" in extra.note
    assert not StockOnHand.objects.filter(sku_code="GX999").exists()
    assert not StockLedgerEntry.objects.filter(sku_code="GX999").exists()
    assert not GLEntry.objects.filter(doc_number=transfer.doc_number).exists()


@pytest.mark.django_db(transaction=True)
def test_a_brand_owned_extra_never_lands_in_our_inventory(gap_scaffold):
    """SOR stock is counted by quantity but its value stays off our books, so an
    extra belonging to a brand posts the memo pair — and never a payable, since
    nothing has been sold."""
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 1),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {
            "scans": [{"barcode": "GB001", "qty": 1}],
            "extras": [{"barcode": "GS001", "qty": 2}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data

    # Counted at the destination…
    assert StockOnHand.objects.get(store=s["store"], sku_code="GS001").net_qty == 2
    # …behind the SOR memo pair, with INVENTORY untouched.
    legs = {e.account: e.amount for e in GLEntry.objects.filter(doc_number=transfer.doc_number)}
    assert legs == {GLAccount.SOR_STOCK: 120000, GLAccount.SOR_CONTRA: -120000}
    assert not GLEntry.objects.filter(account=GLAccount.VENDOR_PAYABLE).exists()


@pytest.mark.django_db(transaction=True)
def test_an_extra_whose_brand_is_unknown_is_recorded_but_not_posted(gap_scaffold):
    """The books can price it but cannot say whose it is — and "ours" is not a
    safe default for an unknown brand, so it stays out of stock with a note."""
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 1),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {
            "scans": [{"barcode": "GB001", "qty": 1}],
            "extras": [{"barcode": "GX777", "qty": 1}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data

    extra = _exceptions(transfer)["extra"][0]
    assert (extra.sku_code, extra.unit_cost_paise) == ("GX777", 15000)
    assert "not in the masters" in extra.note
    assert not StockOnHand.objects.filter(sku_code="GX777").exists()
    assert not GLEntry.objects.filter(doc_number=transfer.doc_number).exists()


@pytest.mark.django_db(transaction=True)
def test_a_piece_on_the_transfer_is_not_an_extra(gap_scaffold):
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 2),))

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"extras": [{"barcode": "GB001", "qty": 1}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "not an extra" in str(resp.data)


@pytest.mark.django_db(transaction=True)
def test_receive_with_nothing_scanned_anywhere_is_rejected(gap_scaffold):
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 2),))
    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive", {}, format="json"
    )
    assert resp.status_code == 400
    assert not TransferReceipt.objects.filter(transfer=transfer).exists()


# ---------------------------------------------------------------------------
# The gaps list
# ---------------------------------------------------------------------------


def _received_short(s, plan=(("GB001", 4),), scanned=3) -> StoreTransfer:
    transfer = _dispatched(s, plan=plan)
    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": plan[0][0], "qty": scanned}], "notes": "Carton opened in transit."},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    transfer.refresh_from_db()
    return transfer


@pytest.mark.django_db(transaction=True)
def test_the_gaps_list_shows_open_gaps_only(gap_scaffold):
    s = gap_scaffold
    gapped = _received_short(s, plan=(("GB001", 4),), scanned=3)
    # A fully-received transfer is not a gap…
    clean = _dispatched(s, plan=(("GB002", 2),))
    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{clean.pk}/receive",
        {"scans": [{"barcode": "GB002", "qty": 2}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    # …and neither is one still on the road.
    on_the_road = _dispatched(s, plan=(("GB002", 1),))

    resp = _client(s["maker"]).get("/api/outbound/transfers/gaps")
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.data]
    assert ids == [gapped.pk]
    assert clean.pk not in ids and on_the_road.pk not in ids
    row = resp.data[0]
    assert row["gap_state"] == "gap"
    assert row["qty_in_transit"] == 1
    assert row["receipt"]["shortfall_notes"] == "Carton opened in transit."
    assert [e["kind"] for e in row["receipt"]["exceptions"]] == ["short"]


@pytest.mark.django_db(transaction=True)
def test_a_closed_gap_leaves_the_list_but_an_unapproved_closure_does_not(gap_scaffold):
    """Raising a closure is not closing it — the gap stays on somebody's screen
    until the resolving entries have actually posted."""
    s = gap_scaffold
    transfer = _received_short(s)
    c = _client(s["maker"])

    closure_id = _raise_closure(s, transfer, "found_later")
    assert [row["id"] for row in c.get("/api/outbound/transfers/gaps").data] == [transfer.pk]

    _approve(s, closure_id)
    assert [row["id"] for row in c.get("/api/outbound/transfers/gaps").data] == [transfer.pk]

    assert c.post(f"/api/outbound/gap-closures/{closure_id}/submit").status_code == 200
    assert c.get("/api/outbound/transfers/gaps").data == []


@pytest.mark.django_db(transaction=True)
def test_the_receiving_store_does_not_find_its_own_gap_on_the_list(gap_scaffold):
    """The list is scoped on the sender, who is answerable for the pieces."""
    s = gap_scaffold
    _received_short(s)
    resp = _client(s["receiver"]).get("/api/outbound/transfers/gaps")
    assert resp.status_code == 200
    assert resp.data == []


# ---------------------------------------------------------------------------
# Gap closure — senior-gated, reason-coded, resolving entries
# ---------------------------------------------------------------------------


def _raise_closure(s, transfer, reason, asker=None) -> int:
    resp = _client(asker or s["maker"]).post(
        f"/api/outbound/transfers/{transfer.pk}/gap-closure",
        {"reason": reason, "note": "Driver called."},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data["id"]


def _approve(s, closure_id, actor=None) -> None:
    closure = TransferGapClosure.objects.get(pk=closure_id)
    approval = Approval.objects.filter(
        object_id=closure.pk, kind="gap_closure", status=ApprovalStatus.PENDING
    ).get()
    resp = _client(actor or s["checker"]).post(
        f"/api/approvals/{approval.pk}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 200, resp.data


@pytest.mark.django_db(transaction=True)
def test_raising_a_closure_asks_a_senior_and_reads_the_gap_off_the_transfer(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s, plan=(("GB001", 4),), scanned=3)

    closure_id = _raise_closure(s, transfer, "found_later")
    closure = TransferGapClosure.objects.get(pk=closure_id)
    assert closure.docstatus == DocStatus.DRAFT
    # Lines come from the in-transit remainder at the frozen dispatch cost —
    # the asker never states how much went missing.
    line = closure.lines.get()
    assert (line.sku_code, line.qty, line.unit_cost_paise) == ("GB001", 1, 45000)

    approval = Approval.objects.get(object_id=closure.pk, kind="gap_closure")
    assert approval.status == ApprovalStatus.PENDING
    assert approval.made_by_id == s["maker"].id
    # The inbox row names the transfer — a bare store code would be useless here.
    assert transfer.doc_number in approval.title
    # Nothing has moved yet.
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 1


@pytest.mark.django_db(transaction=True)
def test_a_closure_cannot_post_before_a_second_person_approves_it(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s)
    closure_id = _raise_closure(s, transfer, "lost_in_transit")

    resp = _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 400
    assert "Waiting for approval" in str(resp.data)
    assert TransferGapClosure.objects.get(pk=closure_id).docstatus == DocStatus.DRAFT
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 1


@pytest.mark.django_db(transaction=True)
def test_found_later_posts_the_pieces_to_the_destination(gap_scaffold):
    """The #80 sub-decision, settled: closure posts the resolving entries
    directly — there is no second scan-receive."""
    s = gap_scaffold
    transfer = _received_short(s, plan=(("GB001", 4),), scanned=3)
    closure_id = _raise_closure(s, transfer, "found_later")
    _approve(s, closure_id)

    resp = _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 200, resp.data
    closure = TransferGapClosure.objects.get(pk=closure_id)
    assert closure.docstatus == DocStatus.SUBMITTED
    assert closure.doc_number and "/GAP/" in closure.doc_number
    assert closure.approved_by_id == s["checker"].id

    # The bucket is empty and the piece is at the destination.
    assert not InTransitStock.objects.filter(transfer_doc_number=transfer.doc_number).exists()
    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 4
    landed = StockLedgerEntry.objects.get(doc_number=closure.doc_number)
    assert (landed.kind, landed.qty, landed.store_id) == ("transfer_in", 1, s["store"].id)
    # The drain leg rides the TRANSFER's number — that is the bucket's key.
    assert StockLedgerEntry.objects.filter(
        doc_number=transfer.doc_number, kind="transit_out", qty=-1
    ).exists()
    # No value created or destroyed: a move, so no GL.
    assert not GLEntry.objects.filter(doc_number=closure.doc_number).exists()
    assert _total_qty("GB001") == 10

    detail = _client(s["maker"]).get(f"/api/outbound/transfers/{transfer.pk}")
    assert detail.data["gap_state"] == "closed"
    assert detail.data["gap_closure"]["reason"] == "found_later"
    assert detail.data["qty_in_transit"] == 0


@pytest.mark.django_db(transaction=True)
def test_wrongly_scanned_puts_the_pieces_back_at_the_sender(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s, plan=(("GB001", 4),), scanned=3)
    closure_id = _raise_closure(s, transfer, "wrongly_scanned")
    _approve(s, closure_id)

    resp = _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 200, resp.data
    closure = TransferGapClosure.objects.get(pk=closure_id)

    # The piece never left the warehouse, so that is where it goes back.
    assert StockOnHand.objects.get(store=s["warehouse"], sku_code="GB001").net_qty == 7
    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 3
    back = StockLedgerEntry.objects.get(doc_number=closure.doc_number)
    assert (back.qty, back.store_id) == (1, s["warehouse"].id)
    assert not InTransitStock.objects.filter(transfer_doc_number=transfer.doc_number).exists()
    assert not GLEntry.objects.filter(doc_number=closure.doc_number).exists()
    assert _total_qty("GB001") == 10


@pytest.mark.django_db(transaction=True)
def test_lost_in_transit_takes_the_value_off_the_books(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s, plan=(("GB001", 4),), scanned=3)
    closure_id = _raise_closure(s, transfer, "lost_in_transit")
    _approve(s, closure_id)

    resp = _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 200, resp.data
    closure = TransferGapClosure.objects.get(pk=closure_id)

    # The piece lands nowhere — it is gone — and the books say so.
    assert not InTransitStock.objects.filter(transfer_doc_number=transfer.doc_number).exists()
    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 3
    assert StockOnHand.objects.get(store=s["warehouse"], sku_code="GB001").net_qty == 6
    assert not StockLedgerEntry.objects.filter(doc_number=closure.doc_number).exists()
    legs = {e.account: e.amount for e in GLEntry.objects.filter(doc_number=closure.doc_number)}
    assert legs == {GLAccount.SUSPENSE: 45000, GLAccount.INVENTORY: -45000}
    # The one honest way a piece leaves the total, and it is booked as a loss.
    assert _total_qty("GB001") == 9


@pytest.mark.django_db(transaction=True)
def test_losing_brand_owned_stock_reverses_the_memo_not_our_inventory(gap_scaffold):
    """A lost carton of SOR stock was never an asset on our books, so writing it
    off must not credit INVENTORY — and whether we owe the brand for it is a
    settlement claim, not a stock posting."""
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GS001", 3),))
    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "GS001", "qty": 2}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    closure_id = _raise_closure(s, transfer, "lost_in_transit")
    _approve(s, closure_id)
    resp = _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 200, resp.data
    closure = TransferGapClosure.objects.get(pk=closure_id)

    legs = {e.account: e.amount for e in GLEntry.objects.filter(doc_number=closure.doc_number)}
    assert legs == {GLAccount.SOR_CONTRA: 60000, GLAccount.SOR_STOCK: -60000}
    assert GLAccount.INVENTORY not in legs
    assert not GLEntry.objects.filter(account=GLAccount.VENDOR_PAYABLE).exists()
    assert _total_qty("GS001") == 4


# ---------------------------------------------------------------------------
# The receiving store never closes its own gap
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_receiving_store_cannot_raise_the_closure(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s)

    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/gap-closure",
        {"reason": "found_later"},
        format="json",
    )
    # A store manager is not even a senior role for this decision.
    assert resp.status_code == 403
    assert not TransferGapClosure.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_a_senior_entitled_to_the_receiving_store_is_still_refused(gap_scaffold):
    """Maker ≠ checker is not the rule here — entitlement is. Somebody senior
    enough to approve, but answerable for the store that received short, may not
    be either party."""
    s = gap_scaffold
    transfer = _received_short(s)

    resp = _client(s["ho_at_store"]).post(
        f"/api/outbound/transfers/{transfer.pk}/gap-closure",
        {"reason": "found_later"},
        format="json",
    )
    assert resp.status_code == 400
    assert "never by the store that received short" in str(resp.data)
    assert not TransferGapClosure.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_a_senior_at_the_receiving_store_cannot_be_the_approver_either(gap_scaffold):
    """The bar is in the posting layer, so clearing the inbox is not enough: the
    closure refuses to post with that person's name on it."""
    s = gap_scaffold
    transfer = _received_short(s)
    closure_id = _raise_closure(s, transfer, "found_later")
    _approve(s, closure_id, actor=s["ho_at_store"])

    resp = _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 400
    assert "never by the store that received short" in str(resp.data)
    assert TransferGapClosure.objects.get(pk=closure_id).docstatus == DocStatus.DRAFT
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 1


@pytest.mark.django_db(transaction=True)
def test_the_maker_cannot_approve_their_own_closure(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s)
    closure_id = _raise_closure(s, transfer, "found_later")

    approval = Approval.objects.get(object_id=closure_id, kind="gap_closure")
    resp = _client(s["maker"]).post(
        f"/api/approvals/{approval.pk}/decide", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Guards around the closure itself
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_transfer_with_no_gap_cannot_be_closed(gap_scaffold):
    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 2),))
    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {"scans": [{"barcode": "GB001", "qty": 2}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    resp = _client(s["maker"]).post(
        f"/api/outbound/transfers/{transfer.pk}/gap-closure",
        {"reason": "found_later"},
        format="json",
    )
    assert resp.status_code == 400
    assert "no gap" in str(resp.data)


@pytest.mark.django_db(transaction=True)
def test_one_gap_gets_one_closure(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s)
    _raise_closure(s, transfer, "found_later")

    resp = _client(s["maker"]).post(
        f"/api/outbound/transfers/{transfer.pk}/gap-closure",
        {"reason": "lost_in_transit"},
        format="json",
    )
    assert resp.status_code == 400
    assert "already has a gap closure" in str(resp.data)
    assert "correct the one it has" in str(resp.data)


def _reject(s, closure_id, reason="Wrong reason — those came back to us.") -> None:
    closure = TransferGapClosure.objects.get(pk=closure_id)
    approval = Approval.objects.filter(
        object_id=closure.pk, kind="gap_closure", status=ApprovalStatus.PENDING
    ).get()
    resp = _client(s["checker"]).post(
        f"/api/approvals/{approval.pk}/decide",
        {"action": "reject", "reason": reason},
        format="json",
    )
    assert resp.status_code == 200, resp.data


def _amend(s, closure_id, reason, note="", actor=None):
    return _client(actor or s["maker"]).patch(
        f"/api/outbound/gap-closures/{closure_id}",
        {"reason": reason, "note": note},
        format="json",
    )


def _closure_lines(closure_id):
    return TransferGapClosure.objects.get(pk=closure_id).lines.all()


@pytest.mark.django_db(transaction=True)
def test_a_rejected_closure_can_be_corrected_and_posted(gap_scaffold):
    """A rejection must not strand the pieces.

    One gap still gets one closure document, but while it is a draft that
    document can be corrected — otherwise a single wrong reason code leaves the
    shortfall in the in-transit bucket with no route out, which is the dead end
    #71 exists to close.
    """
    s = gap_scaffold
    transfer = _received_short(s, plan=(("GB001", 4),), scanned=3)
    closure_id = _raise_closure(s, transfer, "lost_in_transit")
    _reject(s, closure_id)

    resp = _amend(s, closure_id, "found_later", note="Turned up in the back room.")
    assert resp.status_code == 200, resp.data

    closure = TransferGapClosure.objects.get(pk=closure_id)
    assert closure.reason == "found_later"
    assert closure.note == "Turned up in the back room."
    assert closure.docstatus == DocStatus.DRAFT
    # The correction asks again, and the rejection stays on the record.
    assert (
        Approval.objects.filter(
            object_id=closure.pk, kind="gap_closure", status=ApprovalStatus.REJECTED
        ).count()
        == 1
    )
    pending = Approval.objects.filter(
        object_id=closure.pk, kind="gap_closure", status=ApprovalStatus.PENDING
    ).get()
    assert pending.made_by_id == s["maker"].id

    # And the corrected reason is the one that posts.
    _approve(s, closure_id)
    assert (
        _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit").status_code
        == 200
    )
    assert not InTransitStock.objects.filter(transfer_doc_number=transfer.doc_number).exists()
    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 4


@pytest.mark.django_db(transaction=True)
def test_a_closure_posts_once(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s)
    closure_id = _raise_closure(s, transfer, "found_later")
    _approve(s, closure_id)
    c = _client(s["maker"])
    assert c.post(f"/api/outbound/gap-closures/{closure_id}/submit").status_code == 200

    resp = c.post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 400
    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 4


@pytest.mark.django_db(transaction=True)
def test_a_stale_closure_is_refused_rather_than_draining_the_wrong_amount(gap_scaffold):
    """The bucket, not the draft, says what is still owed."""
    s = gap_scaffold
    transfer = _received_short(s, plan=(("GB001", 4),), scanned=3)
    closure_id = _raise_closure(s, transfer, "found_later")
    _approve(s, closure_id)

    bucket = InTransitStock.objects.get(transfer_doc_number=transfer.doc_number)
    bucket.qty = 2
    bucket.save(update_fields=["qty"])

    resp = _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 400
    assert "moved since this closure was drafted" in str(resp.data)
    assert "correct it" in str(resp.data)
    assert TransferGapClosure.objects.get(pk=closure_id).docstatus == DocStatus.DRAFT


@pytest.mark.django_db(transaction=True)
def test_correcting_an_approved_closure_sends_it_back_to_the_checker(gap_scaffold):
    """A correction is never cleared by the old decision.

    The checker approved "found later" — pieces coming back onto the books. If
    the maker could then amend it to "lost in transit" and post, they would have
    written stock off on the strength of an approval for something else.
    """
    s = gap_scaffold
    transfer = _received_short(s, plan=(("GB001", 4),), scanned=3)
    closure_id = _raise_closure(s, transfer, "found_later")
    _approve(s, closure_id)

    assert _amend(s, closure_id, "lost_in_transit").status_code == 200

    resp = _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit")
    assert resp.status_code == 400
    assert "Waiting for approval" in str(resp.data)
    # Nothing moved on the strength of the stale approval.
    assert InTransitStock.objects.get(transfer_doc_number=transfer.doc_number).qty == 1

    _approve(s, closure_id)
    assert (
        _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit").status_code
        == 200
    )
    # And it is the corrected reason that posted. "Found later" would have put
    # the missing piece on the shelf beside the three that arrived; written off,
    # it never lands — and the bucket is empty either way.
    assert StockOnHand.objects.get(store=s["store"], sku_code="GB001").net_qty == 3
    assert not InTransitStock.objects.filter(transfer_doc_number=transfer.doc_number).exists()


@pytest.mark.django_db(transaction=True)
def test_a_corrected_closure_re_reads_the_remainder_rather_than_keeping_it(gap_scaffold):
    """Lines are rebuilt from the transfer, so a correction cannot carry a
    number the maker typed or a number that has since moved on."""
    s = gap_scaffold
    transfer = _received_short(s, plan=(("GB001", 4), ("GB002", 3)), scanned=3)
    closure_id = _raise_closure(s, transfer, "found_later")
    before = {(line.sku_code, line.qty) for line in _closure_lines(closure_id)}

    assert _amend(s, closure_id, "wrongly_scanned").status_code == 200

    assert {(line.sku_code, line.qty) for line in _closure_lines(closure_id)} == before


@pytest.mark.django_db(transaction=True)
def test_a_posted_closure_cannot_be_corrected(gap_scaffold):
    s = gap_scaffold
    transfer = _received_short(s)
    closure_id = _raise_closure(s, transfer, "found_later")
    _approve(s, closure_id)
    assert (
        _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit").status_code
        == 200
    )

    resp = _amend(s, closure_id, "lost_in_transit")
    assert resp.status_code == 400
    assert "already been posted" in str(resp.data)


@pytest.mark.django_db(transaction=True)
def test_a_senior_at_the_receiving_store_cannot_correct_the_closure_either(gap_scaffold):
    """The entitlement bar covers correcting, not just raising and approving —
    otherwise the receiving store gets its say through the back door."""
    s = gap_scaffold
    transfer = _received_short(s)
    closure_id = _raise_closure(s, transfer, "found_later")

    resp = _amend(s, closure_id, "lost_in_transit", actor=s["ho_at_store"])
    assert resp.status_code == 400
    assert "never by the store that received short" in str(resp.data)
    assert TransferGapClosure.objects.get(pk=closure_id).reason == "found_later"


# ---------------------------------------------------------------------------
# Projections stay rebuildable through every exception path
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_rebuild_reproduces_every_projection_after_exceptions_and_closure(gap_scaffold):
    """Damaged, extra and a closed gap all in one transfer — then wipe the three
    caches and rebuild them from the append-only ledger."""
    from django.core.management import call_command

    s = gap_scaffold
    transfer = _dispatched(s, plan=(("GB001", 4),))
    resp = _client(s["receiver"]).post(
        f"/api/outbound/transfers/{transfer.pk}/receive",
        {
            "scans": [{"barcode": "GB001", "qty": 2}],
            "damaged": [{"barcode": "GB001", "qty": 1}],
            "extras": [{"barcode": "GX001", "qty": 1}],
            "notes": "One short, one broken, one stranger.",
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data
    closure_id = _raise_closure(s, transfer, "wrongly_scanned")
    _approve(s, closure_id)
    assert (
        _client(s["maker"]).post(f"/api/outbound/gap-closures/{closure_id}/submit").status_code
        == 200
    )

    def snapshot():
        return (
            sorted(
                StockOnHand.objects.values_list(
                    "store_id", "sku_code", "net_qty", "net_value_paise"
                )
            ),
            sorted(InTransitStock.objects.values_list("transfer_doc_number", "sku_code", "qty")),
            sorted(
                QuarantineStock.objects.values_list("store_id", "sku_code", "qty", "value_paise")
            ),
        )

    before = snapshot()
    assert before[1] == []  # the gap is closed, so nothing is in transit
    assert before[2] == [(s["store"].id, "GB001", 1, 45000)]

    StockOnHand.objects.all().delete()
    InTransitStock.objects.all().delete()
    QuarantineStock.objects.all().delete()
    call_command("rebuild_stock_on_hand")

    assert snapshot() == before
