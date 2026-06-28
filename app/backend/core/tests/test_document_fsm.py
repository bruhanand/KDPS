"""K2 golden test — the docstatus FSM is strictly enforced.

`draft → submitted → cancelled`, one `post()` per doc. No skipped or cyclic
transitions; a posted doc cannot be edited or re-posted; cancel is a reversing
*transition*, never a row delete. The DB trigger is the load-bearing guard (it
binds even raw SQL); the ORM raises the early, clean error.
"""

from __future__ import annotations

import pytest
from django.db import DatabaseError, connection, transaction

from core.documents import (
    DocStatus,
    DocumentEditError,
    DocumentProbe,
    DocumentTransitionError,
    VoucherSeries,
)

FY = "26-27"
STORE = "DEO"
DOC_TYPE = "SAL"


@pytest.fixture
def series() -> VoucherSeries:
    return VoucherSeries.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)


def _draft() -> DocumentProbe:
    return DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)


@pytest.mark.django_db
def test_a_new_document_starts_in_draft_with_no_number(series: VoucherSeries) -> None:
    doc = _draft()
    assert doc.docstatus == DocStatus.DRAFT
    assert doc.doc_number is None  # the business number is minted at post, gap-free


@pytest.mark.django_db
def test_post_moves_draft_to_submitted_and_mints_a_number(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    assert doc.docstatus == DocStatus.SUBMITTED
    assert doc.doc_number == "26-27/DEO/1"
    assert doc.series_id == series.pk


@pytest.mark.django_db
def test_a_posted_document_cannot_be_reposted(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    with pytest.raises(DocumentTransitionError):
        with transaction.atomic():
            doc.post()
    # exactly one number was consumed
    series.refresh_from_db()
    assert series.next_seq == 2


@pytest.mark.django_db
def test_a_posted_document_cannot_be_edited(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    reloaded = DocumentProbe.objects.get(pk=doc.pk)
    reloaded.memo = "tampered"
    with pytest.raises(DocumentEditError):
        reloaded.save()


@pytest.mark.django_db
def test_a_draft_is_freely_editable(series: VoucherSeries) -> None:
    doc = _draft()
    doc.memo = "still a draft"
    doc.save()  # no error
    assert DocumentProbe.objects.get(pk=doc.pk).memo == "still a draft"


@pytest.mark.django_db
def test_cancel_is_a_reversing_transition_never_a_delete(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    doc.cancel()
    assert doc.docstatus == DocStatus.CANCELLED
    # the row still exists — cancellation reverses, it does not delete.
    assert DocumentProbe.objects.filter(pk=doc.pk).exists()


@pytest.mark.django_db
def test_a_draft_cannot_be_cancelled(series: VoucherSeries) -> None:
    doc = _draft()  # never posted
    with pytest.raises(DocumentTransitionError):
        doc.cancel()


@pytest.mark.django_db
def test_a_cancelled_document_is_frozen(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    doc.cancel()
    # cannot re-post, cannot re-cancel, cannot edit
    with pytest.raises(DocumentTransitionError):
        with transaction.atomic():
            doc.post()
    with pytest.raises(DocumentTransitionError):
        doc.cancel()


@pytest.mark.django_db
def test_a_posted_document_cannot_be_deleted(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    reloaded = DocumentProbe.objects.get(pk=doc.pk)
    with pytest.raises(DocumentEditError):
        reloaded.delete()
    assert DocumentProbe.objects.filter(pk=doc.pk).exists()


@pytest.mark.django_db
def test_an_unposted_draft_may_be_discarded(series: VoucherSeries) -> None:
    doc = _draft()
    pk = doc.pk
    doc.delete()  # a never-posted draft burns no number and can be thrown away
    assert not DocumentProbe.objects.filter(pk=pk).exists()


@pytest.mark.django_db
def test_db_trigger_forbids_raw_repost_even_for_superuser(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    table = DocumentProbe._meta.db_table
    # raw SQL trying to walk submitted(1) -> draft(0) is rejected at the DB.
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"UPDATE {table} SET docstatus = 0 WHERE id = %s", [doc.pk])


@pytest.mark.django_db
def test_db_trigger_forbids_raw_delete_of_submitted(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    table = DocumentProbe._meta.db_table
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE id = %s", [doc.pk])
    assert DocumentProbe.objects.filter(pk=doc.pk).exists()
