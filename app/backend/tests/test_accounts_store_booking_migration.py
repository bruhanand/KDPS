"""Migration 0008 — the store person's Booking cell, and its rollback (issue #130).

The forward direction opens Booking read-only on a *still-seeded* store role and
skips a cell a live admin has retuned. The reverse has to be as careful, from the
other end: it may only undo the exact cell it wrote, never an admin's own
``view``. So the pair is an identity — migrate, roll back, and the access matrix
is where it started.

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

MIGRATION = importlib.import_module("accounts.migrations.0008_store_booking_view")

SEEDED = MIGRATION.SEEDED_DEFAULT
OPENED = section_access_for("store_staff")["booking"]


def _role(code: str, booking: dict[str, str] | None) -> Role:
    access = section_access_for(code)
    if booking is None:
        access.pop("booking", None)
    else:
        access["booking"] = dict(booking)
    return Role.objects.create(code=code, name=code.title(), section_access=access)


def _run(direction) -> None:
    with connection.schema_editor(atomic=False) as schema_editor:
        direction(django_apps, schema_editor)


def _booking(role: Role) -> dict[str, str] | None:
    role.refresh_from_db()
    return role.section_access.get("booking")


def test_the_ratified_cell_is_read_only():
    """The correction opens a screen, not a create — the whole of the ruling."""
    assert OPENED["capability"] == "view"


@pytest.mark.parametrize("code", ["store_manager", "store_staff"])
def test_ordinary_round_trip_returns_to_the_seeded_cell(code):
    role = _role(code, SEEDED)

    _run(MIGRATION.open_booking)
    assert _booking(role) == OPENED  # the store gains the Booking screen

    _run(MIGRATION.close_booking)
    assert _booking(role) == SEEDED  # ...and gives it back on rollback


def test_rollback_keeps_an_admins_own_view_grant():
    admin_set = {"capability": "view", "label": "Bookings inbound"}
    role = _role("store_staff", admin_set)

    _run(MIGRATION.open_booking)
    assert _booking(role) == admin_set  # forward skips a retuned cell...

    _run(MIGRATION.close_booking)
    assert _booking(role) == admin_set  # ...so rollback has nothing of its own to undo


@pytest.mark.parametrize(
    "retuned",
    [
        {"capability": "operate", "label": "Create"},
        {"capability": "approve", "label": "Approve"},
        {"capability": "none", "label": "Withdrawn by HO"},
    ],
)
def test_forward_never_touches_a_retuned_cell(retuned):
    role = _role("store_manager", retuned)

    _run(MIGRATION.open_booking)

    assert _booking(role) == retuned


def test_no_other_role_is_touched():
    """The correction is the store persona's. Nobody else's cell moves."""
    codes = ("warehouse", "accounts", "ho_ops")
    before = {code: section_access_for(code)["booking"] for code in codes}
    others = {code: _role(code, before[code]) for code in codes}

    _run(MIGRATION.open_booking)
    _run(MIGRATION.close_booking)

    for code, role in others.items():
        assert _booking(role) == before[code], code


def test_a_role_with_no_booking_key_is_skipped():
    role = _role("store_staff", None)

    _run(MIGRATION.open_booking)

    assert _booking(role) is None  # 0004's job, not this one's
