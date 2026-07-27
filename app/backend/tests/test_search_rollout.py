"""In-page search, rolled out to the rest of the built list screens (#106).

#102 built the shared control and the ``?q=`` contract and proved it on three
screens. This is where the rollout is asserted at the API seam: the term
narrows the list, on the server, and — the property the issue calls out by
name — a store-scoped user searching a store-scoped screen never gets a row
their scope would otherwise withhold. Return to Brand and the Approvals inbox
are asserted here; the stock ledger's own store-scope search is covered
alongside on-hand in ``test_inpage_search.py``.

A handful of the remaining screens (adjustments, write-offs, V-flips, the
vendor ledger) get a narrower smoke test — the term narrows the list and an
empty term changes nothing — since their scoping is already exercised by
``test_outbound_read_scope.py`` and composes with search the same way RTV's
does (search is applied strictly after the scope queryset).
"""

from __future__ import annotations

from typing import Any

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from approvals.services import request_approval
from core.documents import VoucherSeries
from finledger.models import CashLedgerEntry, VendorLedgerEntry
from masters.models import Brand, Gstin, LegalEntity, Store
from outbound.models import (
    ReturnToVendor,
    ReturnToVendorLine,
    StockAdjustment,
    StockAdjustmentLine,
    VFlip,
    VFlipLine,
    WriteOff,
    WriteOffLine,
)
from vendors.models import Vendor

RTVS = "/api/outbound/rtvs"
ADJUSTMENTS = "/api/outbound/adjustments"
WRITEOFFS = "/api/outbound/writeoffs"
VFLIPS = "/api/outbound/vflips"
APPROVALS_INBOX = "/api/approvals/inbox"
VENDOR_ENTRIES = "/api/finledger/vendor/entries"
CASH_ENTRIES = "/api/finledger/cash/entries"


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _ids(resp: Any) -> set[int]:
    return {row["id"] for row in resp.json() if isinstance(row, dict) and "id" in row}


@pytest.fixture()
def scaffold(db):
    """Two stores — DEO, which the caller manages, and BNK, which they must
    never see — each carrying an RTV and a pending approval that share a search
    term, so a leak shows up as an extra row rather than as silence."""
    entity = LegalEntity.objects.create(
        code="sr-ent",
        name="Search Rollout Entity",
        pan="AAACS9001B",
    )
    gstin_jh = Gstin.objects.create(
        gstin="20AAACS9001B1ZQ", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    gstin_bh = Gstin.objects.create(
        gstin="10AAACS9001B1ZQ", state_code="10", state_name="Bihar", legal_entity=entity
    )
    deo = Store.objects.create(code="SR-DEO", name="Rollout Deoghar", gstin=gstin_jh)
    bnk = Store.objects.create(code="SR-BNK", name="Rollout Banka", gstin=gstin_bh)
    for code in ("SR-DEO", "SR-BNK"):
        for doc_type in ("RTV", "ADJ", "WRO", "VFL"):
            VoucherSeries.objects.create(
                fy="26-27",
                store_code=code,
                doc_type=doc_type,
                prefix=f"{code}/{doc_type}/26-27/",
                next_seq=1,
            )

    brand = Brand.objects.create(
        code="sr-brand",
        name="RolloutBrand",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    vendor = Vendor.objects.create(name="Rollout Traders", code="srvnd")

    owner = User.objects.create_user(
        username="sr_owner",
        password=TEST_PASSWORD,
        role=make_role("owner", "Owner (search rollout test)"),
        entity=entity,
        scope_type=ScopeType.ALL,
    )
    store_user = User.objects.create_user(
        username="sr_store",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (search rollout test)"),
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    store_user.stores.add(deo)
    # A second person raises the requests, so `owner` (the approver) never asks
    # their own — an approval never lists the asker or the maker.
    maker = User.objects.create_user(
        username="sr_maker",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (search rollout test, maker)"),
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    maker.stores.add(deo)

    built: dict[str, Any] = {
        "deo": deo,
        "bnk": bnk,
        "owner": owner,
        "store_user": store_user,
        "maker": maker,
    }

    for key, store in (("deo", deo), ("bnk", bnk)):
        rtv = ReturnToVendor.objects.create(
            store=store,
            vendor=vendor,
            brand=brand,
            return_type="defective",
            created_by=owner,
        )
        ReturnToVendorLine.objects.create(rtv=rtv, sku_code="SR-SKU1", qty=1, unit_cost_paise=1000)
        rtv.post()  # mints doc_number — this suite is about search, not stock posting
        built[f"rtv_{key}"] = rtv

        adj = StockAdjustment.objects.create(store=store, reason="miscount", created_by=owner)
        StockAdjustmentLine.objects.create(
            adjustment=adj,
            sku_code="SR-SKU1",
            book_qty=2,
            counted_qty=1,
            adj_qty=-1,
            unit_cost_paise=1000,
        )
        adj.post()
        built[f"adj_{key}"] = adj

        wro = WriteOff.objects.create(store=store, reason="dead_stock", created_by=owner)
        WriteOffLine.objects.create(writeoff=wro, sku_code="SR-SKU1", qty=1, unit_cost_paise=1000)
        wro.post()
        built[f"wro_{key}"] = wro

        vfl = VFlip.objects.create(
            store=store,
            original_brand=brand,
            season="SS26",
            created_by=owner,
        )
        VFlipLine.objects.create(vflip=vfl, sku_code="SR-SKU1", qty=1, unit_cost_paise=1000)
        vfl.post()
        built[f"vfl_{key}"] = vfl

        approval = request_approval(
            built[f"rtv_{key}"],
            kind="rtv",
            kind_label="Return to Brand",
            title=f"RTV at {store.code} — RolloutBrand",
            made_by=maker,
            requested_by=maker,
            approver_roles=["owner"],
            store=store,
        )
        built[f"approval_{key}"] = approval

    vle_deo = VendorLedgerEntry.objects.create(
        amount=-100000,
        vendor=vendor,
        kind="bill",
        doc_number="SR-VL-DEO-1",
        description="Rollout bill",
        reference="",
    )
    other_vendor = Vendor.objects.create(name="Other Traders", code="srvnd2")
    vle_other = VendorLedgerEntry.objects.create(
        amount=-50000,
        vendor=other_vendor,
        kind="bill",
        doc_number="SR-VL-OTHER-1",
        description="Unrelated bill",
        reference="",
    )
    built["vle_deo"] = vle_deo
    built["vle_other"] = vle_other

    cle_deo = CashLedgerEntry.objects.create(
        amount=-25000,
        account="CASH",
        kind="payment",
        doc_number="SR-CL-DEO-1",
        description="Rollout cash-out",
        vendor=vendor,
    )
    cle_other = CashLedgerEntry.objects.create(
        amount=-10000,
        account="CASH",
        kind="payment",
        doc_number="SR-CL-OTHER-1",
        description="Unrelated cash-out",
        vendor=other_vendor,
    )
    built["cle_deo"] = cle_deo
    built["cle_other"] = cle_other

    return built


# -- Return to Brand ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_rtv_search_matches_doc_number_and_brand(scaffold):
    client = _client(scaffold["owner"])
    rtv = scaffold["rtv_deo"]
    assert _ids(client.get(f"{RTVS}?q={rtv.doc_number}")) == {rtv.id}
    assert rtv.id in _ids(client.get(f"{RTVS}?q=RolloutBrand"))
    assert client.get(f"{RTVS}?q=no-such-return").json() == []


@pytest.mark.django_db(transaction=True)
def test_rtv_search_stays_inside_the_caller_store_scope(scaffold):
    """A store-scoped user searching RTVs never gets the other store's row —
    scoping is applied before search narrows further, never the other way."""
    client = _client(scaffold["store_user"])
    seen = _ids(client.get(f"{RTVS}?q=RolloutBrand"))
    assert seen == {scaffold["rtv_deo"].id}
    assert scaffold["rtv_bnk"].id not in seen

    # ...and the same term, for the owner whose scope reaches both, finds it.
    seen_by_owner = _ids(_client(scaffold["owner"]).get(f"{RTVS}?q=RolloutBrand"))
    assert seen_by_owner == {scaffold["rtv_deo"].id, scaffold["rtv_bnk"].id}


@pytest.mark.django_db(transaction=True)
def test_rtv_empty_term_reads_exactly_as_today(scaffold):
    client = _client(scaffold["store_user"])
    assert client.get(f"{RTVS}?q=").json() == client.get(RTVS).json()


# -- Approvals inbox -----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_approvals_search_matches_title_and_type(scaffold):
    client = _client(scaffold["owner"])
    assert scaffold["approval_deo"].id in _ids(client.get(f"{APPROVALS_INBOX}?q=RolloutBrand"))
    assert scaffold["approval_deo"].id in _ids(client.get(f"{APPROVALS_INBOX}?q=Return+to+Brand"))
    assert client.get(f"{APPROVALS_INBOX}?q=no-such-approval").json() == []


@pytest.mark.django_db(transaction=True)
def test_approvals_search_stays_inside_the_inbox_scope(scaffold):
    """The inbox is store-scoped (ADR-0003): an approver whose scope is DEO only
    never sees BNK's approval, searched or not — even with the store-manager role
    swapped onto an approver so scope, not the role gate, is what's on trial."""
    approver = User.objects.create_user(
        username="sr_approver",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (search rollout test, approver)"),
        entity=scaffold["deo"].gstin.legal_entity,
        scope_type=ScopeType.STORE,
    )
    approver.stores.add(scaffold["deo"])
    for key in ("deo", "bnk"):
        scaffold[f"approval_{key}"].approver_roles = ["store_manager"]
        scaffold[f"approval_{key}"].save(update_fields=["approver_roles"])

    seen = _ids(_client(approver).get(f"{APPROVALS_INBOX}?q=RolloutBrand"))
    assert seen == {scaffold["approval_deo"].id}
    assert scaffold["approval_bnk"].id not in seen


@pytest.mark.django_db(transaction=True)
def test_approvals_empty_term_reads_exactly_as_today(scaffold):
    client = _client(scaffold["owner"])
    assert client.get(f"{APPROVALS_INBOX}?q=").json() == client.get(APPROVALS_INBOX).json()


# -- Adjustments, write-offs, V-flips: term narrows, scope already proven ------


@pytest.mark.django_db(transaction=True)
def test_adjustment_search_matches_doc_number_and_reason(scaffold):
    client = _client(scaffold["owner"])
    adj = scaffold["adj_deo"]
    assert _ids(client.get(f"{ADJUSTMENTS}?q={adj.doc_number}")) == {adj.id}
    assert adj.id in _ids(client.get(f"{ADJUSTMENTS}?q=miscount"))
    assert client.get(f"{ADJUSTMENTS}?q=no-such-adjustment").json() == []
    assert client.get(f"{ADJUSTMENTS}?q=").json() == client.get(ADJUSTMENTS).json()


@pytest.mark.django_db(transaction=True)
def test_writeoff_search_matches_doc_number_and_reason(scaffold):
    client = _client(scaffold["owner"])
    wro = scaffold["wro_deo"]
    assert _ids(client.get(f"{WRITEOFFS}?q={wro.doc_number}")) == {wro.id}
    assert wro.id in _ids(client.get(f"{WRITEOFFS}?q=dead_stock"))
    assert client.get(f"{WRITEOFFS}?q=no-such-writeoff").json() == []


@pytest.mark.django_db(transaction=True)
def test_vflip_search_matches_doc_number_and_brand(scaffold):
    client = _client(scaffold["owner"])
    vfl = scaffold["vfl_deo"]
    assert _ids(client.get(f"{VFLIPS}?q={vfl.doc_number}")) == {vfl.id}
    assert vfl.id in _ids(client.get(f"{VFLIPS}?q=RolloutBrand"))
    assert client.get(f"{VFLIPS}?q=no-such-vflip").json() == []


# -- Vendor & cash ledgers ------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_vendor_ledger_search_matches_doc_number_and_party(scaffold):
    client = _client(scaffold["owner"])
    entry = scaffold["vle_deo"]
    by_doc = client.get(f"{VENDOR_ENTRIES}?q={entry.doc_number}").json()["results"]
    assert {r["id"] for r in by_doc} == {entry.id}
    by_party_resp = client.get(f"{VENDOR_ENTRIES}?q=Rollout+Traders").json()["results"]
    by_party = {r["id"] for r in by_party_resp}
    assert entry.id in by_party
    assert scaffold["vle_other"].id not in by_party
    assert client.get(f"{VENDOR_ENTRIES}?q=no-such-entry").json()["results"] == []


@pytest.mark.django_db(transaction=True)
def test_cash_ledger_search_matches_doc_number_and_party(scaffold):
    client = _client(scaffold["owner"])
    entry = scaffold["cle_deo"]
    by_doc = client.get(f"{CASH_ENTRIES}?q={entry.doc_number}").json()["results"]
    assert {r["id"] for r in by_doc} == {entry.id}
    by_party_resp = client.get(f"{CASH_ENTRIES}?q=Rollout+Traders").json()["results"]
    by_party = {r["id"] for r in by_party_resp}
    assert entry.id in by_party
    assert scaffold["cle_other"].id not in by_party
