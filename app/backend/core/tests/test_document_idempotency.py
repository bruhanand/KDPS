"""K2 golden test — the idempotency UUID dedupes offline writes.

A till may retry the same write after a flaky connection. The client-supplied
`idempotency_uuid` makes the retry return the *same* document — never a
duplicate. A duplicate UUID is refused at the DB (a unique column).
"""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError, transaction

from core.documents import DocumentProbe, VoucherSeries

FY = "26-27"
STORE = "DEO"
DOC_TYPE = "SAL"


@pytest.fixture
def series() -> VoucherSeries:
    return VoucherSeries.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)


@pytest.mark.django_db
def test_retry_with_same_uuid_returns_the_same_document(series: VoucherSeries) -> None:
    key = uuid.uuid4()
    first = DocumentProbe.objects.idempotent_create(
        idempotency_uuid=key, fy=FY, store_code=STORE, doc_type=DOC_TYPE
    )
    retry = DocumentProbe.objects.idempotent_create(
        idempotency_uuid=key, fy=FY, store_code=STORE, doc_type=DOC_TYPE
    )
    assert retry.pk == first.pk
    assert DocumentProbe.objects.count() == 1  # no duplicate


@pytest.mark.django_db
def test_distinct_uuids_make_distinct_documents(series: VoucherSeries) -> None:
    a = DocumentProbe.objects.idempotent_create(
        idempotency_uuid=uuid.uuid4(), fy=FY, store_code=STORE, doc_type=DOC_TYPE
    )
    b = DocumentProbe.objects.idempotent_create(
        idempotency_uuid=uuid.uuid4(), fy=FY, store_code=STORE, doc_type=DOC_TYPE
    )
    assert a.pk != b.pk
    assert DocumentProbe.objects.count() == 2


@pytest.mark.django_db
def test_every_document_gets_a_uuid_by_default(series: VoucherSeries) -> None:
    doc = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    assert isinstance(doc.idempotency_uuid, uuid.UUID)


@pytest.mark.django_db
def test_a_duplicate_uuid_is_refused_at_the_db(series: VoucherSeries) -> None:
    key = uuid.uuid4()
    DocumentProbe.objects.create(idempotency_uuid=key, fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DocumentProbe.objects.create(
                idempotency_uuid=key, fy=FY, store_code=STORE, doc_type=DOC_TYPE
            )
