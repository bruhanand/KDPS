"""The two head-office discount dials (#271)."""

from __future__ import annotations

from decimal import Decimal

from _creds import TEST_PASSWORD
from _rbac import make_role
from _sell import build_cashier, build_store, client_for

from accounts.models import ScopeType, User
from sell.models import SellPolicy

URL = "/api/sell/policy"


def test_policy_is_readable_at_sell_view_but_writable_only_at_sell_manage(db):
    store = build_store()
    cashier = build_cashier(store)
    admin = User.objects.create_user(
        username="policy_admin",
        password=TEST_PASSWORD,
        role=make_role("it_admin", "IT admin"),
        scope_type=ScopeType.ALL,
    )

    assert client_for(cashier).get(URL).json() == {
        "manual_discount_cap_percent": "10.00",
        "manual_discount_on_offer_lines": False,
    }
    assert client_for(cashier).put(URL, {}, format="json").status_code == 403

    saved = client_for(admin).put(
        URL,
        {
            "manual_discount_cap_percent": "7.50",
            "manual_discount_on_offer_lines": True,
        },
        format="json",
    )

    assert saved.status_code == 200
    assert saved.json() == {
        "manual_discount_cap_percent": "7.50",
        "manual_discount_on_offer_lines": True,
    }
    policy = SellPolicy.current()
    assert policy.manual_discount_cap_percent == Decimal("7.50")
    assert policy.manual_discount_on_offer_lines is True


def test_policy_rejects_a_partial_or_noncanonical_dial_value(db):
    admin = User.objects.create_user(
        username="policy_validation_admin",
        password=TEST_PASSWORD,
        role=make_role("it_admin", "IT admin"),
        scope_type=ScopeType.ALL,
    )
    client = client_for(admin)

    for body in (
        {"manual_discount_cap_percent": "10.00"},
        {"manual_discount_cap_percent": "10", "manual_discount_on_offer_lines": False},
        {"manual_discount_cap_percent": "100.01", "manual_discount_on_offer_lines": False},
        {"manual_discount_cap_percent": "10.00", "manual_discount_on_offer_lines": "false"},
    ):
        response = client.put(URL, body, format="json")
        assert response.status_code == 400
        assert response.json()["code"] == "VALIDATION"
