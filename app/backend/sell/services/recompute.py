"""What the rulebook says a bill should have cost - the server's own answer.

Two callers, and they want the same number for different reasons.

The **discount cap** (contract step 6) has to know how much of a line's discount
the rulebook is answerable for, because the rest is a cashier's own and B2 caps
that. Before this module existed `_rulebook_saving` returned nought and said why:
the obvious source is the till's `offer_evidence.saved_paise`, and the till is
the party the cap exists to constrain. A cap the capped party can lift by
describing its own discount as an offer is not a cap. So the server resolves the
cart itself, and the number it gets is the only one that counts.

The **daily applied-vs-rulebook check** (D5 Q10, B3) wants the same resolution to
compare against what was actually charged, and to raise `offer_mismatch` where
the two disagree by more than a rupee on a line. That one never blocks: the bill
is printed and the customer has gone.

**The rulebook is read as of the bill's own day, not today.** This is the whole
reason the two uses can share one function without the first becoming a hazard.
A counter bills offline under the rules it holds; by the time the bill syncs, an
offer may have ended and another started. Resolving against *today's* rulebook
would refuse a bill the store priced honestly - `OVERRIDE_REQUIRED` on a receipt
already in a customer's hand, with the whole queue stopped behind it. So an
`ended` rule is still consulted for a bill printed inside its dates: it was
running when that bill was printed, and that is the only question being asked.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from django.db.models import Q

from offers.models import Offer
from offers.resolution import Cart, CartLine, Resolution, Rule, covers, resolve

#: A rupee a line, matching the GST half of the same advisory step (B3). Below
#: this the two engines are agreeing and the difference is a rounding artefact
#: nobody can act on.
OFFER_TOLERANCE_PAISE = 100

#: Statuses a bill could have been priced under. A draft or a merely-approved
#: rule never reached a till, so it cannot explain a discount; an ended one very
#: well might have been running on the day.
BILLABLE_STATUSES = (Offer.Status.LIVE, Offer.Status.ENDED)


@dataclass(frozen=True)
class BillLine:
    """The little a bill line has to say for the rulebook to price it.

    Deliberately a plain record rather than `_PreparedLine` or `SaleLine`: this
    module sits below the accept pipeline, and taking its type would make the
    rulebook a dependency of the counter in the wrong direction.
    """

    line_no: int
    barcode: str
    season: str
    qty: int
    mrp_paise: int
    dims: Mapping[str, str]
    no_discount: bool = False


def _running_on(store_code: str, day: date) -> Any:
    """Rows a bill printed at this store on this day could have been priced under."""
    return (
        Offer.objects.filter(status__in=BILLABLE_STATUSES, starts_on__lte=day)
        .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=day))
        .filter(store_scope__stores__contains=[store_code.upper()])
        .select_related("brand")
    )


def rulebook_for(store_code: str, day: date) -> list[Rule]:
    """The rules that were running at this store on this day, in engine terms."""
    return [offer.as_rule() for offer in _running_on(store_code, day).order_by("priority", "id")]


def _cart_line(line: BillLine) -> CartLine:
    return CartLine(
        line_no=line.line_no,
        brand=line.dims.get("brand", ""),
        item=line.dims.get("item", ""),
        design=line.dims.get("design", ""),
        size=line.dims.get("size", ""),
        color=line.dims.get("color", ""),
        barcode=line.barcode,
        season=line.season,
        qty=line.qty,
        mrp_paise=line.mrp_paise,
        no_discount=line.no_discount,
    )


def resolve_bill(store_code: str, day: date, lines: Sequence[BillLine]) -> Resolution:
    """Price these lines against the store's rulebook as it stood on `day`."""
    cart = Cart(lines=tuple(_cart_line(line) for line in lines), day=day)
    return resolve(cart, rulebook_for(store_code, day))


def rule_was_running(offer_id: Any, store_code: str, day: date, line: BillLine) -> bool:
    """Was the rule the counter cited genuinely running over this piece that day?

    The narrow question that keeps the discount cap from stopping a store's whole
    queue.

    The server reads its rulebook live; the till read its copy whenever it last
    synced. Between the two, head office can end a rule, take this store off one,
    or flip a piece's no-discount flag - and a bill priced honestly under the
    till's copy then looks, to the server, like a discount nobody authorised.
    Refusing it would be `OVERRIDE_REQUIRED` on a receipt already in a customer's
    hand, with every bill behind it stuck in the queue: exactly the "block what
    the business has already absorbed" this pipeline exists not to do.

    So the citation is checked for the three things the server *can* still settle
    - the rule exists, it belonged to this store, and it covered this piece on the
    day the bill printed. What it cannot settle is the *amount*, which is why a
    line answering true here is flagged rather than waved through.

    A fabricated citation fails all three: a till cannot mint a rule, put itself
    on one, or make one cover a brand it never named.

    Note `no_discount=False`. The question being asked is whether the *rule* was
    about this piece, and the AMM/NOD flag is a fact about the piece today, not
    part of any rule. It is a live master-data column with no history, so a piece
    flagged after a bill printed would otherwise turn that bill into a refusal -
    the same retrospective trap, arriving through a different column.
    """
    if not offer_id:
        return False
    offer = _running_on(store_code, day).filter(pk=offer_id).first()
    if offer is None:
        return False
    return covers(offer.as_rule(), replace(_cart_line(line), no_discount=False), day)
