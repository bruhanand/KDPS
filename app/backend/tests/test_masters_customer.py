"""masters.Customer — KDPS's first customer master (#242).

One row per mobile number, born two ways: the accept pipeline's own upsert
(proven against a live bill in `test_sell_sale_accept.py`) and this suite's
`backfill_customers`, which seeds the table from bills already on the books
before the pipeline existed. Both read the same `sell.services.customers`
rules — normalise the mobile to digits, latest non-blank name wins, gstin
fills when supplied — so this suite proves those rules once, directly.
"""

from __future__ import annotations

import pytest
from _sell import (
    SALES_URL,
    bill_payload,
    build_cashier,
    build_piece,
    build_salesman,
    build_store,
    client_for,
    stock_in,
)
from django.db import connection
from django.test.utils import CaptureQueriesContext

from masters.models import Customer
from sell.models import Sale
from sell.services.customers import backfill_customers, normalise_mobile, upsert_customer


@pytest.fixture
def counter(db):
    store = build_store()
    build_piece()
    cashier = build_cashier(store)
    stock_in(store, 5)
    return {
        "store": store,
        "salesman": build_salesman(store),
        "client": client_for(cashier),
    }


def _bill(counter, till_seq: int, **overrides) -> None:
    payload = bill_payload(counter["store"], counter["salesman"], till_seq=till_seq, **overrides)
    response = counter["client"].post(SALES_URL, payload, format="json")
    assert response.status_code == 201, response.json()


# --- the backfill ------------------------------------------------------


def test_backfill_seeds_one_row_per_mobile(counter):
    _bill(counter, 1, customer={"name": "Mrs Sharma", "mobile": "9876543210", "gstin": ""})
    _bill(counter, 2, customer={"name": "Mr Verma", "mobile": "9123456780", "gstin": ""})

    backfill_customers(Sale, Customer)

    assert Customer.objects.count() == 2
    assert set(Customer.objects.values_list("mobile", flat=True)) == {"9876543210", "9123456780"}


def test_backfill_takes_the_newest_bills_name(counter):
    _bill(
        counter,
        1,
        customer={"name": "Mrs Sharma", "mobile": "9876543210", "gstin": ""},
        billed_at="2026-07-30T12:31:00Z",
    )
    _bill(
        counter,
        2,
        customer={"name": "Mrs S Sharma", "mobile": "9876543210", "gstin": ""},
        billed_at="2026-07-30T12:35:00Z",
    )

    backfill_customers(Sale, Customer)

    assert Customer.objects.get(mobile="9876543210").name == "Mrs S Sharma"


def test_backfill_keeps_the_older_name_when_the_newest_bill_is_blank(counter):
    _bill(
        counter,
        1,
        customer={"name": "Mrs Sharma", "mobile": "9876543210", "gstin": ""},
        billed_at="2026-07-30T12:31:00Z",
    )
    _bill(
        counter,
        2,
        customer={"name": "", "mobile": "9876543210", "gstin": ""},
        billed_at="2026-07-30T12:35:00Z",
    )

    backfill_customers(Sale, Customer)

    # The newest bill skipped the name field - the older, non-blank name wins
    # (db-design.md's backfill algorithm and AC1 both say "non-blank").
    assert Customer.objects.get(mobile="9876543210").name == "Mrs Sharma"


def test_backfill_takes_the_newest_b2b_bills_gstin(counter):
    _bill(
        counter,
        1,
        customer={"name": "Mrs Sharma", "mobile": "9876543210", "gstin": "10AABCU9603R1Z2"},
        billed_at="2026-07-30T12:31:00Z",
    )
    _bill(
        counter,
        2,
        customer={"name": "Mrs Sharma", "mobile": "9876543210", "gstin": ""},
        billed_at="2026-07-30T12:35:00Z",
    )

    backfill_customers(Sale, Customer)

    # The later bill carried no gstin - it never wipes the one a B2B bill gave.
    assert Customer.objects.get(mobile="9876543210").gstin == "10AABCU9603R1Z2"


def test_backfill_skips_blank_mobiles(counter):
    _bill(counter, 1, customer={"name": "Walk-in", "mobile": "", "gstin": ""})

    backfill_customers(Sale, Customer)

    assert Customer.objects.count() == 0


def test_backfill_is_idempotent(counter):
    _bill(counter, 1, customer={"name": "Mrs Sharma", "mobile": "9876543210", "gstin": ""})
    backfill_customers(Sale, Customer)
    before = list(
        Customer.objects.values("id", "mobile", "name", "gstin", "created_at", "updated_at")
    )

    backfill_customers(Sale, Customer)

    after = list(
        Customer.objects.values("id", "mobile", "name", "gstin", "created_at", "updated_at")
    )
    assert after == before


# --- the shared rules, direct -------------------------------------------


def test_normalise_mobile_collapses_country_code_and_leading_zero():
    assert normalise_mobile("+91 98765-43210") == "9876543210"
    assert normalise_mobile("09876543210") == "9876543210"
    assert normalise_mobile("9876543210") == "9876543210"
    assert normalise_mobile("") == ""


def test_upsert_customer_collapses_mobile_spellings_to_one_row(db):
    upsert_customer(Customer, mobile="9876543210", name="Mrs Sharma", gstin="")
    upsert_customer(Customer, mobile="+91 98765-43210", name="Mrs Sharma", gstin="")
    upsert_customer(Customer, mobile="09876543210", name="Mrs Sharma", gstin="")

    assert Customer.objects.count() == 1
    assert Customer.objects.get().mobile == "9876543210"


def test_upsert_customer_skips_a_blank_mobile(db):
    upsert_customer(Customer, mobile="   ", name="Nobody", gstin="")

    assert Customer.objects.count() == 0


def test_upsert_customer_never_wipes_a_stored_name_or_gstin(db):
    upsert_customer(Customer, mobile="9876543210", name="Mrs Sharma", gstin="10AABCU9603R1Z2")

    upsert_customer(Customer, mobile="9876543210", name="", gstin="")

    customer = Customer.objects.get(mobile="9876543210")
    assert customer.name == "Mrs Sharma"
    assert customer.gstin == "10AABCU9603R1Z2"


def test_upsert_customer_overwrites_only_when_non_blank_and_different(db):
    upsert_customer(Customer, mobile="9876543210", name="Mrs Sharma", gstin="")

    upsert_customer(Customer, mobile="9876543210", name="Mrs Sharma", gstin="10AABCU9603R1Z2")

    customer = Customer.objects.get(mobile="9876543210")
    assert customer.name == "Mrs Sharma"
    assert customer.gstin == "10AABCU9603R1Z2"


def test_upsert_customer_stores_the_gstin_upper_cased(db):
    """The column says 'normalised uppercase'; the upsert must make that true
    for any caller, not only for the accept path that happens to normalise
    upstream."""
    upsert_customer(Customer, mobile="9876543210", name="Mrs Sharma", gstin=" 10aabcu9603r1z2 ")

    assert Customer.objects.get(mobile="9876543210").gstin == "10AABCU9603R1Z2"


def test_a_bill_that_only_renames_never_writes_the_gstin_column(db):
    """Two tills bill the same mobile at once, and the losing one holds a row it
    read before the winner committed. Writing back every field would push that
    stale blank over the gstin the other bill had just supplied, so a bill must
    only ever write the columns it actually changes."""
    upsert_customer(Customer, mobile="9876543210", name="Mrs Sharma", gstin="10AABCU9603R1Z2")

    with CaptureQueriesContext(connection) as queries:
        upsert_customer(Customer, mobile="9876543210", name="Mrs S Sharma", gstin="")

    updates = [
        q["sql"] for q in queries.captured_queries if q["sql"].lstrip().upper().startswith("UPDATE")
    ]
    assert len(updates) == 1
    assert "gstin" not in updates[0]
    assert Customer.objects.get(mobile="9876543210").gstin == "10AABCU9603R1Z2"
