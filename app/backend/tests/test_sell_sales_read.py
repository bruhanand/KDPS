"""Finding a bill again: customer search and reprint (#177, contract E1/E2).

A customer comes back with a mobile number, a name, or a scrap of paper with a
bill number on it, and the counter has to find their bill. That is the whole
feature, and the two things worth proving about it are that it finds the bill
and that it shows nobody else's.
"""

from __future__ import annotations

import pytest
from _sell import (
    FY,
    MRP_PAISE,
    SALES_URL,
    bill_payload,
    build_cashier,
    build_piece,
    build_salesman,
    build_store,
    client_for,
)

from sell.models import Sale


def test_sales_read_shapes_are_published_in_the_openapi_contract():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)

    listing = schema["paths"]["/api/sell/sales"]["get"]["responses"]["200"]
    detail = schema["paths"]["/api/sell/sales/{doc_number}"]["get"]["responses"]["200"]
    assert listing["content"]["application/json"]["schema"]["items"]["$ref"].endswith("/SaleRow")
    assert detail["content"]["application/json"]["schema"]["$ref"].endswith("/SaleRead")


@pytest.fixture
def counter(db):
    store = build_store()
    build_piece()
    cashier = build_cashier(store)
    client = client_for(cashier)
    salesman = build_salesman(store)
    response = client.post(SALES_URL, bill_payload(store, salesman, till_seq=1), format="json")
    assert response.status_code == 201
    return {
        "store": store,
        "cashier": cashier,
        "salesman": salesman,
        "client": client,
        "sale": Sale.objects.get(pk=response.json()["id"]),
    }


def test_a_search_with_no_criterion_is_refused_rather_than_dumping_the_day(counter):
    response = counter["client"].get(SALES_URL)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION"


@pytest.mark.parametrize(
    "query",
    ["mobile=9876543210", "name=sharma", "doc=1", f"doc={FY}/SEL-DEO/SAL/1"],
)
def test_every_way_a_customer_identifies_their_bill_finds_it(counter, query):
    response = counter["client"].get(f"{SALES_URL}?{query}")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["doc_number"] == counter["sale"].doc_number
    assert rows[0]["net_paise"] == MRP_PAISE
    assert rows[0]["lines_summary"] == "1 piece · MUFTI"


def test_a_search_that_matches_nothing_says_so_quietly(counter):
    response = counter["client"].get(f"{SALES_URL}?mobile=0000000000")

    assert response.status_code == 200
    assert response.json() == []


def test_the_detail_is_the_whole_bill_for_reprint(counter):
    response = counter["client"].get(f"{SALES_URL}/{counter['sale'].doc_number}")

    assert response.status_code == 200
    body = response.json()
    assert body["doc_number"] == counter["sale"].doc_number
    assert body["store_code"] == counter["store"].code
    # The paper is a tax invoice, and the screen that reprints it has no till
    # behind it to borrow a registration from (#185).
    assert body["store_gstin"] == counter["store"].gstin.gstin
    assert body["lines"][0]["barcode"] == "8901000000011"
    assert body["lines"][0]["salesman_code"] == "ALIE"
    assert body["tenders"][0]["mode"] == "cash"
    assert body["flags"] == []


def test_another_stores_bill_is_not_findable_and_answers_as_missing(db):
    """Read scope has failed open in this codebase before, so both doors are
    checked - and the detail answers 404, never 403: a 403 would confirm the
    bill exists."""
    home = build_store()
    build_piece()
    elsewhere = build_store(code="SEL-RAN", state="20")
    seller = build_cashier(home, username="sell_home")
    salesman = build_salesman(home)
    created = client_for(seller).post(
        SALES_URL, bill_payload(home, salesman, till_seq=1), format="json"
    )
    assert created.status_code == 201
    doc_number = created.json()["doc_number"]

    stranger = client_for(build_cashier(elsewhere, username="sell_elsewhere"))

    assert stranger.get(f"{SALES_URL}?mobile=9876543210").json() == []
    detail = stranger.get(f"{SALES_URL}/{doc_number}")
    assert detail.status_code == 404
    assert detail.json()["code"] == "NOT_FOUND"


def test_a_person_with_no_selling_rights_reaches_none_of_it(db):
    """The section gate, not the scope: a warehouse seat holds `sell: none`."""
    from _creds import TEST_PASSWORD
    from _rbac import make_role

    from accounts.models import ScopeType, User

    store = build_store()
    build_piece()
    warehouse = User.objects.create_user(
        username="sell_warehouse",
        password=TEST_PASSWORD,
        role=make_role("warehouse", "Warehouse (sell tests)"),
        scope_type=ScopeType.STORE,
    )
    warehouse.stores.add(store)
    client = client_for(warehouse)

    assert client.get(f"{SALES_URL}?mobile=9876543210").status_code == 403
    assert client.post(SALES_URL, {}, format="json").status_code == 403


def test_a_reader_may_read_but_not_bill(db):
    """`sell: view` - an accounts seat reprints a bill and cannot write one."""
    from _creds import TEST_PASSWORD
    from _rbac import make_role

    from accounts.models import ScopeType, User

    store = build_store()
    build_piece()
    reader = User.objects.create_user(
        username="sell_reader",
        password=TEST_PASSWORD,
        role=make_role("accounts", "Accounts (sell tests)"),
        scope_type=ScopeType.STORE,
    )
    reader.stores.add(store)
    client = client_for(reader)

    assert client.get(f"{SALES_URL}?mobile=9876543210").status_code == 200
    assert client.post(SALES_URL, {}, format="json").status_code == 403


def test_recent_bills_returns_newest_first_with_pieces_and_salespeople(counter):
    client = counter["client"]
    store = counter["store"]
    salesman = counter["salesman"]

    # Post a second bill
    client.post(SALES_URL, bill_payload(store, salesman, till_seq=2), format="json")

    response = client.get(f"{SALES_URL}?recent=3")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    # Newest first: seq 2 then seq 1
    assert rows[0]["doc_number"].endswith("/2")
    assert rows[1]["doc_number"].endswith("/1")
    # Check extra fields for recent-bill pick list
    assert "pieces" in rows[0]
    assert rows[0]["pieces"] == 1
    assert "salespeople" in rows[0]
    assert isinstance(rows[0]["salespeople"], list)


def test_recent_bills_query_validation(counter):
    client = counter["client"]

    # Combined with search parameter -> 400
    res = client.get(f"{SALES_URL}?recent=3&mobile=9876543210")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION"

    # Out of range n -> 400
    res_zero = client.get(f"{SALES_URL}?recent=0")
    assert res_zero.status_code == 400

    res_large = client.get(f"{SALES_URL}?recent=15")
    assert res_large.status_code == 400
