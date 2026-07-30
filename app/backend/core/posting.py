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

from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.floors import REGISTERED_FLOOR_EXCEPTIONS
from core.gl import GLAccount, GLEntry


class PostingError(Exception):
    """Base for posting-engine violations."""


class UnbalancedError(PostingError):
    """The legs of a posting do not sum to zero in paise (or there are fewer than two)."""


class PostingFloorError(PostingError, PermissionDenied):
    """A non-configurable people rule refused an otherwise valid posting."""


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

    Reads as the three things it is: refuse anything that is not a balanced
    posting, resolve what the legs inherit from the document, then write. The
    refusals are grouped in `_refuse_unpostable` on purpose — they are the
    invariants of the value ledger, and they are worth reading in one place.
    """
    legs = list(legs)
    _refuse_unpostable(doc, legs)
    doc_type, doc_number, default_store, default_gstin, actor = _posting_context(doc, posted_by)
    _refuse_actor_outside_floor(actor, legs, doc_type)

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


def _refuse_actor_outside_floor(actor: Any, legs: list[Leg], doc_type: str) -> None:
    """A store may move pieces, but it never writes rupees into the books.

    This sits in the sole GL writer, below every API and business module, so a
    Setup grant, shell call or future endpoint cannot route around it.

    The one carve-out — the store-native sale — is declared in `core.floors` with
    its reason, and is narrow by construction: it names its document types and
    the exact accounts they may touch, so a leg outside the allow-list drops back
    onto the floor even on a document the exception covers.
    """
    if getattr(actor, "scope_type", "") == "store" and not _store_actor_within_exception(
        legs, doc_type
    ):
        raise PostingFloorError(
            "A store-scoped user cannot post value to the books; "
            "a named head-office person must perform this action."
        )
    raises_brand_liability = any(leg.account == GLAccount.VENDOR_PAYABLE for leg in legs)
    actor_name = getattr(actor, "full_name", "") or getattr(actor, "username", "") if actor else ""
    if doc_type in {"PT", "VFL"}:
        assert_pt_or_vflip_actor(actor)
    if raises_brand_liability and (not getattr(actor, "pk", None) or not actor_name):
        raise PostingFloorError(
            "Money owed to a brand cannot post without a named head-office person."
        )


def _store_actor_within_exception(legs: list[Leg], doc_type: str) -> bool:
    """Is this posting inside a declared carve-out from the store floor?

    True only when some registered exception covers `doc_type` *and* every leg
    sits inside that exception's account allow-list — one stray account and the
    whole posting is back on the floor. Accounts the exception marks as
    party-required must also name their counterparty.
    """
    exception = next(
        (e for e in REGISTERED_FLOOR_EXCEPTIONS.values() if e.covers(doc_type)),
        None,
    )
    if exception is None:
        return False
    return all(
        leg.account in exception.accounts
        and (leg.account not in exception.party_required_accounts or bool(leg.party_code))
        for leg in legs
    )


def assert_pt_or_vflip_actor(actor: Any) -> None:
    """Floor shared by PT value posting and V-flip stock + value posting."""
    actor_name = getattr(actor, "full_name", "") or getattr(actor, "username", "") if actor else ""
    if (
        getattr(actor, "scope_type", "") == "store"
        or not getattr(actor, "pk", None)
        or not actor_name
        or not getattr(actor, "may_post_pt_or_vflip_floor", False)
    ):
        raise PostingFloorError(
            "Only a named Accounts or Owner head-office person may post PT inwarding "
            "or V-flip value."
        )


def _refuse_unpostable(doc: Any, legs: list[Leg]) -> None:
    """Every reason a posting is refused, in one place. Raises, or returns None."""
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
    if not getattr(doc, "doc_type", None) or not getattr(doc, "doc_number", None):
        raise PostingError("post_entries requires a doc with a doc_type and a minted doc_number")


def _posting_context(doc: Any, posted_by: Any) -> tuple[str, str, Any, Any, Any]:
    """What every leg of this voucher inherits from its document.

    An unauthenticated actor is recorded as nobody rather than as itself: a leg's
    `posted_by` is evidence, and `AnonymousUser` is not a person.
    """
    actor = posted_by if posted_by is not None else getattr(doc, "posted_by", None)
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    return (
        doc.doc_type,
        doc.doc_number,
        getattr(doc, "store", None),
        getattr(doc, "gstin", None),
        actor,
    )
