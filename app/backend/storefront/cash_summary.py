"""What the store took today, by tender (#188, contract §Step 6).

Read-only, and deliberately short of a day close. Confirming a day - counting the
drawer, agreeing the float, locking the date - is store open/close (I3), its own
designed flow sequenced after this one. What this is, is the number a store
person counts *against*: the day by mode, the bills behind it, and the exceptions
the day left open.

The arithmetic is `storefront.day`, shared with the Dashboard's money tiles so
"today" cannot read one figure on Home and another in Money.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Q

from masters.models import Store
from sell.models import ContinuityFlag
from storefront.day import money_for


def open_flags(store: Store, day: date) -> Any:
    """This store's unresolved exceptions belonging to `day`.

    A flag belongs to the day of the **bill** it is about; one about no
    particular bill - a hole is a bill that never arrived, so there is nothing to
    hang it on - belongs to the day it was raised. Both readings are "the day
    this became somebody's problem", which is what a person scanning a day
    summary is asking.

    `ignored` rows are not here and that is the point of the state: the store has
    looked and said this one is fine. They stay countable on the bill itself.
    """
    return ContinuityFlag.objects.filter(store=store, status=ContinuityFlag.Status.OPEN).filter(
        Q(sale__billed_at__date=day) | Q(sale__isnull=True, created_at__date=day)
    )


def build(store: Store, day: date) -> dict[str, Any]:
    """The contract's cash-summary body for one store and one day."""
    money = money_for(store, day)
    return {
        # Beyond the contract's sketch, and for the same reason the Dashboard
        # carries it: the top-bar switcher decides which shop this is, so a screen
        # that could not name the store it drew would leave a person reading
        # yesterday's Ranchi against tonight's Deoghar drawer.
        "store": store.code,
        "date": day.isoformat(),
        "modes": dict(money.collections),
        "bills": money.bills,
        "returns": money.returns,
        "credit_notes_issued_paise": money.credit_notes_issued_paise,
        "flags_open": open_flags(store, day).count(),
    }
