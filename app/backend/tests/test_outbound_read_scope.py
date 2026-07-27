"""Read scope on the outbound documents (issue #141).

Writing an outbound document was always gated — ``enforce_store_scope`` stops a
store person dispatching from a store they do not work at. *Reading* one was not
gated at all, so the Deoghar manager's Transfers screen listed a move between two
other stores, and knowing a voucher's id was enough to open any of them.

Two rules, both already ratified and both already live in the top-bar search
registry; this suite is where they bite on the list and detail endpoints:

* **a transfer belongs to both ends of the move** — visible when the caller's
  scope holds the source *or* the destination, and to nobody else. Returns to
  brand, adjustments, write-offs and V-flips are visible at their own store;
* **a brand-scoped caller sees none of them** (ADR-0003) — these documents carry
  no brand, so nothing can prove a row is theirs. An empty list, not an error and
  not everything. #110 replaces that interim with cross-by-brand.

Out of scope must be *indistinguishable from not existing*: the detail endpoints
answer 404, never 403, because a 403 confirms the document is real.
"""

from __future__ import annotations

from typing import Any

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from rest_framework.test import APIClient

from accounts.models import ScopeType, User
from core.documents import VoucherSeries
from masters.models import Brand, Gstin, LegalEntity, Store
from outbound.models import (
    ReturnToVendor,
    ReturnToVendorLine,
    StockAdjustment,
    StockAdjustmentLine,
    StoreTransfer,
    TransferGapClosure,
    TransferPT,
    VFlip,
    VFlipLine,
    WriteOff,
    WriteOffLine,
)
from vendors.models import Vendor

TRANSFERS = "/api/outbound/transfers"
#: The four store-owned outbound documents, as `(list url, scaffold key prefix)`.
#: Parameterising rather than repeating keeps a fifth document type one line away
#: and stops one of the four quietly losing its gate.
STORE_DOCS = [
    ("/api/outbound/rtvs", "rtv"),
    ("/api/outbound/adjustments", "adj"),
    ("/api/outbound/writeoffs", "wro"),
    ("/api/outbound/vflips", "vfl"),
]


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _ids(resp: Any) -> set[int]:
    return {row["id"] for row in resp.json()}


@pytest.fixture()
def scaffold(db):
    """Three stores — DEO which the caller manages, BNK and FAR which they must
    never read — with one of every outbound document at DEO and at BNK, and three
    transfers: out of DEO, into DEO, and one between the two other stores that
    has nothing to do with the caller.
    """
    entity = LegalEntity.objects.create(code="rs-ent", name="Read Scope Entity", pan="AAACR1234B")
    gstin_jh = Gstin.objects.create(
        gstin="20AAACR1234B1ZQ", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    gstin_bh = Gstin.objects.create(
        gstin="10AAACR1234B1ZQ", state_code="10", state_name="Bihar", legal_entity=entity
    )
    deo = Store.objects.create(code="RS-DEO", name="Read Deoghar", gstin=gstin_jh)
    bnk = Store.objects.create(code="RS-BNK", name="Read Banka", gstin=gstin_bh)
    far = Store.objects.create(code="RS-FAR", name="Read Faraway", gstin=gstin_bh)
    for code in ("RS-DEO", "RS-BNK", "RS-FAR"):
        VoucherSeries.objects.create(
            fy="26-27", store_code=code, doc_type="STO", prefix=f"{code}/STO/26-27/", next_seq=1
        )

    brand = Brand.objects.create(
        code="rs-brand",
        name="ReadBrand",
        ownership=Brand.Ownership.BRAND_OWNED,
        return_terms=Brand.ReturnTerms.UNCAPPED,
    )
    vendor = Vendor.objects.create(name="Read Vendor", code="rsvnd")

    owner_user = User.objects.create_user(
        username="rs_owner",
        password=TEST_PASSWORD,
        role=make_role("owner", "Owner (read scope test)"),
        entity=entity,
        scope_type=ScopeType.ALL,
    )
    store_user = User.objects.create_user(
        username="rs_store",
        password=TEST_PASSWORD,
        role=make_role("store_manager", "Store Manager (read scope test)"),
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    store_user.stores.add(deo)
    brand_user = User.objects.create_user(
        username="rs_brand",
        password=TEST_PASSWORD,
        role=make_role("brand_manager", "Brand Manager (read scope test)"),
        entity=entity,
        scope_type=ScopeType.BRAND,
    )
    brand_user.brands.add(brand)

    def _transfer(source: Store, destination: Store) -> StoreTransfer:
        t = StoreTransfer(source_store=source, destination_store=destination)
        t.save()
        t.post()  # gives it a voucher number, so a search can look for it
        return t

    built: dict[str, Any] = {
        "deo": deo,
        "bnk": bnk,
        "far": far,
        "brand": brand,
        "owner": owner_user,
        "store_user": store_user,
        "brand_user": brand_user,
        "out_of_deo": _transfer(deo, far),
        "into_deo": _transfer(far, deo),
        "foreign": _transfer(bnk, far),
    }

    for key, store in (("deo", deo), ("bnk", bnk)):
        rtv = ReturnToVendor.objects.create(
            store=store,
            vendor=vendor,
            brand=brand,
            return_type="defective",
            created_by=owner_user,
        )
        ReturnToVendorLine.objects.create(rtv=rtv, sku_code="RS-SKU1", qty=1, unit_cost_paise=1000)
        built[f"rtv_{key}"] = rtv

        adj = StockAdjustment.objects.create(store=store, reason="miscount", created_by=owner_user)
        StockAdjustmentLine.objects.create(
            adjustment=adj,
            sku_code="RS-SKU1",
            book_qty=2,
            counted_qty=1,
            adj_qty=-1,
            unit_cost_paise=1000,
        )
        built[f"adj_{key}"] = adj

        wro = WriteOff.objects.create(store=store, reason="dead_stock", created_by=owner_user)
        WriteOffLine.objects.create(writeoff=wro, sku_code="RS-SKU1", qty=1, unit_cost_paise=1000)
        built[f"wro_{key}"] = wro

        vfl = VFlip.objects.create(
            store=store, original_brand=brand, season="SS26", created_by=owner_user
        )
        VFlipLine.objects.create(vflip=vfl, sku_code="RS-SKU1", qty=1, unit_cost_paise=1000)
        built[f"vfl_{key}"] = vfl

    return built


# -- Transfers: both ends of the move ---------------------------------------


@pytest.mark.django_db(transaction=True)
def test_transfer_list_holds_both_ends_of_the_move_and_nothing_else(scaffold):
    """A transfer belongs to the sender and to the receiver — the store person
    sees the ones they sent and the ones coming to them, and never a move between
    two other stores."""
    seen = _ids(_client(scaffold["store_user"]).get(TRANSFERS))

    assert seen == {scaffold["out_of_deo"].id, scaffold["into_deo"].id}


@pytest.mark.django_db(transaction=True)
def test_a_transfer_between_other_stores_does_not_exist_to_a_store_person(scaffold):
    """Knowing the id is not a way in, and the answer is 404 — a 403 would confirm
    the document is real, which is the thing being withheld (ADR-0003)."""
    client = _client(scaffold["store_user"])

    assert client.get(f"{TRANSFERS}/{scaffold['foreign'].id}").status_code == 404
    assert client.get(f"{TRANSFERS}/{scaffold['out_of_deo'].id}").status_code == 200
    assert client.get(f"{TRANSFERS}/{scaffold['into_deo'].id}").status_code == 200


@pytest.mark.django_db(transaction=True)
def test_an_all_scope_caller_still_sees_every_transfer(scaffold):
    owner = _client(scaffold["owner"])

    assert _ids(owner.get(TRANSFERS)) >= {
        scaffold["out_of_deo"].id,
        scaffold["into_deo"].id,
        scaffold["foreign"].id,
    }
    assert owner.get(f"{TRANSFERS}/{scaffold['foreign'].id}").status_code == 200


# -- RTV, adjustment, write-off, V-flip: their own store --------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("url", "key"), STORE_DOCS)
def test_store_owned_outbound_documents_list_only_the_callers_store(scaffold, url, key):
    seen = _ids(_client(scaffold["store_user"]).get(url))

    assert seen == {scaffold[f"{key}_deo"].id}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("url", "key"), STORE_DOCS)
def test_another_stores_outbound_document_does_not_exist_to_a_store_person(scaffold, url, key):
    client = _client(scaffold["store_user"])

    assert client.get(f"{url}/{scaffold[f'{key}_bnk'].id}").status_code == 404
    assert client.get(f"{url}/{scaffold[f'{key}_deo'].id}").status_code == 200


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("url", "key"), STORE_DOCS)
def test_an_all_scope_caller_still_sees_every_store(scaffold, url, key):
    owner = _client(scaffold["owner"])

    assert _ids(owner.get(url)) >= {scaffold[f"{key}_deo"].id, scaffold[f"{key}_bnk"].id}
    assert owner.get(f"{url}/{scaffold[f'{key}_bnk'].id}").status_code == 200


# -- The brand manager: fail closed, exactly as the top bar already does ----


@pytest.mark.django_db(transaction=True)
def test_a_brand_scoped_caller_gets_empty_lists_not_everything(scaffold):
    """These documents carry no brand, so nothing can prove a row is theirs
    (ADR-0003). "Stores are the wrong question" must never resolve to "so show
    every store" — and an empty list is the answer, not a 403.

    A deliberate interim: #110 gives outbound documents a brand dimension and
    replaces this with cross-by-brand.
    """
    client = _client(scaffold["brand_user"])

    for url in [TRANSFERS] + [u for u, _ in STORE_DOCS]:
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert resp.json() == [], url


@pytest.mark.django_db(transaction=True)
def test_a_brand_scoped_caller_cannot_open_one_by_id_either(scaffold):
    client = _client(scaffold["brand_user"])

    assert client.get(f"{TRANSFERS}/{scaffold['out_of_deo'].id}").status_code == 404
    for url, key in STORE_DOCS:
        assert client.get(f"{url}/{scaffold[f'{key}_deo'].id}").status_code == 404, url


# -- The routes that reach the same document another way --------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("suffix", ["pt", "pt.csv", "pt.xlsx"])
def test_the_transfer_pt_is_not_a_way_round_the_gate_on_its_transfer(scaffold, suffix):
    """The PT travels with the carton and is reached through the transfer, so it
    inherits the transfer's scope. It is the surface that matters most: the rows
    carry the unit cost the transfer detail does not print, so an open PT would
    hand another store its landed cost.
    """
    TransferPT.objects.create(transfer=scaffold["foreign"], rows=[{"MRP": "999"}])
    TransferPT.objects.create(transfer=scaffold["out_of_deo"], rows=[{"MRP": "999"}])
    client = _client(scaffold["store_user"])

    assert client.get(f"{TRANSFERS}/{scaffold['foreign'].id}/{suffix}").status_code == 404
    assert client.get(f"{TRANSFERS}/{scaffold['out_of_deo'].id}/{suffix}").status_code == 200
    assert (
        _client(scaffold["owner"]).get(f"{TRANSFERS}/{scaffold['foreign'].id}/{suffix}").status_code
        == 200
    )


@pytest.mark.django_db(transaction=True)
def test_a_gap_closure_at_another_store_cannot_be_read_by_id(scaffold):
    """The closure names both ends of the move and prices the missing pieces, so
    it is scoped like the documents around it — by entitlement rather than by the
    switcher, because correcting one is an act and the top bar must not veto it.
    """
    closure = TransferGapClosure.objects.create(
        transfer=scaffold["foreign"],
        store=scaffold["bnk"],
        reason="lost_in_transit",
        created_by=scaffold["owner"],
    )
    url = f"/api/outbound/gap-closures/{closure.id}"

    assert _client(scaffold["store_user"]).get(url).status_code == 404
    assert _client(scaffold["brand_user"]).get(url).status_code == 404
    assert _client(scaffold["owner"]).get(url).status_code == 200


# -- The in-page search (#102) now filters a genuinely scoped set -----------


@pytest.mark.django_db(transaction=True)
def test_searching_another_stores_voucher_number_answers_with_nothing(scaffold):
    """#102's criterion — "a store person only ever searches their own rows" —
    passed vacuously while the list was the whole network. It bites here: the
    foreign transfer's own voucher number, typed in full, finds nothing for the
    store person and finds it for the owner."""
    number = scaffold["foreign"].doc_number

    assert _client(scaffold["store_user"]).get(f"{TRANSFERS}?q={number}").json() == []
    assert _ids(_client(scaffold["owner"]).get(f"{TRANSFERS}?q={number}")) == {
        scaffold["foreign"].id
    }


@pytest.mark.django_db(transaction=True)
def test_searching_the_other_end_of_a_foreign_move_answers_with_nothing(scaffold):
    """`RS-FAR` is an end of all three transfers, so it matches the foreign one
    too — the search term is not what keeps it out, the gate is."""
    seen = _ids(_client(scaffold["store_user"]).get(f"{TRANSFERS}?q=RS-FAR"))

    assert seen == {scaffold["out_of_deo"].id, scaffold["into_deo"].id}
