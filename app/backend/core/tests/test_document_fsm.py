"""K2 golden test — the docstatus FSM is strictly enforced.

`draft → submitted → cancelled`, one `post()` per doc. No skipped or cyclic
transitions; a posted doc cannot be edited or re-posted; cancel is a reversing
*transition*, never a row delete. The DB trigger is the load-bearing guard (it
binds even raw SQL); the ORM raises the early, clean error.
"""

from __future__ import annotations

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction

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
    assert doc.doc_number == "26-27/DEO/SAL/1"
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


# -- [#3] a posted row can never exist without a number (INSERT *and* UPDATE) ----
@pytest.mark.django_db
def test_cannot_insert_a_submitted_row_without_a_number(series: VoucherSeries) -> None:
    # objects.create(docstatus=SUBMITTED) is an INSERT — it never touches post()
    # or the UPDATE trigger, so only a DB CHECK constraint can stop it.
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DocumentProbe.objects.create(
                fy=FY, store_code=STORE, doc_type=DOC_TYPE, docstatus=DocStatus.SUBMITTED
            )


@pytest.mark.django_db
def test_cannot_queryset_update_a_numberless_draft_to_submitted(series: VoucherSeries) -> None:
    # A bulk UPDATE flips docstatus while doc_number stays NULL — the FSM trigger
    # allows draft→submitted, so again only the CHECK constraint catches it.
    doc = _draft()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DocumentProbe.objects.filter(pk=doc.pk).update(docstatus=DocStatus.SUBMITTED)
    doc.refresh_from_db()
    assert doc.docstatus == DocStatus.DRAFT  # still a numberless draft


# -- [#4] cancellation is status-only; it may not rewrite posted facts ----------
@pytest.mark.django_db
def test_raw_cancel_that_tampers_another_column_is_rejected(series: VoucherSeries) -> None:
    doc = _draft()
    with transaction.atomic():
        doc.post()
    table = DocumentProbe._meta.db_table
    # the slice's thesis is "binds even the superuser": a raw cancel that also
    # rewrites memo must be refused, not silently mutate a posted fact.
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                f"UPDATE {table} SET docstatus = 2, memo = 'tampered' WHERE id = %s",
                [doc.pk],
            )
    reloaded = DocumentProbe.objects.get(pk=doc.pk)
    assert reloaded.docstatus == DocStatus.SUBMITTED  # the whole UPDATE rolled back
    assert reloaded.memo == ""


@pytest.mark.django_db
def test_raw_status_only_cancel_is_allowed(series: VoucherSeries) -> None:
    # The backstop must reject *tampering*, not legitimate cancellation: a raw
    # UPDATE touching only docstatus is the sanctioned reversing transition.
    doc = _draft()
    with transaction.atomic():
        doc.post()
    table = DocumentProbe._meta.db_table
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(f"UPDATE {table} SET docstatus = 2 WHERE id = %s", [doc.pk])
    assert DocumentProbe.objects.get(pk=doc.pk).docstatus == DocStatus.CANCELLED
