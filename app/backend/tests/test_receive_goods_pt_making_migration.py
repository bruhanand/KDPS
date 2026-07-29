"""Migration 0013 - the warehouse's raised rung, the store's retitled cell,
and their rollback (issue #119).

The forward direction moves two cells on a still-seeded role and skips either
one a live admin has already retuned. The reverse has to be as careful, from
the other end: it may only undo the exact cell it wrote, never an admin's own
grant. So the pair is an identity - migrate, roll back, and the access matrix
is where it started.

The functions are called directly (as 0008's own test does); the schema is
unchanged by this migration, so running the data functions is the whole of it.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection

from accounts.models import Role
from accounts.rbac_matrix import section_access_for

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("accounts.migrations.0013_receive_goods_pt_making_rung")

WAREHOUSE_SEEDED = MIGRATION.WAREHOUSE_SEEDED_DEFAULT
WAREHOUSE_RAISED = section_access_for("warehouse")["receive_goods"]
STORE_SEEDED = MIGRATION.STORE_SEEDED_DEFAULT
STORE_RETITLED = section_access_for("store_staff")["receive_goods"]


def _role(code: str, receive_goods: dict[str, str] | None) -> Role:
    access = section_access_for(code)
    if receive_goods is None:
        access.pop("receive_goods", None)
    else:
        access["receive_goods"] = dict(receive_goods)
    return Role.objects.create(code=code, name=code.title(), section_access=access)


def _run(direction) -> None:
    with connection.schema_editor(atomic=False) as schema_editor:
        direction(django_apps, schema_editor)


def _cell(role: Role) -> dict[str, str] | None:
    role.refresh_from_db()
    return role.section_access.get("receive_goods")


def test_the_ratified_cells_move_making_but_not_receiving():
    """The rung rises for the warehouse; the store keeps its rung and loses a
    word, not a capability."""
    assert WAREHOUSE_RAISED["capability"] == "approve"
    assert STORE_RETITLED["capability"] == "operate"
    assert STORE_RETITLED["label"] == "Receive + bill upload (own store)"


def test_ordinary_round_trip_returns_to_the_seeded_cells():
    warehouse = _role("warehouse", WAREHOUSE_SEEDED)
    manager = _role("store_manager", STORE_SEEDED)
    cashier = _role("store_staff", STORE_SEEDED)

    _run(MIGRATION.raise_warehouse_and_retitle_store)
    assert _cell(warehouse) == WAREHOUSE_RAISED
    assert _cell(manager) == STORE_RETITLED
    assert _cell(cashier) == STORE_RETITLED

    _run(MIGRATION.lower_warehouse_and_restore_store_label)
    assert _cell(warehouse) == WAREHOUSE_SEEDED
    assert _cell(manager) == STORE_SEEDED
    assert _cell(cashier) == STORE_SEEDED


def test_rollback_keeps_an_admins_own_grant():
    admin_warehouse = {"capability": "manage", "label": "Full control, retuned by hand"}
    admin_store = {"capability": "none", "label": "Withdrawn by HO"}
    warehouse = _role("warehouse", admin_warehouse)
    cashier = _role("store_staff", admin_store)

    _run(MIGRATION.raise_warehouse_and_retitle_store)
    assert _cell(warehouse) == admin_warehouse  # forward skips a retuned cell...
    assert _cell(cashier) == admin_store

    _run(MIGRATION.lower_warehouse_and_restore_store_label)
    assert _cell(warehouse) == admin_warehouse  # ...so rollback has nothing of its own to undo
    assert _cell(cashier) == admin_store


@pytest.mark.parametrize(
    "retuned",
    [
        {"capability": "manage", "label": "Full"},
        {"capability": "view", "label": "View only"},
        {"capability": "none", "label": "No"},
    ],
)
def test_forward_never_touches_a_retuned_cell(retuned):
    warehouse = _role("warehouse", retuned)
    store = _role("store_manager", retuned)

    _run(MIGRATION.raise_warehouse_and_retitle_store)

    assert _cell(warehouse) == retuned
    assert _cell(store) == retuned


def test_no_other_role_is_touched():
    """The correction is the warehouse's and the store persona's. Nobody
    else's cell moves."""
    codes = ("owner", "accounts", "ho_ops", "it_admin")
    before = {code: section_access_for(code)["receive_goods"] for code in codes}
    others = {code: _role(code, before[code]) for code in codes}

    _run(MIGRATION.raise_warehouse_and_retitle_store)
    _run(MIGRATION.lower_warehouse_and_restore_store_label)

    for code, role in others.items():
        assert _cell(role) == before[code], code


def test_a_role_with_no_receive_goods_key_is_skipped():
    warehouse = _role("warehouse", None)
    store = _role("store_staff", None)

    _run(MIGRATION.raise_warehouse_and_retitle_store)

    assert _cell(warehouse) is None  # 0004's job, not this one's
    assert _cell(store) is None
