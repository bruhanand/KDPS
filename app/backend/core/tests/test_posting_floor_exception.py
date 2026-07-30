"""Anti-cheat golden test — the store floor bends for the sale, and nowhere else.

The floor is "a store-scoped user never writes rupees into the books", enforced
inside the sole GL writer so no grant, view or shell call can route around it.
Selling needs one carve-out — the till has to post a bill while the customer is
standing there — and the whole risk of this slice is that the carve-out turns
out to be wider than it reads.

So these tests come at it from the outside: a store actor posting a *sale* of
allow-listed legs succeeds, and a store actor posting anything else, or a sale
carrying one leg that is not on the list, is refused exactly as before.
"""

from __future__ import annotations

import pytest

from accounts.models import Role, User
from core.floors import REGISTERED_FLOOR_EXCEPTIONS, STORE_NATIVE_SALE
from core.gl import GLAccount, GLEntry, trial_balance
from core.posting import PostingFloorError, PostingRef, cr, dr, post_entries

SALE = PostingRef(doc_type="SAL", doc_number="26-27/DEO/SAL/74")
RETURN = PostingRef(doc_type="SRT", doc_number="26-27/DEO/SRT/3")
TRANSFER = PostingRef(doc_type="STO", doc_number="26-27/DEO/STO/9")


def _till_actor() -> User:
    role, _ = Role.objects.get_or_create(code="store_staff", defaults={"name": "Store Staff"})
    return User.objects.create(
        username="deo-till",
        full_name="Deoghar Till",
        scope_type="store",
        role=role,
    )


def _sale_money_legs() -> list:
    """Event A for a ₹1,749.30 cash bill at 5% — the ordinary shape."""
    return [
        dr(GLAccount.CASH, 174930),
        cr(GLAccount.SALES_REVENUE, 166600),
        cr(GLAccount.OUTPUT_GST, 8330),
    ]


# --- the carve-out does what it is for --------------------------------------


@pytest.mark.django_db
def test_a_till_can_post_the_money_side_of_its_own_bill() -> None:
    post_entries(SALE, _sale_money_legs(), posted_by=_till_actor())
    assert GLEntry.objects.filter(doc_number=SALE.doc_number).count() == 3
    assert trial_balance() == 0


@pytest.mark.django_db
def test_a_till_can_post_the_cost_side_of_its_own_bill() -> None:
    post_entries(
        SALE,
        [dr(GLAccount.COGS, 90000), cr(GLAccount.INVENTORY, 90000)],
        posted_by=_till_actor(),
    )
    assert trial_balance() == 0


@pytest.mark.django_db
def test_a_till_can_post_a_plain_return() -> None:
    post_entries(
        RETURN,
        [
            dr(GLAccount.SALES_REVENUE, 166600),
            dr(GLAccount.OUTPUT_GST, 8330),
            cr(GLAccount.CREDIT_NOTE_LIABILITY, 174930),
        ],
        posted_by=_till_actor(),
    )
    assert trial_balance() == 0


@pytest.mark.django_db
def test_a_till_can_accrue_the_sor_liability_when_it_names_the_vendor() -> None:
    post_entries(
        SALE,
        [
            dr(GLAccount.COGS, 90000),
            cr(GLAccount.VENDOR_PAYABLE, 90000, party_type="vendor", party_code="V-ARROW"),
        ],
        posted_by=_till_actor(),
    )
    assert trial_balance() == 0


# --- and nothing more -------------------------------------------------------


@pytest.mark.django_db
def test_a_till_still_cannot_post_a_transfer() -> None:
    with pytest.raises(PostingFloorError):
        post_entries(
            TRANSFER,
            [dr(GLAccount.INVENTORY, 5000), cr(GLAccount.INVENTORY, 5000)],
            posted_by=_till_actor(),
        )
    assert GLEntry.objects.count() == 0


@pytest.mark.django_db
def test_a_till_still_cannot_post_pt_value() -> None:
    with pytest.raises(PostingFloorError):
        post_entries(
            PostingRef(doc_type="PT", doc_number="26-27/RAN-WH/PT/1"),
            [dr(GLAccount.INVENTORY, 5000), cr(GLAccount.VENDOR_PAYABLE, 5000)],
            posted_by=_till_actor(),
        )
    assert GLEntry.objects.count() == 0


@pytest.mark.django_db
def test_one_leg_outside_the_allow_list_drops_the_whole_bill_back_on_the_floor() -> None:
    # The carve-out is per-posting, not per-document: a SAL cannot be used as a
    # wrapper to slip an unrelated account past the floor.
    with pytest.raises(PostingFloorError):
        post_entries(
            SALE,
            [
                dr(GLAccount.CASH, 174930),
                cr(GLAccount.SALES_REVENUE, 166600),
                cr(GLAccount.GRNI, 8330),  # not a sale account
            ],
            posted_by=_till_actor(),
        )
    assert GLEntry.objects.count() == 0


@pytest.mark.django_db
def test_a_vendor_liability_with_no_named_vendor_is_refused() -> None:
    # Under the carve-out the SOR accrual is machine-computed *from a vendor's
    # settlement rate*. A payable with nobody on the other end is not that.
    with pytest.raises(PostingFloorError):
        post_entries(
            SALE,
            [dr(GLAccount.COGS, 90000), cr(GLAccount.VENDOR_PAYABLE, 90000)],
            posted_by=_till_actor(),
        )
    assert GLEntry.objects.count() == 0


@pytest.mark.django_db
def test_a_head_office_actor_is_unaffected_by_any_of_this() -> None:
    role, _ = Role.objects.get_or_create(code="accounts", defaults={"name": "Accounts"})
    ho = User.objects.create(
        username="ho-accounts", full_name="HO Accounts", scope_type="all", role=role
    )
    post_entries(
        TRANSFER, [dr(GLAccount.INVENTORY, 5000), cr(GLAccount.SUSPENSE, 5000)], posted_by=ho
    )
    assert trial_balance() == 0


# --- the register itself ----------------------------------------------------

#: Every declared carve-out from the posting floor. A change to this set is a
#: decision about who may write into the books, which is exactly what the test is
#: here to force somebody to make on purpose.
EXPECTED_FLOOR_EXCEPTIONS = {"core.store_native_sale_floor"}


def test_every_declared_floor_exception_carries_a_reason() -> None:
    assert set(REGISTERED_FLOOR_EXCEPTIONS) == EXPECTED_FLOOR_EXCEPTIONS
    for name, entry in REGISTERED_FLOOR_EXCEPTIONS.items():
        assert entry.reason.strip(), name
        assert entry.doc_types, name
        assert entry.accounts, name


def test_the_sale_carve_out_covers_only_the_two_selling_documents() -> None:
    assert STORE_NATIVE_SALE.doc_types == {"SAL", "SRT"}
    assert not STORE_NATIVE_SALE.covers("PT")
    assert not STORE_NATIVE_SALE.covers("STO")


def test_the_sale_carve_out_names_no_purchase_or_payment_account() -> None:
    # The accounts a store must never reach from the shop floor: goods-received
    # accruals, recoverable input tax, and the balancing account that hides
    # mistakes.
    forbidden = {GLAccount.GRNI, GLAccount.INPUT_GST, GLAccount.SUSPENSE}
    assert not (STORE_NATIVE_SALE.accounts & forbidden)
