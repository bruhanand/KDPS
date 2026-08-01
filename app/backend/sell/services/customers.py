"""The customer master - one row per mobile, born from a bill (#242).

`masters.Customer` lives one layer below `sell` (ADR-0002: domain modules read
down into `masters`, never the other way), but the rule for what a row should
say only exists where the mobile actually shows up - a bill. So the rule lives
here and is called from two places that never see each other: the accept
pipeline's `on_commit` hook, one bill at a time, and the one-off data migration
that seeds the table from every bill already on the books. Sharing the
function is what keeps "latest non-blank wins" one rule rather than two that
can drift.

Nothing here posts, blocks, or refuses a bill (Rule 5) - the accept hook wraps
this in try/except and the migration is a plain loop over rows it already
trusts.
"""

from __future__ import annotations

from typing import Any


def normalise_mobile(value: str) -> str:
    """Digits only, then collapsed to the bare 10-digit Indian mobile, so
    '+91 98765-43210', '09876543210' and '9876543210' are one customer."""
    raw = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(raw) == 12 and raw.startswith("91"):
        return raw[2:]
    if len(raw) == 11 and raw.startswith("0"):
        return raw[1:]
    return raw


def upsert_customer(customer_model: Any, *, mobile: str, name: str, gstin: str) -> None:
    """Get-or-create by mobile; latest non-blank name wins; gstin fills when
    supplied. A blank name or gstin never wipes what is already stored - only a
    non-blank, *different* value overwrites (api-contract steps 6c/6d).

    Saves only when something actually changed, since `updated_at` drives the
    till's dataset delta pull - an unconditional save on every bill would push
    the whole customer list down every till forever.

    `mobile` is `varchar(15)`; a mobile whose digits are blank or exceed that is
    skipped rather than raising, so a malformed historic row cannot crash the
    backfill (and, symmetrically, cannot fail a live bill either).
    """
    mobile = normalise_mobile(mobile)
    if not mobile or len(mobile) > 15:
        return
    name = (name or "").strip()
    gstin = gstin or ""

    customer, created = customer_model.objects.get_or_create(
        mobile=mobile, defaults={"name": name, "gstin": gstin}
    )
    if created:
        return

    changed = False
    if name and name != customer.name:
        customer.name = name
        changed = True
    if gstin and gstin != customer.gstin:
        customer.gstin = gstin
        changed = True
    if changed:
        customer.save(update_fields=["name", "gstin", "updated_at"])


def backfill_customers(sale_model: Any, customer_model: Any) -> None:
    """One row per distinct mobile in `sell_sale`, oldest bill to newest.

    Walking the bills in that order and handing each one to `upsert_customer`
    is the whole algorithm: its latest-non-blank-wins rule does the "newest
    bill's name, newest B2B bill's gstin" work for free, and running this
    twice converges to the same rows both times (idempotent, keyed on mobile).
    """
    rows = (
        sale_model.objects.exclude(customer_mobile="")
        .order_by("billed_at", "id")
        .values_list("customer_mobile", "customer_name", "buyer_gstin")
    )
    for mobile, name, gstin in rows:
        upsert_customer(customer_model, mobile=mobile, name=name, gstin=gstin)
