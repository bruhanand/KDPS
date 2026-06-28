"""K2 golden test — document numbers are gap-free with no collisions.

The Tally join key `{FY}/{store}/{seq}` must never skip a number and never hand
out the same number twice, even when many tills post at the same instant. A
Postgres SEQUENCE leaks gaps on rollback, so the series is a row counter
incremented under `SELECT … FOR UPDATE` inside the document's own transaction —
a rolled-back post un-allocates its number.
"""

from __future__ import annotations

import threading

import pytest
from django.db import connection, transaction

from core.documents import DocumentProbe, VoucherSeries

FY = "26-27"
STORE = "DEO"
DOC_TYPE = "SAL"


def _seed_series(prefix: str = "", suffix: str = "") -> VoucherSeries:
    return VoucherSeries.objects.create(
        fy=FY, store_code=STORE, doc_type=DOC_TYPE, prefix=prefix, suffix=suffix
    )


@pytest.mark.django_db
def test_render_matches_the_canonical_tally_key() -> None:
    series = _seed_series()
    # the issue's worked example: 26-27/DEO/74
    assert series.render(74) == "26-27/DEO/74"


@pytest.mark.django_db
def test_prefix_and_suffix_are_data_not_code() -> None:
    series = _seed_series(prefix="S-", suffix="/A")
    assert series.render(1) == "S-26-27/DEO/1/A"


@pytest.mark.django_db
def test_sequential_posts_are_gap_free() -> None:
    _seed_series()
    numbers = []
    for _ in range(5):
        doc = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
        with transaction.atomic():
            doc.post()
        numbers.append(doc.doc_number)
    assert numbers == [
        "26-27/DEO/1",
        "26-27/DEO/2",
        "26-27/DEO/3",
        "26-27/DEO/4",
        "26-27/DEO/5",
    ]


@pytest.mark.django_db
def test_a_rolled_back_post_does_not_burn_a_number() -> None:
    series = _seed_series()
    doc = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            doc.post()
            assert doc.doc_number == "26-27/DEO/1"
            raise RuntimeError("force rollback after allocation")
    # the counter is back where it started — gap-free, no leaked 1.
    series.refresh_from_db()
    assert series.next_seq == 1
    # and the next real post takes number 1, not 2.
    doc2 = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    with transaction.atomic():
        doc2.post()
    assert doc2.doc_number == "26-27/DEO/1"


@pytest.mark.django_db(transaction=True)
def test_no_collisions_under_concurrent_inserts() -> None:
    _seed_series()
    workers = 12
    barrier = threading.Barrier(workers)
    results: list[str] = []
    lock = threading.Lock()

    def post_one() -> None:
        barrier.wait()  # maximise contention — everyone races the same series row
        try:
            doc = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
            with transaction.atomic():
                doc.post()
            with lock:
                results.append(doc.doc_number)
        finally:
            connection.close()

    threads = [threading.Thread(target=post_one) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = {f"26-27/DEO/{n}" for n in range(1, workers + 1)}
    assert set(results) == expected  # gap-free AND collision-free
    assert len(results) == workers  # no duplicates
