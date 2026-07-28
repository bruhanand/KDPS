"""Migration 0011 - the Staff section becomes HRMS, and the rollback (issue #118).

Unlike 0006/0008, this migration is not "only if still the seeded default" -
it is a key rename, so whatever the cell currently holds (seeded default *or*
a live admin's own retuning) moves with it. The reverse renames the key back,
carrying the same value.

The functions are called directly (as ``test_accounts_staff_manage_migration``
does for 0006); the schema is unchanged by this migration, so running the data
functions is the whole of it.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection

from accounts.models import Role
from accounts.rbac_matrix import section_access_for

pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("accounts.migrations.0011_rename_staff_section_to_hrms")


def _role(code: str, staff: dict[str, str] | None) -> Role:
    access = section_access_for(code)
    access.pop("hrms", None)  # simulate DB state before this migration ever ran
    if staff is None:
        access.pop("staff", None)
    else:
        access["staff"] = dict(staff)
    return Role.objects.create(code=code, name=code.title(), section_access=access)


def _run(direction) -> None:
    with connection.schema_editor(atomic=False) as schema_editor:
        direction(django_apps, schema_editor)


def _cell(role: Role, key: str) -> dict[str, str] | None:
    role.refresh_from_db()
    return role.section_access.get(key)


def test_the_seeded_cell_moves_from_staff_to_hrms():
    role = _role("warehouse", {"capability": "operate", "label": "Own attendance (derived)"})

    _run(MIGRATION.rename_to_hrms)

    assert _cell(role, "staff") is None
    assert _cell(role, "hrms") == {"capability": "operate", "label": "Own attendance (derived)"}


def test_round_trip_is_an_identity():
    seeded = {"capability": "operate", "label": "Own attendance (derived)"}
    role = _role("warehouse", seeded)

    _run(MIGRATION.rename_to_hrms)
    _run(MIGRATION.rename_to_staff)

    assert _cell(role, "staff") == seeded
    assert _cell(role, "hrms") is None


def test_a_live_admins_retuned_cell_rides_along_unchanged():
    """The rename carries an override, it does not reset it (unlike 0006/0008)."""
    admin_set = {"capability": "approve", "label": "Approve leave"}
    role = _role("store_manager", admin_set)

    _run(MIGRATION.rename_to_hrms)
    assert _cell(role, "hrms") == admin_set

    _run(MIGRATION.rename_to_staff)
    assert _cell(role, "staff") == admin_set


def test_a_role_with_no_staff_key_is_left_alone():
    role = _role("store_manager", None)

    _run(MIGRATION.rename_to_hrms)

    assert _cell(role, "staff") is None
    assert _cell(role, "hrms") is None


def test_every_role_is_touched_not_just_store_manager():
    """Unlike 0006, this rename is not confined to one role - it is the whole table."""
    codes = ("owner", "store_manager", "store_staff", "warehouse", "accounts")
    roles = {code: _role(code, {"capability": "view", "label": "x"}) for code in codes}

    _run(MIGRATION.rename_to_hrms)

    for code, role in roles.items():
        assert _cell(role, "hrms") == {"capability": "view", "label": "x"}, code
