"""Phase C golden test — `core.post_entries` is the balanced-or-fail GL writer.

Every posting fans out into ≥2 legs whose signed paise sum to zero (debit +,
credit −); an unbalanced set writes nothing; the GL is append-only and TRUNCATE
is forbidden at the DB. These are the kernel invariants the money slice rests on.
"""

from __future__ import annotations

import pytest
from django.db import DatabaseError, connection, transaction

from accounts.models import User
from core.gl import GLAccount, GLEntry, account_balance, trial_balance
from core.posting import PostingError, PostingRef, UnbalancedError, cr, dr, post_entries

REF = PostingRef(doc_type="PT", doc_number="26-27/RAN-WH/PT/1")
TABLE = GLEntry._meta.db_table


def _head_office_actor() -> User:
    return User.objects.create(
        username="gl-head-office", full_name="GL Head Office", scope_type="all"
    )


@pytest.mark.django_db
def test_balanced_posting_writes_all_legs_and_ties_to_zero() -> None:
    rows = post_entries(
        REF,
        [dr(GLAccount.INVENTORY, 12000), cr(GLAccount.VENDOR_PAYABLE, 12000)],
        posted_by=_head_office_actor(),
    )
    assert len(rows) == 2
    assert GLEntry.objects.filter(doc_number=REF.doc_number).count() == 2
    assert account_balance(GLAccount.INVENTORY) == 12000
    assert account_balance(GLAccount.VENDOR_PAYABLE) == -12000
    assert trial_balance() == 0  # the books tie


@pytest.mark.django_db
def test_unbalanced_posting_raises_and_writes_nothing() -> None:
    with pytest.raises(UnbalancedError):
        post_entries(REF, [dr(GLAccount.INVENTORY, 12000), cr(GLAccount.VENDOR_PAYABLE, 11999)])
    assert GLEntry.objects.count() == 0  # all-or-none: a half-posting never lands


@pytest.mark.django_db
def test_a_single_leg_is_rejected() -> None:
    with pytest.raises(UnbalancedError):
        post_entries(REF, [dr(GLAccount.INVENTORY, 100)])
    assert GLEntry.objects.count() == 0


@pytest.mark.django_db
def test_a_multi_leg_posting_with_gst_ties() -> None:
    rows = post_entries(
        REF,
        [
            dr(GLAccount.INVENTORY, 10000),
            dr(GLAccount.INPUT_GST, 500),
            cr(GLAccount.VENDOR_PAYABLE, 10500),
        ],
        posted_by=_head_office_actor(),
    )
    assert len(rows) == 3
    assert trial_balance() == 0


@pytest.mark.django_db
def test_a_doc_without_a_number_cannot_post() -> None:
    with pytest.raises(PostingError):
        post_entries(
            PostingRef(doc_type="PT", doc_number=""),
            [dr(GLAccount.INVENTORY, 100), cr(GLAccount.CASH, 100)],
        )
    assert GLEntry.objects.count() == 0


@pytest.mark.django_db
def test_dimensions_are_snapshotted_onto_each_leg() -> None:
    rows = post_entries(
        REF,
        [
            dr(GLAccount.INVENTORY, 5000, brand="Peter England", season="SS-26"),
            cr(GLAccount.VENDOR_PAYABLE, 5000, party_type="vendor", party_code="V-001"),
        ],
        posted_by=_head_office_actor(),
    )
    inv = next(r for r in rows if r.account == GLAccount.INVENTORY)
    pay = next(r for r in rows if r.account == GLAccount.VENDOR_PAYABLE)
    assert inv.brand == "Peter England" and inv.season == "SS-26"
    assert pay.party_type == "vendor" and pay.party_code == "V-001"


@pytest.mark.django_db
def test_gl_is_append_only_raw_update_forbidden_even_for_superuser() -> None:
    post_entries(
        REF,
        [dr(GLAccount.INVENTORY, 100), cr(GLAccount.CASH, 100)],
        posted_by=_head_office_actor(),
    )
    row = GLEntry.objects.first()
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"UPDATE {TABLE} SET amount = 999 WHERE id = %s", [row.pk])
    assert GLEntry.objects.get(pk=row.pk).amount == row.amount


@pytest.mark.django_db
def test_truncate_is_forbidden_by_the_db_trigger() -> None:
    post_entries(
        REF,
        [dr(GLAccount.INVENTORY, 100), cr(GLAccount.CASH, 100)],
        posted_by=_head_office_actor(),
    )
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cur:
            # Disable the test-only flush escape hatch to exercise the real guard.
            cur.execute("SET LOCAL kdps.allow_truncate = 'off'")
            cur.execute(f"TRUNCATE {TABLE}")
    assert GLEntry.objects.count() == 2  # untouched
