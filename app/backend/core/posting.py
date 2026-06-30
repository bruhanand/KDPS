"""The single balanced-or-fail posting engine (ADR-0006).

`post_entries(doc, legs)` is the *sole* writer of the value general ledger. It
enforces the two laws every poster must obey:

1. **Balanced** — Σ(leg.amount) MUST equal 0 in paise, with ≥ 2 legs (a debit and
   a credit). An unbalanced set raises and writes nothing.
2. **All-or-none** — every leg commits in one `transaction.atomic()` or none does.

Dimensions are snapshotted onto each leg at write time; liability *timing* lives on
the calling document (which legs it hands us), never in this engine.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from core.gl import GLEntry


class PostingError(Exception):
    """Base for posting-engine violations."""


class UnbalancedError(PostingError):
    """The legs of a posting do not sum to zero in paise (or there are fewer than two)."""


@dataclass(frozen=True)
class Leg:
    """One side of a balanced posting. `amount` is signed paise: debit > 0, credit < 0.

    Per-leg dimensions override the document defaults (a leg may carry its own
    store/gstin/brand/season/party — e.g. a payable leg with no store)."""

    account: str
    amount: int
    store: Any = None
    gstin: Any = None
    brand: str = ""
    season: str = ""
    party_type: str = ""
    party_code: str = ""
    against_voucher: str = ""
    memo: str = ""


def dr(account: str, paise: int, **dims: Any) -> Leg:
    """A debit leg (+paise)."""
    return Leg(account=account, amount=abs(int(paise)), **dims)


def cr(account: str, paise: int, **dims: Any) -> Leg:
    """A credit leg (−paise)."""
    return Leg(account=account, amount=-abs(int(paise)), **dims)


@dataclass(frozen=True)
class PostingRef:
    """A lightweight source-document reference for callers that are not (yet) a
    `core.documents.Document` (e.g. a PT file before Phase D reparenting). Anything
    exposing `doc_type` + `doc_number` (+ optional `store`/`gstin`/`posted_by`) works."""

    doc_type: str
    doc_number: str
    store: Any = None
    gstin: Any = None
    posted_by: Any = None


@transaction.atomic
def post_entries(doc: Any, legs: Sequence[Leg], *, posted_by: Any = None) -> list[GLEntry]:
    """Write a balanced set of GL legs for `doc`, or fail without writing anything.

    `doc` is the source document/reference (exposes `doc_type` + a minted
    `doc_number`; optionally `store`/`gstin`/`posted_by`). Raises `UnbalancedError`
    if the legs do not sum to zero or there are fewer than two; `PostingError` if the
    document has no number or a leg amount is not integer paise.
    """
    legs = list(legs)
    if len(legs) < 2:
        raise UnbalancedError("a posting needs at least two legs (a debit and a credit)")
    for leg in legs:
        if isinstance(leg.amount, bool) or not isinstance(leg.amount, int):
            raise PostingError(
                f"leg amount must be integer paise, got {type(leg.amount).__name__} "
                f"for account {leg.account!r}"
            )
    total = sum(leg.amount for leg in legs)
    if total != 0:
        raise UnbalancedError(f"legs do not balance: Σ = {total} paise (must be 0)")

    doc_type = getattr(doc, "doc_type", None)
    doc_number = getattr(doc, "doc_number", None)
    if not doc_type or not doc_number:
        raise PostingError("post_entries requires a doc with a doc_type and a minted doc_number")

    default_store = getattr(doc, "store", None)
    default_gstin = getattr(doc, "gstin", None)
    actor = posted_by if posted_by is not None else getattr(doc, "posted_by", None)
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None

    rows = [
        GLEntry(
            account=leg.account,
            amount=leg.amount,
            doc_type=doc_type,
            doc_number=doc_number,
            against_voucher=leg.against_voucher,
            party_type=leg.party_type,
            party_code=leg.party_code,
            store=leg.store if leg.store is not None else default_store,
            gstin=leg.gstin if leg.gstin is not None else default_gstin,
            brand=leg.brand,
            season=leg.season,
            line_no=i,
            memo=leg.memo,
            posted_by=actor,
        )
        for i, leg in enumerate(legs, start=1)
    ]
    GLEntry.objects.bulk_create(rows)
    return rows
