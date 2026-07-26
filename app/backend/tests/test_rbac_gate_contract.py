"""One gate: every write resolves through the section ladder (#94).

The sidebar contract (#85) proved the *payload* matches the RBAC matrix. This
proves the *API* does — that no role which a section grants ``view`` can write in
it, and that the answer for every gated endpoint is computed from
``section_access_for`` rather than restated in a role list beside the view.

Three things are asserted, in the order they can go wrong:

1. **the gates** — for every seeded role and every gated endpoint group, allow
   or deny is exactly what the matrix says. A denied caller gets 403; an allowed
   one gets past the permission layer and fails on the payload or the pk
   instead, which is the thing being measured.
2. **the approvers** — the write-off, V-flip and adjustment approver lists hold
   only roles the matrix puts at ``approve`` on that document's own section, in
   the code defaults *and* in every undecided row on a running install.
3. **the exceptions** — the four gates that stayed role lists are registered
   with a reason, and no new role-list constant has appeared without one.
"""

from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path

import pytest
from _creds import TEST_PASSWORD
from _rbac import make_role
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.rbac_matrix import KNOWN_ROLE_CODES, roles_with_capability, section_access_for
from accounts.role_lists import REGISTERED_ROLE_LISTS
from accounts.sections import CAP_APPROVE, CAP_MANAGE, CAP_OPERATE, CAP_VIEW, meets
from approvals.models import Approval, ApprovalPolicy, ApprovalStatus
from masters.models import Gstin, LegalEntity, Store
from outbound.maker_checker import KINDS
from outbound.models import StockAdjustment, WriteOff

BACKEND = Path(__file__).resolve().parent.parent

#: A pk nothing can own, so an allowed caller lands on 404 and a denied one on
#: 403 — the two are the whole discriminator, no fixture documents needed.
ABSENT = 999_999

#: (label, section, minimum rung, method, path). The mapping under test: every
#: outbound write plus the inbound queue, each named with the gate it claims.
GATED_ENDPOINTS: list[tuple[str, str, str, str, str]] = [
    ("transfer create", "transfer", CAP_OPERATE, "post", "/api/outbound/transfers"),
    (
        "transfer dispatch",
        "transfer",
        CAP_OPERATE,
        "post",
        f"/api/outbound/transfers/{ABSENT}/dispatch",
    ),
    (
        "transfer receive",
        "transfer",
        CAP_OPERATE,
        "post",
        f"/api/outbound/transfers/{ABSENT}/receive",
    ),
    # Gap closure sits a rung above the daily transfer work: the design gives the
    # decision to the Operations Head, not to whoever sent or received the carton.
    (
        "gap closure raise",
        "transfer",
        CAP_APPROVE,
        "post",
        f"/api/outbound/transfers/{ABSENT}/gap-closure",
    ),
    (
        "gap closure post",
        "transfer",
        CAP_APPROVE,
        "post",
        f"/api/outbound/gap-closures/{ABSENT}/submit",
    ),
    (
        "gap closure ask again",
        "transfer",
        CAP_APPROVE,
        "post",
        f"/api/outbound/gap-closures/{ABSENT}/request-approval",
    ),
    ("mark damaged", "return_to_brand", CAP_OPERATE, "post", "/api/outbound/mark-damaged"),
    ("rtv create", "return_to_brand", CAP_OPERATE, "post", "/api/outbound/rtvs"),
    ("rtv submit", "return_to_brand", CAP_OPERATE, "post", f"/api/outbound/rtvs/{ABSENT}/submit"),
    ("adjustment create", "stock_count", CAP_OPERATE, "post", "/api/outbound/adjustments"),
    (
        "adjustment submit",
        "stock_count",
        CAP_OPERATE,
        "post",
        f"/api/outbound/adjustments/{ABSENT}/submit",
    ),
    (
        "adjustment ask again",
        "stock_count",
        CAP_OPERATE,
        "post",
        f"/api/outbound/adjustments/{ABSENT}/request-approval",
    ),
    ("writeoff create", "stock_count", CAP_OPERATE, "post", "/api/outbound/writeoffs"),
    (
        "writeoff submit",
        "stock_count",
        CAP_OPERATE,
        "post",
        f"/api/outbound/writeoffs/{ABSENT}/submit",
    ),
    (
        "writeoff ask again",
        "stock_count",
        CAP_OPERATE,
        "post",
        f"/api/outbound/writeoffs/{ABSENT}/request-approval",
    ),
    ("vflip create", "stock", CAP_MANAGE, "post", "/api/outbound/vflips"),
    ("vflip submit", "stock", CAP_MANAGE, "post", f"/api/outbound/vflips/{ABSENT}/submit"),
    (
        "vflip ask again",
        "stock",
        CAP_MANAGE,
        "post",
        f"/api/outbound/vflips/{ABSENT}/request-approval",
    ),
    ("inbound queue", "receive_goods", CAP_VIEW, "get", "/api/inbound/queue"),
    # Booking (#130). The list opens at `view` - the rung the ratified table now
    # gives a store - while placing one, and the AI draft that begins placing
    # one, stay at `operate`. Before #130 these three answered any authenticated
    # caller, so the table's Booking column decided nothing.
    ("booking list", "booking", CAP_VIEW, "get", "/api/bookings"),
    ("booking detail", "booking", CAP_VIEW, "get", f"/api/bookings/{ABSENT}"),
    ("booking create", "booking", CAP_OPERATE, "post", "/api/bookings"),
    ("booking draft", "booking", CAP_OPERATE, "post", "/api/bookings/draft"),
]

#: Which section each wired approval kind belongs to — the section whose
#: ``approve`` rung decides who may clear it.
APPROVAL_SECTION = {
    "writeoff": "stock_count",
    "adjustment": "stock_count",
    "vflip": "stock",
    "gap_closure": "transfer",
    "damage": "return_to_brand",
}


def _role(code: str) -> Role:
    return make_role(code, code.title(), nav_groups=["home"], is_system=True)


def _user(username: str, role: Role | None, **kwargs) -> User:
    user = User.objects.create(username=username, role=role, scope_type="all", **kwargs)
    user.set_password(TEST_PASSWORD)
    user.save()
    return user


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _call(client: APIClient, method: str, path: str):
    return client.post(path, {}, format="json") if method == "post" else client.get(path)


# --- 1. The gates ----------------------------------------------------------
@pytest.mark.parametrize("role_code", KNOWN_ROLE_CODES)
def test_every_gate_answers_what_the_matrix_says(db, role_code):
    """The contract itself: expectation computed from the sheet, never restated.

    Store scope is a separate gate, so these users are network-scoped — this
    measures the rung and nothing else.
    """
    client = _client(_user(f"g_{role_code}", _role(role_code)))
    for label, section, minimum, method, path in GATED_ENDPOINTS:
        allowed = meets(section_access_for(role_code)[section]["capability"], minimum)
        resp = _call(client, method, path)
        denied = resp.status_code == 403
        assert denied is not allowed, (
            f"{role_code} on {label} ({section}:{minimum}): "
            f"matrix says {'allow' if allowed else 'deny'}, API said {resp.status_code}"
        )


def test_accounts_cannot_write_anything_it_may_only_view(db):
    """The finding this issue exists for, stated as its own assertion.

    Accounts holds ``view`` on transfer, stock count, return to brand and stock,
    and ``manage`` on money alone. It must not create, submit, dispatch, receive,
    convert ownership or destroy stock on any of them.
    """
    client = _client(_user("acc", _role("accounts")))
    for label, _section, _minimum, method, path in GATED_ENDPOINTS:
        status = _call(client, method, path).status_code
        if method == "get":
            # Reads are the point of `view` - the inbound queue and the booking
            # list are Accounts' to open, and asserting that keeps this test
            # measuring both halves rather than skipping the read rows.
            assert status != 403, label
        else:
            assert status == 403, label


def test_the_two_store_roles_get_identical_answers_on_outbound(db):
    """One persona, one answer — on the outbound endpoints (#96 narrows this).

    The manager and the cashier legitimately diverge on ``staff`` alone; on every
    outbound gate they are the same person doing the same job, and the old write
    list naming only ``store_manager`` was a plain bug.
    """
    manager = _client(_user("mgr", _role("store_manager")))
    cashier = _client(_user("cash", _role("store_staff")))
    for label, _section, _minimum, method, path in GATED_ENDPOINTS:
        assert (
            _call(manager, method, path).status_code == _call(cashier, method, path).status_code
        ), label


def test_superuser_break_glass_passes_every_gate(db):
    """``require_section`` resolves a superuser to ``manage`` everywhere, so the
    break-glass account keeps working after the gates move."""
    client = _client(_user("root", None, is_superuser=True))
    for label, _section, _minimum, method, path in GATED_ENDPOINTS:
        assert _call(client, method, path).status_code != 403, label


# --- 2. The approvers ------------------------------------------------------
def test_code_default_approvers_hold_only_roles_the_matrix_trusts():
    """No approver default names a role the matrix gives only ``view``."""
    for kind in KINDS.values():
        section = APPROVAL_SECTION[kind.code]
        can_approve = set(roles_with_capability(section, CAP_APPROVE))
        # Nobody the matrix trusts is ever dropped…
        assert can_approve <= set(kind.approver_roles), kind.code
        # …and exactly one kind adds anyone: damage flags, whose confirmer holds
        # the same `return_to_brand: operate` rung as the store person who
        # raises them (#138), so the ladder cannot tell the two apart. Named per
        # kind, so no *other* family can quietly inherit the widening.
        allowed_extra = (
            REGISTERED_ROLE_LISTS["outbound.damage_confirmers"].roles
            if kind.code == "damage"
            else frozenset()
        )
        assert set(kind.approver_roles) - can_approve <= allowed_extra, kind.code
        # The band may add the in-charge, and nothing else — that one addition
        # is the registered exception, so it is named here rather than assumed.
        extra = set(kind.band_roles) - can_approve
        assert extra <= {"store_manager"}, kind.code
        assert "accounts" not in set(kind.approver_roles) | set(kind.band_roles), kind.code


def test_a_freshly_raised_approval_names_no_view_only_role(db):
    """The defaults reach the row, which is what ``can_decide`` actually reads.

    Asserting over whatever the database happens to hold would pass on an empty
    one and prove nothing, so this raises a real request through the module that
    owns it and checks the list frozen onto it.
    """
    from outbound.maker_checker import request_document_approval

    store = _store("SEEDQ", "10AAACK1234M1Z7")
    maker = _user("wh_maker", _role("warehouse"))
    doc = WriteOff.objects.create(store=store, created_by=maker, reason="dead stock")
    doc.lines.create(sku_code="Q1", qty=2, unit_cost_paise=45_000)

    approval = request_document_approval(doc, requested_by=maker)

    assert approval is not None
    trusted = set(roles_with_capability(APPROVAL_SECTION["writeoff"], CAP_APPROVE))
    assert set(approval.approver_roles) <= trusted
    assert "accounts" not in approval.approver_roles


#: What migration 0008 finds on the alpha: the frozen outbound admin list.
STALE_APPROVERS = ["accounts", "ho_ops", "it_admin", "owner"]


def _store(code: str, gstin_number: str) -> Store:
    entity = LegalEntity.objects.create(code=code.lower(), name=code)
    gstin = Gstin.objects.create(
        gstin=gstin_number, legal_entity=entity, state_code="10", state_name="Bihar"
    )
    return Store.objects.create(code=code, name=code, store_type="store", gstin=gstin)


def _writeoff_approval(store: Store, maker: User, **overrides) -> Approval:
    doc = WriteOff.objects.create(store=store, created_by=maker, reason="stocktake")
    return Approval.objects.create(
        kind="writeoff",
        kind_label="Write-off",
        title="t",
        content_type=ContentType.objects.get_for_model(WriteOff),
        object_id=doc.pk,
        store=store,
        approver_roles=STALE_APPROVERS,
        made_by=maker,
        requested_by=maker,
        **{"status": ApprovalStatus.PENDING, **overrides},
    )


def test_the_migration_corrects_a_running_install(db):
    """Both stored halves, and the one that must not move.

    The policy row and every undecided request lose Accounts; a request already
    decided keeps the list it was decided under, because that is history.
    """
    migration = import_module("outbound.migrations.0008_rbac_approver_roles")
    policy = ApprovalPolicy.objects.create(
        kind="writeoff", band_roles=STALE_APPROVERS, escalated_roles=STALE_APPROVERS
    )
    maker = _user("maker", _role("warehouse"))
    checker = _user("checker", _role("accounts"))
    store = _store("DEO", "10AAACK1234M1Z5")
    pending = _writeoff_approval(store, maker)
    decided = _writeoff_approval(
        store,
        maker,
        status=ApprovalStatus.APPROVED,
        decided_by=checker,
        decided_at=timezone.now(),
    )

    migration.correct_stored_approvers(django_apps, None)

    policy.refresh_from_db()
    pending.refresh_from_db()
    decided.refresh_from_db()
    assert "accounts" not in policy.escalated_roles
    assert "accounts" not in policy.band_roles
    assert "accounts" not in pending.approver_roles
    assert decided.approver_roles == STALE_APPROVERS


def test_the_migration_does_not_invent_policy_rows(db):
    """A kind nobody has exercised has no row, and must not gain one — the code
    defaults create it correctly on first use."""
    migration = import_module("outbound.migrations.0008_rbac_approver_roles")

    migration.correct_stored_approvers(django_apps, None)

    assert not ApprovalPolicy.objects.exists()


def test_a_small_pending_adjustment_keeps_the_in_charge_with_no_policy_row(db):
    """The lazy-row case: a small one must still be the in-charge's to clear.

    ``ApprovalPolicy`` is materialised on first use, so an install can carry
    pending adjustments and no row at all. Reading the missing band as zero
    would push every one of them to HO and quietly take the store manager off
    a variance the design says is his — so the default band stands in.
    """
    migration = import_module("outbound.migrations.0008_rbac_approver_roles")
    maker = _user("adj_maker", _role("warehouse"))
    store = _store("BNK", "10AAACK1234M1Z8")
    doc = StockAdjustment.objects.create(store=store, created_by=maker, reason="miscount")
    small = Approval.objects.create(
        kind="adjustment",
        kind_label="Stock adjustment",
        title="t",
        content_type=ContentType.objects.get_for_model(StockAdjustment),
        object_id=doc.pk,
        store=store,
        value_paise=5_00_000,  # ₹5,000 — inside the ₹25,000 band
        approver_roles=STALE_APPROVERS,
        made_by=maker,
        requested_by=maker,
        status=ApprovalStatus.PENDING,
    )

    migration.correct_stored_approvers(django_apps, None)

    small.refresh_from_db()
    assert "store_manager" in small.approver_roles
    assert "accounts" not in small.approver_roles


# --- 3. The declared exceptions -------------------------------------------
#: The five gates the ladder provably cannot express. A change to this set is a
#: decision, which is exactly what the test is here to force.
EXPECTED_EXCEPTIONS = {
    "outbound.adjustment_band_in_charge",
    "outbound.damage_confirmers",
    "ptmapper.post_and_reverse_pt",
    "ptmapper.mapping_stewardship",
    "masters.writes",
}


def test_every_declared_exception_carries_a_reason():
    # Importing the view modules is what registers them.
    import masters.views  # noqa: F401
    import outbound.maker_checker  # noqa: F401
    import ptmapper.views  # noqa: F401

    assert set(REGISTERED_ROLE_LISTS) == EXPECTED_EXCEPTIONS
    for name, entry in REGISTERED_ROLE_LISTS.items():
        assert entry.reason.strip(), name
        assert entry.roles, name


# --- 4. Views that carry no section gate at all ---------------------------
#: Every view still sitting on a bare ``IsAuthenticated``, as of #130. For each
#: of these the ratified table decides nothing: any logged-in person reaches
#: them, whatever their row says. That is the hole the Booking endpoints were in
#: until this issue, and it was found by reading rather than by a test.
#:
#: This is a **baseline, not an approval**. Closing these is #124's, #131's and
#: #134's work, ticket by ticket, and each one leaves this list when its section
#: is decided. What the assertion buys today is that the list cannot grow by
#: accident: a new endpoint shipping ungated fails here, so leaving it ungated
#: becomes a recorded decision instead of an oversight.
UNGATED_VIEWS = {
    "accounts/views.py:MeView",
    "accounts/views.py:LogoutView",
    "approvals/views.py:ApprovalInboxView",
    "approvals/views.py:ApprovalListView",
    "approvals/views.py:ApprovalDecideView",
    "inbound/views.py:PendingBookingsView",
    "inbound/views.py:InvoiceDraftView",
    "inbound/views.py:GrnListCreateView",
    "inbound/views.py:GrnDetailView",
    "masters/views.py:LegalEntityListView",
    "masters/views.py:SkuLookupView",
    "masters/views.py:SummaryView",
    "outbound/views.py:TransferDetailView",
    "outbound/views.py:TransferGapListView",
    "outbound/views.py:GapClosureDetailView",
    "outbound/views.py:ScanLookupView",
    "outbound/views.py:RTVDetailView",
    "outbound/views.py:AdjustmentDetailView",
    "outbound/views.py:WriteOffDetailView",
    "outbound/views.py:VFlipDetailView",
    # #76: record-scoped via _load_stocktake (fail-closed on the queryset),
    # same shape as the other detail views above - no section gate of its own.
    "outbound/views.py:StocktakeDetailView",
    "outbound/views.py:StocktakeVarianceView",
    # #76: a dims-only lookup during a blind count, same shape as ScanLookupView.
    "outbound/views.py:CountLookupView",
    "ptmapper/views.py:PtFileListCreateView",
    "ptmapper/views.py:PtFileFromGrnView",
    "ptmapper/views.py:PtFileDetailView",
    "ptmapper/views.py:PtFileRerunView",
    "ptmapper/views.py:PtRowsUpdateView",
    "ptmapper/views.py:PtFileSendView",
    "ptmapper/views.py:PtFileRecallView",
    "ptmapper/views.py:PtFilePostView",
    "ptmapper/views.py:PtFileReverseView",
    "ptmapper/views.py:PtFilePriceView",
    "ptmapper/views.py:PtFileExportXlsxView",
    "ptmapper/views.py:PtFileExportView",
    "ptmapper/views.py:ReviewListView",
    "ptmapper/views.py:ReviewResolveView",
    "ptmapper/views.py:LookupProposalListView",
    "ptmapper/views.py:LookupProposalDecideView",
    "ptmapper/views.py:SuggestView",
    "ptmapper/views.py:ControlledValuesView",
    "search/views.py:GlobalSearchView",
    "stockledger/views.py:StockLedgerListView",
    "stockledger/views.py:StockLedgerSummaryView",
    "stockledger/views.py:InTransitView",
    "stockledger/views.py:QuarantineView",
    "stockledger/views.py:StockOnHandView",
    "vendors/views.py:VendorListCreateView",
}

_CLASS = re.compile(r"^class\s+(\w+)")
_BARE_AUTH = re.compile(r"^\s*permission_classes\s*=\s*\[IsAuthenticated\]\s*$")


def _views_with_no_section_gate() -> set[str]:
    """``path:ClassName`` for every view whose only permission is authentication.

    Source-level, because "this view names no section" is a fact about the code
    rather than about any one request: an endpoint nobody wrote a test for is
    exactly the one that ships open.
    """
    found = set()
    for path in BACKEND.rglob("*.py"):
        parts = set(path.parts)
        if "tests" in parts or "migrations" in parts or ".venv" in parts:
            continue
        current = ""
        for line in path.read_text().splitlines():
            named = _CLASS.match(line)
            if named:
                current = named.group(1)
            elif current and _BARE_AUTH.match(line):
                found.add(f"{path.relative_to(BACKEND).as_posix()}:{current}")
    return found


def test_no_new_endpoint_ships_without_a_section_gate():
    found = _views_with_no_section_gate()
    new = found - UNGATED_VIEWS
    assert not new, (
        "these views answer any authenticated caller, so the access table decides "
        "nothing about them - gate them with `require_section(...)`, or add them "
        f"to UNGATED_VIEWS and say in the ticket why they stay open: {sorted(new)}"
    )
    closed = UNGATED_VIEWS - found
    assert not closed, (
        "these views have been gated since the baseline was written - delete them "
        f"from UNGATED_VIEWS so the list keeps shrinking honestly: {sorted(closed)}"
    )


#: What a hand-kept gate is *called*. A constant naming a set of role codes in
#: this codebase has always ended in one of these, so the guard below is a
#: naming convention enforced, not a proof: a list called something else, or
#: built inline at its call site, still escapes. It catches the shape people
#: actually write, which is what a new one is overwhelmingly likely to be.
ROLE_LIST_NAME = re.compile(
    r"^\s*(_?[A-Z][A-Z0-9_]*(?:ROLES|APPROVERS|STEWARDS))\s*=\s*(.*)$", re.MULTILINE
)


def test_no_role_list_escapes_the_register():
    """A new hand-kept list must come through ``declare_role_list``.

    Without this the register decays into documentation of the four we happened
    to remember: the next gate someone writes as a set literal would gate just
    as hard and appear nowhere. Source-level because that is the only place the
    difference between "declared" and "invented" is visible.

    A list *derived* from the matrix is not hand-kept and passes — that is the
    whole point of deriving it.
    """
    allowed_sources = ("declare_role_list(", "roles_with_capability(", "tuple(sorted(")
    offenders = []
    for path in BACKEND.rglob("*.py"):
        parts = set(path.parts)
        if "tests" in parts or "migrations" in parts or ".venv" in parts:
            continue
        for name, rhs in ROLE_LIST_NAME.findall(path.read_text()):
            if not rhs.startswith(allowed_sources):
                offenders.append(f"{path.relative_to(BACKEND)}: {name}")
    assert not offenders, (
        "hand-kept role lists that never declared a reason — either gate them on "
        f"a section capability or register them: {offenders}"
    )
