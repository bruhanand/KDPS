"""The standalone writer retired; its historical rows remain readable (#273)."""

from _sell import (
    FY,
    MRP_PAISE,
    SALES_URL,
    bill_payload,
    build_cashier,
    build_manager,
    build_piece,
    build_salesman,
    build_store,
    client_for,
)
from django.utils import timezone

from sell.models import Return, ReturnLine, Sale
from sell.services.refunds import returned_so_far
from sell.services.returns import returns_by_employee


def test_plain_return_endpoint_is_retired(db):
    store = build_store()
    client = client_for(build_cashier(store))

    response = client.post("/api/sell/returns", {}, format="json")

    assert response.status_code == 404


def test_historical_plain_returns_still_reduce_the_bill_returnable_quantity(db):
    store = build_store()
    build_piece()
    cashier = build_cashier(store)
    manager = build_manager(store)
    salesman = build_salesman(store)
    client = client_for(cashier)
    created = client.post(
        SALES_URL,
        bill_payload(store, salesman, till_seq=1),
        format="json",
    )
    assert created.status_code == 201
    sale = Sale.objects.get(pk=created.json()["id"])
    original = sale.lines.get(line_no=1)
    historical = Return.objects.create(
        store=store,
        fy=FY,
        original_sale=sale,
        returned_at=timezone.now(),
        customer_name=sale.customer_name,
        customer_mobile=sale.customer_mobile,
        created_by=cashier,
        override_by=manager,
    )
    ReturnLine.objects.create(
        return_doc=historical,
        line_no=1,
        original_line=original,
        barcode=original.barcode,
        season=original.season,
        design=original.design,
        color=original.color,
        size=original.size,
        brand=original.brand,
        item=original.item,
        hsn=original.hsn,
        qty=1,
        refund_paise=MRP_PAISE,
        gst_rate=original.gst_rate,
        gst_paise=original.gst_paise,
        reason="historical",
        condition="good",
    )
    historical.post()

    assert returned_so_far(original) == (1, MRP_PAISE)
    detail = client.get(f"{SALES_URL}/{sale.doc_number}")
    assert detail.status_code == 200
    assert detail.json()["lines"][0]["returned_qty"] == 1
    assert detail.json()["lines"][0]["returned_paise"] == MRP_PAISE
    assert returns_by_employee(store, timezone.localdate()) == [
        {
            "taken_by": cashier.username,
            "approved_by": manager.username,
            "returns": 1,
            "value_paise": MRP_PAISE,
        }
    ]
