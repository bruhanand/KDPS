"""Anti-cheat golden test — a till-assigned number is accepted exactly once.

The sale is the one document the server does not number: the till bills offline,
prints, and hands the customer a numbered piece of paper long before the server
hears about it. So the kernel's job flips from *handing out* a number to
*accepting* one, and the guarantee has to flip with it.

What must hold, and what each of these tests is here to stop:

* **Exactly once.** Two writes claiming `26-27/DEO/SAL/74` cannot both become
  documents — not sequentially, not racing, not through a bulk path.
* **A minted number is never edited or re-used.** Not by a second post, not by a
  rewind of the counter, not by a raw UPDATE.
* **A hole is flagged, never blocked.** Bill 75 syncing before bill 74 must sell;
  74 must still be accepted when it eventually arrives.
* **Only the till's document type comes this way.** Every other series still gets
  its number from the server, gap-free.
"""

from __future__ import annotations

import threading

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction

from core.documents import (
    EXTERNAL_NUMBER_DOC_TYPES,
    DocumentProbe,
    ExternalNumberError,
    VoucherSeries,
)

FY = "26-27"
STORE = "DEO"
SAL = "SAL"


def _seed_series(doc_type: str = SAL) -> VoucherSeries:
    return VoucherSeries.objects.create(fy=FY, store_code=STORE, doc_type=doc_type)


def _accept(seq: int, doc_type: str = SAL) -> DocumentProbe:
    """Post a probe the way a synced bill posts: carrying its own number."""
    probe = DocumentProbe.objects.create(
        fy=FY, store_code=STORE, doc_type=doc_type, external_seq=seq
    )
    with transaction.atomic():
        probe.post()
    return probe


# --- the number the till brought -------------------------------------------


@pytest.mark.django_db
def test_the_tills_number_is_the_number_the_document_gets() -> None:
    _seed_series()
    probe = _accept(74)
    assert probe.doc_number == "26-27/DEO/SAL/74"


@pytest.mark.django_db
def test_accepting_advances_the_counter_past_the_number_used() -> None:
    series = _seed_series()
    _accept(1)
    series.refresh_from_db()
    assert series.next_seq == 2


@pytest.mark.django_db
def test_a_rolled_back_accept_leaves_the_counter_where_it_was() -> None:
    series = _seed_series()
    probe = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=SAL, external_seq=1)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            probe.post()
            raise RuntimeError("force rollback after acceptance")
    series.refresh_from_db()
    assert series.next_seq == 1
    # …and the till's number is still available, because nothing consumed it.
    assert _accept(1).doc_number == "26-27/DEO/SAL/1"


# --- exactly once -----------------------------------------------------------


@pytest.mark.django_db
def test_the_same_number_cannot_become_two_documents() -> None:
    _seed_series()
    _accept(74)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _accept(74)


@pytest.mark.django_db(transaction=True)
def test_concurrent_writers_cannot_both_take_one_number() -> None:
    # Two tills (or one till syncing twice) racing the same seq. Exactly one wins;
    # the loser fails outright rather than quietly minting a second `…/SAL/74`.
    _seed_series()
    workers = 8
    barrier = threading.Barrier(workers)
    won: list[str] = []
    lock = threading.Lock()

    def accept_74() -> None:
        barrier.wait()
        try:
            probe = _accept(74)
        except Exception:  # noqa: BLE001 — losing is the expected outcome for 7 of 8
            return
        finally:
            connection.close()
        with lock:
            won.append(probe.doc_number)

    threads = [threading.Thread(target=accept_74) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert won == ["26-27/DEO/SAL/74"]
    assert DocumentProbe.objects.filter(doc_number="26-27/DEO/SAL/74").count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_burst_of_distinct_till_numbers_all_land_exactly_once() -> None:
    # The realistic sync drain: a day of queued bills arriving at once, out of
    # order. Every one is accepted, none twice, and the counter ends past the
    # highest number used.
    series = _seed_series()
    seqs = [7, 3, 9, 1, 5, 2, 8, 4, 6]
    barrier = threading.Barrier(len(seqs))

    def accept(seq: int) -> None:
        barrier.wait()
        try:
            _accept(seq)
        finally:
            connection.close()

    threads = [threading.Thread(target=accept, args=(s,)) for s in seqs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    numbers = set(DocumentProbe.objects.values_list("doc_number", flat=True))
    assert numbers == {f"26-27/DEO/SAL/{n}" for n in seqs}
    series.refresh_from_db()
    assert series.next_seq == 10


@pytest.mark.django_db
def test_an_accepted_document_cannot_be_posted_again() -> None:
    _seed_series()
    probe = _accept(74)
    with pytest.raises(Exception):  # noqa: B017 — the FSM's refusal, whichever it is
        with transaction.atomic():
            probe.post()
    probe.refresh_from_db()
    assert probe.doc_number == "26-27/DEO/SAL/74"


@pytest.mark.django_db
def test_a_minted_number_cannot_be_edited_afterwards() -> None:
    _seed_series()
    probe = _accept(74)
    probe.memo = "renumbered by hand"
    with pytest.raises(Exception):  # noqa: B017 — posted documents are immutable
        probe.save()


# --- holes: flag, never block ----------------------------------------------


@pytest.mark.django_db
def test_a_bill_that_arrives_ahead_of_its_predecessors_is_accepted() -> None:
    # Bill 75 syncs while 73 and 74 are still stuck on the till. Refusing it would
    # stop the store selling because an *older* bill is stuck — Rule 8 says flag.
    series = _seed_series()
    with transaction.atomic():
        accepted = VoucherSeries.accept_external(fy=FY, store_code=STORE, doc_type=SAL, seq=75)
    assert accepted.doc_number == "26-27/DEO/SAL/75"
    assert accepted.hole_from == 1
    assert accepted.hole_count == 74
    series.refresh_from_db()
    assert series.next_seq == 76


@pytest.mark.django_db
def test_the_hole_is_still_acceptable_when_it_finally_syncs() -> None:
    _seed_series()
    _accept(75)
    late = _accept(74)  # the straggler arrives
    assert late.doc_number == "26-27/DEO/SAL/74"


@pytest.mark.django_db
def test_filling_a_hole_does_not_move_the_counter() -> None:
    series = _seed_series()
    _accept(75)
    series.refresh_from_db()
    assert series.next_seq == 76
    _accept(74)
    series.refresh_from_db()
    assert series.next_seq == 76  # a late arrival is not "the latest bill"


@pytest.mark.django_db
def test_an_in_sequence_accept_reports_no_hole() -> None:
    _seed_series()
    with transaction.atomic():
        accepted = VoucherSeries.accept_external(fy=FY, store_code=STORE, doc_type=SAL, seq=1)
    assert accepted.hole_from is None
    assert accepted.hole_count == 0


@pytest.mark.django_db
def test_an_absurd_jump_is_described_by_count_not_by_a_list() -> None:
    # A till bug naming seq 10 million must not make the kernel build a
    # ten-million-element range to say so. It is still accepted (flag, never
    # block) and later, lower bills still post as hole-fills.
    _seed_series()
    with transaction.atomic():
        accepted = VoucherSeries.accept_external(
            fy=FY, store_code=STORE, doc_type=SAL, seq=10_000_000
        )
    assert accepted.hole_count == 9_999_999
    assert _accept(2).doc_number == "26-27/DEO/SAL/2"


# --- who may come this way --------------------------------------------------


@pytest.mark.django_db
def test_only_the_tills_document_type_may_bring_its_own_number() -> None:
    _seed_series("GRN")
    with pytest.raises(ExternalNumberError):
        with transaction.atomic():
            VoucherSeries.accept_external(fy=FY, store_code=STORE, doc_type="GRN", seq=1)
    assert "GRN" not in EXTERNAL_NUMBER_DOC_TYPES


@pytest.mark.django_db
def test_a_server_allocated_series_is_untouched_by_this_path() -> None:
    # The GRN counter still hands out numbers gap-free from 1, whatever the sale
    # series next door is doing.
    _seed_series()
    _seed_series("GRN")
    _accept(500)
    grn = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type="GRN")
    with transaction.atomic():
        grn.post()
    assert grn.doc_number == "26-27/DEO/GRN/1"


@pytest.mark.parametrize("bad", [0, -1, -74])
@pytest.mark.django_db
def test_a_non_positive_sequence_is_refused(bad: int) -> None:
    _seed_series()
    with pytest.raises(ExternalNumberError):
        with transaction.atomic():
            VoucherSeries.accept_external(fy=FY, store_code=STORE, doc_type=SAL, seq=bad)


@pytest.mark.django_db
def test_a_boolean_is_not_a_sequence() -> None:
    # `True == 1` in Python; an accidental flag must not become bill number 1.
    _seed_series()
    with pytest.raises(ExternalNumberError):
        with transaction.atomic():
            VoucherSeries.accept_external(fy=FY, store_code=STORE, doc_type=SAL, seq=True)


@pytest.mark.django_db
def test_a_missing_series_is_refused_rather_than_invented() -> None:
    with pytest.raises(VoucherSeries.DoesNotExist):
        with transaction.atomic():
            VoucherSeries.accept_external(fy=FY, store_code="NOPE", doc_type=SAL, seq=1)


@pytest.mark.django_db(transaction=True)  # the ordinary marker would supply one
def test_accepting_outside_a_transaction_is_refused() -> None:
    # Without the caller's transaction the row lock is a no-op and the document
    # write that makes acceptance exactly-once commits separately — so the kernel
    # refuses rather than pretending to be safe.
    _seed_series()
    with pytest.raises(ExternalNumberError):
        VoucherSeries.accept_external(fy=FY, store_code=STORE, doc_type=SAL, seq=1)


# --- the counter itself, under the DB guard ---------------------------------


@pytest.mark.django_db
def test_a_sale_counter_cannot_be_rewound_by_raw_sql() -> None:
    # [#D] The till series is the one allowed to jump forward. That must not be
    # read as "the till series is unguarded": a rewind hands out a number that is
    # already on a printed, posted bill.
    series = _seed_series()
    _accept(74)
    with pytest.raises(DatabaseError):
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("UPDATE core_voucher_series SET next_seq = 1 WHERE id = %s", [series.pk])
    series.refresh_from_db()
    assert series.next_seq == 75


@pytest.mark.django_db
def test_a_sale_counter_cannot_be_jumped_by_a_bulk_update() -> None:
    # [#D] A jump is legal only from `accept_external()`, which declares the
    # sequence it is accepting to the guard. `QuerySet.update()` declares nothing.
    series = _seed_series()
    _accept(1)
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            VoucherSeries.objects.filter(pk=series.pk).update(next_seq=999)
    series.refresh_from_db()
    assert series.next_seq == 2


@pytest.mark.django_db
def test_the_accept_licence_does_not_outlive_the_call() -> None:
    # `accept_external` declares its jump transaction-locally. If that licence
    # leaked, everything else sharing the transaction would inherit permission to
    # rewrite the counter freely — so it is cleared the moment the accept is done.
    series = _seed_series()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            VoucherSeries.accept_external(fy=FY, store_code=STORE, doc_type=SAL, seq=50)
            VoucherSeries.objects.filter(pk=series.pk).update(next_seq=999)
    series.refresh_from_db()
    assert series.next_seq == 1  # the whole transaction rolled back
