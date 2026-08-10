"""The reversing half of the cancel transition, at the kernel level (#220).

The FSM has always been able to walk a document to `cancelled`. What it could not
do was *undo* what the document posted, so cancelling a bill left its legs in the
general ledger and the credit note it issued spendable for money the books said
had never been given back.

Three properties are asserted here, and the third is the one that keeps the other
two true a year from now:

  · a cancel mirrors the document's value legs, in one transaction with the status
    move, so the accounts come back to exactly where they were,
  · a document type that has declared nothing to reverse **refuses to cancel**
    rather than walking to `cancelled` over postings nobody reversed,
  · every concrete document in the system is either declared or is on a written
    list of the ones nobody has designed a reversal for - so a new money document
    cannot ship with a cancel that quietly does nothing, which is how #220 happened.

What a *bill* owes on top of its value legs - stock, collections, the vendor
accrual, the credit note - is `tests/test_sell_cancel_reversal.py`.
"""

from __future__ import annotations

import pytest
from django.apps import apps

from core.documents import DocStatus, DocumentProbe, VoucherSeries
from core.gl import GLAccount, GLEntry, account_balance, trial_balance
from core.posting import cr, dr, post_entries
from core.reversal import (
    REGISTERED_REVERSALS,
    ReversalNotDeclared,
    run_declared_reversal,
)

FY = "26-27"
STORE = "REV"
DOC_TYPE = "PRB"
VALUE = 250_000

#: Documents nobody has designed a reversal for yet, and what that means today:
#: they refuse to cancel. Every one of them moves stock, so a value-only mirror
#: would be a set of books that ties while the shelf disagrees - the half-reversal
#: the ticket's approach note warns against. They are listed rather than defaulted
#: so that adding one is a decision, and so that this test names the work that is
#: left (the transfer family's in-transit bucket is its own to unwind; the rest
#: follow the same shape as the bill's).
UNDESIGNED = {
    "inbound.grn",
    "outbound.storetransfer",
    "outbound.stockrequest",
    "outbound.transfergapclosure",
    "outbound.markdamaged",
    "outbound.returntovendor",
    "outbound.stockadjustment",
    "outbound.writeoff",
    "outbound.vflip",
}


@pytest.fixture
def series(db) -> VoucherSeries:
    return VoucherSeries.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE)


def _posted(memo: str = "") -> DocumentProbe:
    doc = DocumentProbe.objects.create(fy=FY, store_code=STORE, doc_type=DOC_TYPE, memo=memo)
    doc.post()
    return doc


@pytest.mark.django_db
def test_cancelling_mirrors_the_value_legs_the_document_posted(series: VoucherSeries) -> None:
    """The accounts come back to where they were, by appending, never by editing."""
    doc = _posted()
    post_entries(doc, [dr(GLAccount.CASH, VALUE), cr(GLAccount.SALES_REVENUE, VALUE)])
    assert account_balance(GLAccount.CASH) == VALUE
    original_ids = list(GLEntry.objects.values_list("id", flat=True))

    doc.cancel()

    assert account_balance(GLAccount.CASH) == 0
    assert account_balance(GLAccount.SALES_REVENUE) == 0
    assert trial_balance() == 0
    # append-only: the original legs are still there, with two more beside them
    assert set(original_ids) <= set(GLEntry.objects.values_list("id", flat=True))
    assert GLEntry.objects.count() == 4


@pytest.mark.django_db
def test_the_mirror_is_filed_under_the_document_it_undoes(series: VoucherSeries) -> None:
    """Not under a fresh number: a reversal is that document being undone, and the
    one document that matters most here - the till-numbered sale - has no series of
    its own to take a number from."""
    doc = _posted()
    post_entries(doc, [dr(GLAccount.CASH, VALUE), cr(GLAccount.SALES_REVENUE, VALUE)])

    doc.cancel()

    legs = GLEntry.objects.filter(doc_number=doc.doc_number)
    assert legs.count() == 4
    assert sum(leg.amount for leg in legs) == 0
    assert [leg.memo for leg in legs if leg.memo] == [f"Reversal of {doc.doc_number}"] * 2


@pytest.mark.django_db
def test_a_document_that_posted_nothing_still_cancels(series: VoucherSeries) -> None:
    """A document with no value legs reverses to nothing - which is an answer, not
    a failure. `post_entries` would refuse a one-leg voucher, so "mirror what is
    there" has to cope with there being nothing there."""
    doc = _posted()

    doc.cancel()

    assert DocumentProbe.objects.get(pk=doc.pk).docstatus == DocStatus.CANCELLED
    assert GLEntry.objects.count() == 0


@pytest.mark.django_db
def test_a_document_with_no_declared_reversal_refuses_to_cancel() -> None:
    """The safe default. A cancel that silently reversed nothing is the defect."""

    class _Undeclared:
        class _Meta:
            label_lower = "nowhere.nothing"

        _meta = _Meta()

    with pytest.raises(ReversalNotDeclared, match="nowhere.nothing"):
        run_declared_reversal(_Undeclared())


@pytest.mark.django_db
def test_every_document_type_has_decided_what_cancelling_it_undoes() -> None:
    """The contract that stops #220 happening again to a document nobody thought of.

    A concrete document is either declared - somebody wrote what its cancel undoes
    - or it is on `UNDESIGNED` above, where cancelling refuses outright. What is
    forbidden is the third state: a document that walks to `cancelled` while its
    postings stand.
    """
    from core.documents import Document

    documents = {
        model._meta.label_lower
        for model in apps.get_models()
        if issubclass(model, Document) and not model._meta.abstract
    }
    undecided = documents - set(REGISTERED_REVERSALS) - UNDESIGNED
    assert not undecided, f"no reversal decision for: {sorted(undecided)}"
    # And the other way about, so the list cannot rot into naming a model that has
    # since been declared or deleted.
    assert UNDESIGNED <= documents
    assert not (UNDESIGNED & set(REGISTERED_REVERSALS))
