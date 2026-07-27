"""Take a draft transfer past the Operations Head, in one line.

Since #137 no stock leaves any location until a second, senior person has
approved the transfer, so *every* suite that dispatches one has to clear it
first — including the dozen suites that are about something else entirely
(the PT in the carton, the in-transit bucket, gap closures, store scope).

Spelling the ritual out in each of them would put the same four lines in a
dozen places and, worse, would let one of them drift into approving as the
maker — which the engine refuses, but only at the moment the test is written.
So: one helper, which raises the request if the draft was built straight
through the ORM, and decides it as somebody who is provably not the maker.
"""

from __future__ import annotations

from typing import Any

from _creds import TEST_PASSWORD
from _rbac import make_role

from accounts.models import ScopeType, User
from approvals.services import approval_for, decide
from outbound.maker_checker import request_document_approval

#: Deliberately not one of the usernames any fixture builds: the checker must
#: never turn out to be the maker, and a fixed name that could collide would
#: make that a coin toss.
CHECKER_USERNAME = "transfer_checker"


def a_checker(entity: Any = None, role_code: str = "owner") -> User:
    """The second person on a transfer — the Owner, who overrides everything.

    Network-scoped, because a checker who cannot see the sending store would
    fail on entitlement rather than on the rule under test.
    """
    user = User.objects.filter(username=CHECKER_USERNAME).first()
    if user is None:
        user = User.objects.create_user(
            username=CHECKER_USERNAME,
            password=TEST_PASSWORD,
            role=make_role(role_code),
            entity=entity,
            scope_type=ScopeType.ALL,
        )
    return user


def approve_transfer(transfer: Any, *, checker: User | None = None) -> User:
    """Clear ``transfer`` for dispatch, and return who cleared it.

    A draft created through the API is already waiting in the inbox; one built
    straight through the ORM has never been asked, so ask on its maker's behalf
    first — the same request the serializer would have raised.
    """
    approval = approval_for(transfer)
    if approval is None:
        maker = transfer.created_by
        assert maker is not None, "an ORM-built transfer needs a created_by to ask on behalf of"
        approval = request_document_approval(transfer, requested_by=maker)
        assert approval is not None, "StoreTransfer is not wired for approval"

    entity = getattr(transfer.source_store.gstin, "legal_entity", None)
    checker = checker or a_checker(entity)
    decide(approval, actor=checker, action="approve")
    return checker
