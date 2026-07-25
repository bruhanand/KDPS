"""Migration 0006 — the store manager's Staff grant, and its rollback (issue #100).

The forward direction lifts a *still-seeded* ``store_manager`` from
``staff: operate`` to ``staff: manage``, and skips a cell a live admin has
retuned. The reverse has to be as careful, from the other end: it may only undo
the exact cell it wrote, never an admin's own ``manage``. So the pair is an
identity — migrate, roll back, and the access matrix is where it started.

The functions are called directly (as ``tests/test_inbound_pt_authoring.py``
does for ``inbound.0005``); the schema is unchanged by this migration, so
running the data functions is the whole of it.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection

from accounts.models import Role
from accounts.rbac_matrix import MATRIX, section_access_for

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("accounts.migrations.0006_store_manager_staff_manage")

SEEDED = dict(zip(("capability", "label"), MATRIX["store_person"]["staff"], strict=True))
GRANTED = section_access_for("store_manager")["staff"]


def _role(code: str, staff: dict[str, str] | None) -> Role:
    access = section_access_for(code)
    if staff is None:
        access.pop("staff", None)
    else:
        access["staff"] = dict(staff)
    return Role.objects.create(code=code, name=code.title(), section_access=access)


def _run(direction) -> None:
    with connection.schema_editor(atomic=False) as schema_editor:
        direction(django_apps, schema_editor)


def _staff(role: Role) -> dict[str, str]:
    role.refresh_from_db()
    return role.section_access.get("staff")


def test_ordinary_round_trip_returns_to_the_seeded_cell():
    role = _role("store_manager", SEEDED)

    _run(MIGRATION.grant_members)
    assert _staff(role) == GRANTED  # manager gains Member Details

    _run(MIGRATION.revoke_members)
    assert _staff(role) == SEEDED  # ...and gives it back on rollback


def test_rollback_keeps_an_admins_own_manage_grant():
    admin_set = {"capability": "manage", "label": "Members + attendance"}
    role = _role("store_manager", admin_set)

    _run(MIGRATION.grant_members)
    assert _staff(role) == admin_set  # forward skips a retuned cell...

    _run(MIGRATION.revoke_members)
    assert _staff(role) == admin_set  # ...so rollback has nothing of its own to undo


@pytest.mark.parametrize(
    "retuned",
    [
        {"capability": "view", "label": "Read only"},
        {"capability": "approve", "label": "Approve leave"},
        {"capability": "none", "label": "No"},
    ],
)
def test_forward_never_touches_a_retuned_cell(retuned):
    role = _role("store_manager", retuned)

    _run(MIGRATION.grant_members)

    assert _staff(role) == retuned


def test_the_cashier_is_left_alone_in_both_directions():
    cashier = _role("store_staff", SEEDED)

    _run(MIGRATION.grant_members)
    assert _staff(cashier) == SEEDED

    _run(MIGRATION.revoke_members)
    assert _staff(cashier) == SEEDED


def test_a_role_with_no_staff_key_is_skipped():
    role = _role("store_manager", None)

    _run(MIGRATION.grant_members)

    assert _staff(role) is None  # 0005's job, not this one's
