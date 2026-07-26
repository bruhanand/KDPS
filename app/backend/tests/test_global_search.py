"""Global search contract (issue #86), asserted at the API seam.

Three properties matter and none of them are about implementation: a scanned
barcode resolves to its cohorts with the caller's own stock context; a voucher
number finds its document whatever type it is; and neither can ever show a
store-scoped user another store's data (the anti-leak line). The fourth is
honesty — a no-match answer says so rather than returning a silent blank.
"""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, ScopeType, User
from accounts.rbac_matrix import section_access_for
from core.documents import VoucherSeries
from inbound.models import Grn
from masters.models import Brand, Cohort, Gstin, LegalEntity, Season, Sku, Store
from outbound.models import StockAdjustment, StoreTransfer
from stockledger.models import StockOnHand
from tests._creds import TEST_PASSWORD
from vendors.models import Booking, Vendor

SEARCH = "/api/search"


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _results(body: dict[str, Any], group: str) -> list[dict[str, Any]]:
    for g in body["groups"]:
        if g["key"] == group:
            return list(g["results"])
    return []


def _post(doc: Any) -> Any:
    """Save a draft and take it through the FSM so it carries a real number."""
    doc.save()
    doc.post()
    return doc


@pytest.fixture()
def scaffold(db):
    """Two stores — DEO the caller's own, BNK another — with a document at each."""
    entity = LegalEntity.objects.create(code="gs-ent", name="Search Entity", pan="AAACS4321B")
    gstin_jh = Gstin.objects.create(
        gstin="20AAACS4321B1ZQ", state_code="20", state_name="Jharkhand", legal_entity=entity
    )
    gstin_bh = Gstin.objects.create(
        gstin="10AAACS4321B1ZQ", state_code="10", state_name="Bihar", legal_entity=entity
    )
    store_deo = Store.objects.create(code="GS-DEO", name="Search DEO", gstin=gstin_jh)
    store_bnk = Store.objects.create(code="GS-BNK", name="Search Banka", gstin=gstin_bh)

    brand = Brand.objects.create(
        code="gs-arrow",
        name="ArrowSearch",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    vendor = Vendor.objects.create(name="Search Vendor", code="gsvnd")

    for code in ("GS-DEO", "GS-BNK"):
        for doc_type in ("GRN", "STO", "ADJ"):
            VoucherSeries.objects.create(
                fy="26-27",
                store_code=code,
                doc_type=doc_type,
                prefix=f"{code}/{doc_type}/26-27/",
                next_seq=1,
            )

    # One SKU bought across two seasons — the cohort case a scan must resolve.
    sku = Sku.objects.create(
        barcode="GS-BAR-001",
        design="ASD1234",
        color="Blue",
        size="40",
        brand="ArrowSearch",
        item="shirt",
        hsn="6205",
        mrp_paise=199900,
    )
    Cohort.objects.create(
        sku=sku, barcode=sku.barcode, season="SS26", unit_cost_paise=90000, mrp_paise=199900
    )
    Cohort.objects.create(
        sku=sku, barcode=sku.barcode, season="AW26", unit_cost_paise=95000, mrp_paise=199900
    )
    for store, gstin, qty, season in (
        (store_deo, gstin_jh, 7, "SS26"),
        (store_bnk, gstin_bh, 500, "SS26"),
    ):
        StockOnHand.objects.create(
            store=store,
            gstin=gstin,
            sku_code=sku.barcode,
            design="ASD1234",
            color="Blue",
            size="40",
            brand="ArrowSearch",
            season=season,
            item="shirt",
            hsn="6205",
            net_qty=qty,
            net_value_paise=qty * 90000,
        )

    grn_deo = _post(Grn(store=store_deo, vendor=vendor, received_at=Grn.ReceivedAt.STORE))
    grn_bnk = _post(Grn(store=store_bnk, vendor=vendor, received_at=Grn.ReceivedAt.STORE))
    adj_bnk = _post(StockAdjustment(store=store_bnk, reason="miscount", notes="other store"))
    transfer = _post(StoreTransfer(source_store=store_bnk, destination_store=store_deo))

    booking = Booking.objects.create(
        number="GS-BK-0001",
        vendor=vendor,
        brand=brand,
        season=Season.objects.create(code="gs-ss26", name="Search SS26"),
        destination_store=store_deo,
        status=Booking.Status.BOOKED,
    )

    store_role = Role.objects.create(
        code="store_manager",
        name="Store Manager (search test)",
        section_access=section_access_for("store_manager"),
    )
    store_user = User.objects.create_user(
        username="gs_store",
        password=TEST_PASSWORD,
        role=store_role,
        entity=entity,
        scope_type=ScopeType.STORE,
    )
    store_user.stores.add(store_deo)

    owner_role = Role.objects.create(
        code="owner", name="Owner (search test)", section_access=section_access_for("owner")
    )
    owner = User.objects.create_user(
        username="gs_owner",
        password=TEST_PASSWORD,
        role=owner_role,
        entity=entity,
        scope_type=ScopeType.ALL,
    )
    return {
        "store_deo": store_deo,
        "store_bnk": store_bnk,
        "brand": brand,
        "sku": sku,
        "grn_deo": grn_deo,
        "grn_bnk": grn_bnk,
        "adj_bnk": adj_bnk,
        "transfer": transfer,
        "booking": booking,
        "store_user": store_user,
        "owner": owner,
    }


# -- items -----------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_scanned_barcode_resolves_to_cohorts_with_own_stock(scaffold):
    """A scan answers with the SKU's cohorts, and the stock line counts only the
    caller's own store — 7 at DEO, never the 500 sitting at Banka."""
    body = _client(scaffold["store_user"]).get(f"{SEARCH}?q=GS-BAR-001").json()
    items = _results(body, "items")

    assert [i["title"] for i in items] == ["GS-BAR-001", "GS-BAR-001"]
    assert {i["subtitle"].split(" · ")[-1] for i in items} == {"SS26", "AW26"}
    assert all(i["exact"] for i in items)
    ss26 = next(i for i in items if i["subtitle"].endswith("SS26"))
    assert ss26["meta"] == "7 pcs at GS-DEO"
    assert "500" not in ss26["meta"]
    # The AW26 cohort has no stock anywhere the caller can see — say so plainly.
    aw26 = next(i for i in items if i["subtitle"].endswith("AW26"))
    assert aw26["meta"] == "No stock in your locations"
    assert ss26["to"] == "/stock?sku=GS-BAR-001"
    assert ss26["mrp_paise"] == 199900


@pytest.mark.django_db(transaction=True)
def test_free_text_finds_items_by_design_and_brand(scaffold):
    body = _client(scaffold["store_user"]).get(f"{SEARCH}?q=ASD1234").json()
    assert [i["title"] for i in _results(body, "items")] == ["GS-BAR-001", "GS-BAR-001"]

    body = _client(scaffold["store_user"]).get(f"{SEARCH}?q=ArrowSearch").json()
    assert _results(body, "items")
    brands = _results(body, "brands")
    assert [b["title"] for b in brands] == ["ArrowSearch"]
    # "Search brand" on the store person's sketch means *show me this brand's
    # stock* — not the brand master, which they may not open at all.
    assert brands[0]["to"] == "/stock?brand=ArrowSearch"


@pytest.mark.django_db(transaction=True)
def test_network_user_sees_stock_across_locations(scaffold):
    """The same scan, network scope: both stores roll up."""
    body = _client(scaffold["owner"]).get(f"{SEARCH}?q=GS-BAR-001").json()
    ss26 = next(i for i in _results(body, "items") if i["subtitle"].endswith("SS26"))
    assert ss26["meta"] == "507 pcs across 2 locations"


def _brand_manager(username: str, brands: list[Brand]) -> User:
    role, _ = Role.objects.get_or_create(
        code="brand_manager",
        defaults={
            "name": "Brand Manager (search test)",
            "section_access": section_access_for("brand_manager"),
        },
    )
    user = User.objects.create_user(
        username=username, password=TEST_PASSWORD, role=role, scope_type=ScopeType.BRAND
    )
    user.brands.set(brands)
    return user


@pytest.mark.django_db(transaction=True)
def test_search_shows_a_brand_manager_their_own_brands_stock(scaffold):
    """Their work spans every store, so the roll-up is the network one — the
    brand is the boundary, not the store."""
    manager = _brand_manager("gs_brand_own", [scaffold["brand"]])

    body = _client(manager).get(f"{SEARCH}?q=GS-BAR-001").json()
    ss26 = next(i for i in _results(body, "items") if i["subtitle"].endswith("SS26"))

    assert ss26["meta"] == "507 pcs across 2 locations"


@pytest.mark.django_db(transaction=True)
def test_search_never_reveals_stock_of_a_brand_that_is_not_yours(scaffold):
    """Scanning someone else's barcode may identify the item — that is master
    data — but must never say how much is sitting where."""
    other = Brand.objects.create(
        code="gs-mufti",
        name="MuftiSearch",
        ownership=Brand.Ownership.OWNED,
        return_terms=Brand.ReturnTerms.NONE,
    )
    manager = _brand_manager("gs_brand_other", [other])

    body = _client(manager).get(f"{SEARCH}?q=GS-BAR-001").json()
    ss26 = next(i for i in _results(body, "items") if i["subtitle"].endswith("SS26"))

    assert ss26["meta"] == "No stock in your locations"


@pytest.mark.django_db(transaction=True)
def test_search_does_not_hand_a_brand_manager_every_stores_documents(scaffold):
    """A voucher carries no brand, so nothing can prove it is theirs. Search must
    fail closed rather than treat "not store-scoped" as "entitled to all"."""
    manager = _brand_manager("gs_brand_docs", [scaffold["brand"]])
    grn = scaffold["grn_bnk"]

    body = _client(manager).get(f"{SEARCH}?q={grn.doc_number}").json()

    assert _results(body, "documents") == []


# -- documents -------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_voucher_number_finds_documents_across_types(scaffold):
    """One number, whatever type owns it — and it links to that type's screen."""
    owner = _client(scaffold["owner"])

    grn = scaffold["grn_deo"]
    hit = _results(owner.get(f"{SEARCH}?q={grn.doc_number}").json(), "documents")
    assert [(h["title"], h["to"]) for h in hit] == [(grn.doc_number, f"/receive/{grn.pk}")]
    assert hit[0]["subtitle"] == "Goods receipt · GS-DEO"
    assert hit[0]["exact"] is True

    transfer = scaffold["transfer"]
    hit = _results(owner.get(f"{SEARCH}?q={transfer.doc_number}").json(), "documents")
    assert hit[0]["to"] == f"/transfer/{transfer.pk}"
    assert hit[0]["subtitle"] == "Transfer · GS-BNK → GS-DEO"

    adj = scaffold["adj_bnk"]
    hit = _results(owner.get(f"{SEARCH}?q={adj.doc_number}").json(), "documents")
    assert hit[0]["to"] == f"/stock-count/adjustments/{adj.pk}"

    hit = _results(owner.get(f"{SEARCH}?q=GS-BK-0001").json(), "documents")
    assert hit[0]["to"] == f"/booking/{scaffold['booking'].pk}"
    assert hit[0]["subtitle"] == "Booking · ArrowSearch"


@pytest.mark.django_db(transaction=True)
def test_partial_number_matches_and_exact_floats_first(scaffold):
    """Typing the tail of a number still finds it; a full match sorts to the top."""
    owner = _client(scaffold["owner"])
    hits = _results(owner.get(f"{SEARCH}?q=GRN").json(), "documents")
    numbers = [h["title"] for h in hits]
    assert scaffold["grn_deo"].doc_number in numbers
    assert scaffold["grn_bnk"].doc_number in numbers

    hits = _results(owner.get(f"{SEARCH}?q={scaffold['grn_bnk'].doc_number}").json(), "documents")
    assert hits[0]["title"] == scaffold["grn_bnk"].doc_number


@pytest.mark.django_db(transaction=True)
def test_a_broad_query_shows_every_type_not_just_the_first(scaffold):
    """Every voucher number carries the store code, so "GS-" matches all types.
    They interleave — the first type must not eat the whole group and leave the
    rest invisible behind a "more matches" line."""
    hits = _results(_client(scaffold["owner"]).get(f"{SEARCH}?q=GS-").json(), "documents")
    kinds = {h["subtitle"].split(" · ")[0] for h in hits}
    assert {"Goods receipt", "Transfer", "Adjustment"} <= kinds


# -- the anti-leak line ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_store_scoped_user_never_sees_another_stores_documents(scaffold):
    """The Banka GRN and adjustment exist and the caller knows their numbers —
    search must still answer as if they did not."""
    store = _client(scaffold["store_user"])

    for doc in (scaffold["grn_bnk"], scaffold["adj_bnk"]):
        body = store.get(f"{SEARCH}?q={doc.doc_number}").json()
        assert _results(body, "documents") == []
        assert body["total"] == 0
        assert body["notes"]

    # Its own GRN is found — the gate is scope, not a broken query.
    body = store.get(f"{SEARCH}?q={scaffold['grn_deo'].doc_number}").json()
    assert len(_results(body, "documents")) == 1

    # A transfer touching the caller's store is visible from either end.
    body = store.get(f"{SEARCH}?q={scaffold['transfer'].doc_number}").json()
    assert len(_results(body, "documents")) == 1


@pytest.mark.django_db(transaction=True)
def test_section_capability_gates_document_types(scaffold):
    """A document type is invisible to a role the table gives no section for.

    The Data Steward owns masters and holds no Booking cell, so a booking is not
    theirs to find. Owner holds the section and finds it. (This used to be shown
    with the *store* person, whose Booking cell was "No" on the sheet — #130
    ratified it to `view`, so the store is no longer the example.)
    """
    steward_role = Role.objects.create(
        code="data_steward",
        name="Data Steward (search test)",
        section_access=section_access_for("data_steward"),
    )
    steward = User.objects.create_user(
        username="gs_steward",
        password=TEST_PASSWORD,
        role=steward_role,
        scope_type=ScopeType.ALL,
    )

    body = _client(steward).get(f"{SEARCH}?q=GS-BK-0001").json()
    assert _results(body, "documents") == []
    assert _results(_client(scaffold["owner"]).get(f"{SEARCH}?q=GS-BK-0001").json(), "documents")


@pytest.mark.django_db(transaction=True)
def test_the_store_finds_a_booking_headed_its_way(scaffold):
    """The ratified Booking cell reaches search too (#130).

    A capability is not a screen — it is the answer every surface reads, and
    search is the one that used to hide bookings from a store outright.
    """
    body = _client(scaffold["store_user"]).get(f"{SEARCH}?q=GS-BK-0001").json()
    assert len(_results(body, "documents")) == 1


@pytest.mark.django_db(transaction=True)
def test_user_with_no_role_finds_nothing(scaffold):
    """Fail-closed: no role means no sections, so search answers with nothing —
    not with everything."""
    orphan = User.objects.create_user(
        username="gs_orphan", password=TEST_PASSWORD, scope_type=ScopeType.STORE
    )
    body = _client(orphan).get(f"{SEARCH}?q=GS-BAR-001").json()
    assert body["groups"] == []
    assert body["total"] == 0

    body = _client(orphan).get(f"{SEARCH}?q={scaffold['grn_deo'].doc_number}").json()
    assert body["total"] == 0


@pytest.mark.django_db(transaction=True)
def test_search_requires_authentication(scaffold):
    assert APIClient().get(f"{SEARCH}?q=GS-BAR-001").status_code in (401, 403)


# -- honest emptiness ------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_no_match_says_so_and_names_what_is_not_searchable_yet(scaffold):
    body = _client(scaffold["owner"]).get(f"{SEARCH}?q=zzz-nothing-here").json()
    assert body["groups"] == []
    assert body["total"] == 0
    assert "Nothing found" in body["notes"][0]
    assert any("billing (POS)" in n for n in body["notes"])


@pytest.mark.django_db(transaction=True)
def test_short_and_empty_queries_are_answered_not_run(scaffold):
    for q in ("", "  ", "a"):
        body = _client(scaffold["owner"]).get(f"{SEARCH}?q={q}").json()
        assert body["groups"] == []
        assert body["notes"] == ["Type at least 2 characters, or scan a tag."]


@pytest.mark.django_db(transaction=True)
def test_stock_on_hand_accepts_the_sku_filter_search_links_to(scaffold):
    """The item result's destination has to actually filter, scope intact."""
    resp = _client(scaffold["store_user"]).get("/api/stockledger/on-hand?sku=GS-BAR-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["units_on_hand"] == 7
    assert {r["store_code"] for r in body["rows"]} == {"GS-DEO"}

    body = _client(scaffold["owner"]).get("/api/stockledger/on-hand?sku=GS-BAR-001").json()
    assert body["summary"]["units_on_hand"] == 507

    body = _client(scaffold["owner"]).get("/api/stockledger/on-hand?sku=NO-SUCH-BAR").json()
    assert body["summary"]["units_on_hand"] == 0

    # And the brand result's destination, likewise scoped.
    body = _client(scaffold["store_user"]).get("/api/stockledger/on-hand?brand=ArrowSearch").json()
    assert body["summary"]["units_on_hand"] == 7
