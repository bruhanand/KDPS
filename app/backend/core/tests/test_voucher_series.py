"""K2 golden test — document numbers are gap-free with no collisions.

The Tally join key `{FY}/{store}/{type}/{seq}` must never skip a number and never
hand out the same number twice, even when many tills post at the same instant. A
Postgres SEQUENCE leaks gaps on rollback, so the series is a row counter
incremented DB-side under the post's own transaction — a rolled-back post
un-allocates its number, and a stale config save can never rewind it.
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
    # the canonical worked example: 26-27/DEO/SAL/74 — doc_type is in the key.
    assert series.render(74) == "26-27/DEO/SAL/74"


@pytest.mark.django_db
def test_render_carries_doc_type_so_the_key_is_globally_unique() -> None:
    # Two types in the same fy/store both start their counter at 1; only the
    # doc_type segment keeps their rendered keys apart.
    sal = _seed_series()
    grn = VoucherSeries.objects.create(
        fy=FY, store_code=STORE, doc_type="GRN", prefix="", suffix=""
    )
    assert sal.render(1) == "26-27/DEO/SAL/1"
    assert grn.render(1) == "26-27/DEO/GRN/1"
    assert sal.render(1) != grn.render(1)


@pytest.mark.django_db
def test_prefix_and_suffix_are_data_not_code() -> None:
    series = _seed_series(prefix="S-", suffix="/A")
    assert series.render(1) == "S-26-27/DEO/SAL/1/A"


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
        "26-27/DEO/SAL/1",
        "26-27/DEO/SAL/2",
        "26-27/DEO/SAL/3",
        "26-27/DEO/SAL/4",
        "26-27/DEO/SAL/5",
    ]


@pytest.mark.django_db
def test_two_doc_types_in_one_fy_store_post_with_distinct_numbers() -> None:
    # [#1] The per-(fy, store, doc_type) counter means SAL and GRN both start at
    # 1. If render() dropped doc_type both would mint `26-27/DEO/1` — a unique
    # violation on this shared table and a corrupt Tally join key across tables.
    _seed_series()  # SAL
    VoucherSeries.objects.create(fy=FY, store_code=STORE, doc_type="GRN")
    sal = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    grn = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type="GRN")
    with transaction.atomic():
        sal.post()
    with transaction.atomic():
        grn.post()  # must NOT collide with the SAL number
    assert sal.doc_number == "26-27/DEO/SAL/1"
    assert grn.doc_number == "26-27/DEO/GRN/1"
    assert sal.doc_number != grn.doc_number
    assert "SAL" in sal.doc_number and "GRN" in grn.doc_number


@pytest.mark.django_db
def test_a_rolled_back_post_does_not_burn_a_number() -> None:
    series = _seed_series()
    doc = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            doc.post()
            assert doc.doc_number == "26-27/DEO/SAL/1"
            raise RuntimeError("force rollback after allocation")
    # the counter is back where it started — gap-free, no leaked 1.
    series.refresh_from_db()
    assert series.next_seq == 1
    # and the next real post takes number 1, not 2.
    doc2 = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    with transaction.atomic():
        doc2.post()
    assert doc2.doc_number == "26-27/DEO/SAL/1"


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

    expected = {f"26-27/DEO/SAL/{n}" for n in range(1, workers + 1)}
    assert set(results) == expected  # gap-free AND collision-free
    assert len(results) == workers  # no duplicates


@pytest.mark.django_db
def test_a_stale_config_save_cannot_rewind_the_counter() -> None:
    # [#2] An admin loads a series, then a post advances the counter. The admin's
    # later full-row save() (editing prefix) must NOT write the old next_seq back
    # — that would reuse a number and break the gap-free guarantee.
    series = _seed_series()
    stale = VoucherSeries.objects.get(pk=series.pk)  # loaded when next_seq == 1

    doc = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    with transaction.atomic():
        doc.post()
    series.refresh_from_db()
    assert series.next_seq == 2  # the post advanced it

    stale.prefix = "EDIT-"  # admin edits config on the stale instance
    stale.save()

    series.refresh_from_db()
    assert series.next_seq == 2  # counter did NOT regress to the stale 1
    assert series.prefix == "EDIT-"  # the config edit still landed

    doc2 = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)
    with transaction.atomic():
        doc2.post()
    assert doc2.doc_number == "EDIT-26-27/DEO/SAL/2"  # fresh, non-colliding


@pytest.mark.django_db
def test_a_long_but_valid_series_posts_without_overflow() -> None:
    # [#5] prefix(32) + suffix(32) + fy + store + type + seq renders past 64
    # chars. doc_number must be wide enough that a valid config posts, rather
    # than every post failing at save time under that config.
    long_store = "WAREHOUSE-DEPOT1"  # 16 chars (the field max)
    long_type = "TRANSFER-OUT"
    VoucherSeries.objects.create(
        fy=FY,
        store_code=long_store,
        doc_type=long_type,
        prefix="P" * 32,
        suffix="S" * 32,
    )
    doc = DocumentProbe.objects.create(fy=FY, store_code=long_store, doc_type=long_type)
    with transaction.atomic():
        doc.post()
    assert len(doc.doc_number) > 64  # would have overflowed varchar(64)
    assert doc.doc_number.startswith("P" * 32)
    assert doc.doc_number.endswith("S" * 32)
