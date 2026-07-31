"""Reading a day off the wire, once.

`?date=2026-07-31` reaches four places now - the cash summary, the flag list, the
daily-check command and (as a cursor) the till's dataset - and each of them has
to catch the *two* different ways Django's `parse_date` refuses:

* it **answers nothing** for text that is not a date at all ("yesterday");
* it **raises** for text correctly shaped and impossible ("2026-02-30").

Miss the second and a well-formed nonsense date is a 500 rather than a sentence.
It was written out four times before this module existed, comment and all, and a
fifth caller was one copy-paste away from getting only half of it.
"""

from __future__ import annotations

from datetime import date

from django.utils.dateparse import parse_date


def parse_day(text: str) -> date | None:
    """The day `text` names, or `None` if it names none.

    One answer for both refusals, so a caller has one branch to write. What to
    *do* about `None` stays the caller's: a query parameter earns a 400, and the
    till's opaque cursor deliberately self-heals into a full bootstrap instead.
    """
    try:
        return parse_date(text)
    except ValueError:
        return None
