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
from dataclasses import dataclass
from datetime import date

from django.db.models import Q

from offers.models import Offer
from offers.resolution import Cart, CartLine, Resolution, Rule, resolve

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


def rulebook_for(store_code: str, day: date) -> list[Rule]:
    """The rules that were running at this store on this day, in engine terms."""
    rows = (
        Offer.objects.filter(status__in=BILLABLE_STATUSES, starts_on__lte=day)
        .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=day))
        .filter(store_scope__stores__contains=[store_code.upper()])
        .select_related("brand")
        .order_by("priority", "id")
    )
    return [_rule(offer) for offer in rows]


def _rule(offer: Offer) -> Rule:
    payload = offer.as_rule_payload()
    return Rule(
        id=offer.id,
        name=offer.name,
        layer=offer.layer,
        brand=offer.brand_name,
        trigger_type=offer.trigger_type,
        trigger_config=payload["trigger_config"],
        reward_type=offer.reward_type,
        reward_config=payload["reward_config"],
        item_scope=payload["item_scope"],
        starts_on=offer.starts_on,
        ends_on=offer.ends_on,
        combinable=offer.combinable,
        priority=offer.priority,
    )


def resolve_bill(store_code: str, day: date, lines: Sequence[BillLine]) -> Resolution:
    """Price these lines against the store's rulebook as it stood on `day`."""
    cart = Cart(
        lines=tuple(
            CartLine(
                line_no=line.line_no,
                brand=line.dims.get("brand", ""),
                item=line.dims.get("item", ""),
                design=line.dims.get("design", ""),
                barcode=line.barcode,
                season=line.season,
                qty=line.qty,
                mrp_paise=line.mrp_paise,
                no_discount=line.no_discount,
            )
            for line in lines
        ),
        day=day,
    )
    return resolve(cart, rulebook_for(store_code, day))
