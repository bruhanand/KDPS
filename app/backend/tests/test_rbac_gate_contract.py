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
from accounts.sections import (
    CAP_APPROVE,
    CAP_MANAGE,
    CAP_OPERATE,
    CAP_VIEW,
    SECTION_CODES,
    meets,
)
from approvals.models import Approval, ApprovalPolicy, ApprovalStatus
from core.gl import GLEntry
from masters.models import Gstin, LegalEntity, Store
from outbound.maker_checker import KINDS
from outbound.models import StockAdjustment, WriteOff
from vendors.models import Vendor

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
    # The returnable pool is a read, so it sits at `view` - Accounts and the
    # Brand Manager open it. Creating and executing the return are *not* here:
    # the sheet puts a store and the warehouse on the same `operate` rung, and
    # #75 splits them, so a stored actor policy decides those two. See
    # `test_return_creation_uses_the_stored_actor_policy`.
    ("returnable pool", "return_to_brand", CAP_VIEW, "get", "/api/outbound/returnable-pool"),
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
    # PT making moved to the warehouse rung (#119): the list still opens at
    # `view`, but only `approve` and up may create — not from a screen, and
    # not from the API either.
    ("pt file list", "receive_goods", CAP_VIEW, "get", "/api/ptmapper/files"),
    ("pt file create", "receive_goods", CAP_APPROVE, "post", "/api/ptmapper/files"),
    # ...and the writes behind the same screen, which #119 left on a bare
    # `IsAuthenticated` while it moved the screen itself off the store. Editing
    # a mapped PT is making one, so each answers at the making rung.
    (
        "pt rows update",
        "receive_goods",
        CAP_APPROVE,
        "patch",
        f"/api/ptmapper/files/{ABSENT}/rows",
    ),
    ("pt file send", "receive_goods", CAP_APPROVE, "post", f"/api/ptmapper/files/{ABSENT}/send"),
    ("pt file rerun", "receive_goods", CAP_APPROVE, "post", f"/api/ptmapper/files/{ABSENT}/rerun"),
    # The first document in the inbound chain, and the one that posts quantity
    # into the stock ledger. Reading the queue is `view`; standing at the door
    # is `operate`.
    ("grn list", "receive_goods", CAP_VIEW, "get", "/api/inbound/grns"),
    ("grn create", "receive_goods", CAP_OPERATE, "post", "/api/inbound/grns"),
]

#: Which section each wired approval kind belongs to — the section whose
#: ``approve`` rung decides who may clear it.
APPROVAL_SECTION = {
    "writeoff": "stock_count",
    "adjustment": "stock_count",
    "vflip": "stock",
    "gap_closure": "transfer",
    "damage": "return_to_brand",
    "return_to_brand": "return_to_brand",
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
    if method in ("post", "patch"):
        return getattr(client, method)(path, {}, format="json")
    return client.get(path)


# --- 1. The gates ----------------------------------------------------------
def _stored_capability(role: Role, section: str) -> str:
    """What the *database* says this role holds - the only authority there is.

    #173 made the matrix an admin-editable screen, so ``rbac_matrix`` is now
    starting content and nothing more. Reading the expectation from the code
    table would make this test agree with a seed the business may have retuned
    months ago, and pass while every live gate answered something else.
    """
    role.refresh_from_db(fields=["section_access"])
    entry = (role.section_access or {}).get(section) or {}
    return str(entry.get("capability", "none"))


@pytest.mark.parametrize("role_code", KNOWN_ROLE_CODES)
def test_every_gate_answers_what_the_matrix_says(db, role_code):
    """The contract itself: expectation read from the stored row, never restated.

    Store scope is a separate gate, so these users are network-scoped — this
    measures the rung and nothing else.
    """
    role = _role(role_code)
    client = _client(_user(f"g_{role_code}", role))
    for label, section, minimum, method, path in GATED_ENDPOINTS:
        allowed = meets(_stored_capability(role, section), minimum)
        resp = _call(client, method, path)
        denied = resp.status_code == 403
        assert denied is not allowed, (
            f"{role_code} on {label} ({section}:{minimum}): "
            f"stored matrix says {'allow' if allowed else 'deny'}, API said {resp.status_code}"
        )


@pytest.mark.parametrize(
    ("label", "section", "minimum", "method", "path"),
    [row for row in GATED_ENDPOINTS if row[2] in (CAP_OPERATE, CAP_APPROVE)],
    ids=[row[0] for row in GATED_ENDPOINTS if row[2] in (CAP_OPERATE, CAP_APPROVE)],
)
def test_a_retuned_cell_moves_its_gate_with_it(db, label, section, minimum, method, path):
    """ "Whatever it says" - the half the old assertion could not see (#173).

    Comparing the API against the seed table proves the two agree on the seed.
    It cannot prove the gate is *reading* the stored row rather than the code
    one, which is the whole promise of an editable matrix. So: take a role the
    seed denies, grant it the rung on the Role row - no release, no restart -
    and the same call must stop answering 403.

    This is about *where the gate reads from*, not about when a change should
    land on someone mid-shift - that question is open and is #173's, not this
    test's (see the PR).
    """
    denied_by_the_seed = next(
        (
            code
            for code in KNOWN_ROLE_CODES
            if not meets(section_access_for(code)[section]["capability"], minimum)
        ),
        "",
    )
    if not denied_by_the_seed:
        pytest.skip(f"every seeded role already reaches {section}:{minimum} - nothing to retune")
    role = _role(denied_by_the_seed)
    client = _client(_user(f"retune_{denied_by_the_seed}_{section}_{minimum}", role))
    assert _call(client, method, path).status_code == 403, label

    role.section_access[section] = {"capability": minimum, "label": "Retuned in Setup"}
    role.save(update_fields=["section_access"])

    assert _call(client, method, path).status_code != 403, label


def test_the_floors_hold_whatever_the_stored_matrix_says(db):
    """Floors are asserted unconditionally - they are not cells (#173, PRD #104).

    A retuned matrix moves gates; it must never move a floor. This writes the
    most generous row the ladder can express straight onto the database, past
    the editor that would have refused it, and then asks the two floors that
    have somewhere to fail: a store seat still cannot post value to the books,
    and Setup rung or no Setup rung, a role outside Owner/IT Admin still cannot
    touch users and roles.
    """
    everything = {
        section: {"capability": CAP_MANAGE, "label": "Everything"} for section in SECTION_CODES
    }
    cashier = _role("store_staff")
    cashier.section_access = dict(everything)
    cashier.save(update_fields=["section_access"])
    warehouse = _role("warehouse")
    warehouse.section_access = dict(everything)
    warehouse.save(update_fields=["section_access"])

    store_user = _user("floor_cashier", cashier)
    store_user.scope_type = "store"
    store_user.save(update_fields=["scope_type"])
    vendor = Vendor.objects.create(code="floor-gate-vendor", name="Floor Gate Vendor")

    # Rule 2 - the books refuse the store, even holding `money: manage`.
    posted = _client(store_user).post(
        "/api/finledger/vendor/bill",
        {"vendor_id": vendor.pk, "amount": "1250.00", "description": "must not post"},
        format="json",
    )
    assert posted.status_code == 403
    assert not GLEntry.objects.exists()

    # Rule 4 - `setup: manage` is not the power to change users and roles.
    assert (
        _client(_user("floor_warehouse", warehouse))
        .patch(f"/api/auth/admin/roles/{cashier.pk}", {"name": "Bypassed"}, format="json")
        .status_code
        == 403
    )


def test_accounts_cannot_write_anything_it_may_only_view(db):
    """The finding this issue exists for, stated as its own assertion.

    Accounts holds ``view`` on transfer, stock count, return to brand and stock,
    and ``manage`` on money alone. It must not create, submit, dispatch, receive,
    create an ownership flip or destroy stock on any of them. Executing an
    already-approved V-flip is a separate stored actor policy.
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


@pytest.mark.parametrize(
    ("role_code", "allowed"),
    [("accounts", True), ("owner", True), ("warehouse", False), ("it_admin", False)],
)
def test_vflip_execution_uses_the_stored_actor_policy(db, role_code, allowed):
    client = _client(_user(f"vflip_execute_{role_code}", _role(role_code)))

    response = client.post(f"/api/outbound/vflips/{ABSENT}/submit", {}, format="json")

    assert (response.status_code != 403) is allowed


@pytest.mark.parametrize(
    ("role_code", "allowed"),
    [
        ("warehouse", True),
        ("owner", True),
        ("store_manager", False),
        ("store_staff", False),
        ("brand_manager", False),
        ("accounts", False),
    ],
)
@pytest.mark.parametrize(
    ("step", "path"),
    [("create", "/api/outbound/rtvs"), ("submit", f"/api/outbound/rtvs/{ABSENT}/submit")],
)
def test_return_creation_uses_the_stored_actor_policy(db, step, path, role_code, allowed):
    """A store may only mark damage; the warehouse creates and executes returns.

    This cannot be a row in ``GATED_ENDPOINTS`` because the ratified sheet gives
    the store and the warehouse the same ``operate`` rung on this section - "Mark
    damage only" against "Create & execute". The rung is the same, the job is
    not, so the narrower question is asked of a stored ``ActorPolicy`` row
    (``outbound.create_return_to_brand``) exactly as V-flip execution is.
    """
    client = _client(_user(f"rtb_{step}_{role_code}", _role(role_code)))

    response = client.post(path, {}, format="json")

    assert (response.status_code != 403) is allowed


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
#: Who the #104 ruling puts on each document family, in-band and above it. Once
#: approvers became data (#131) the matrix stopped being their source of truth —
#: the ruling deliberately overrides it (IT Admin off every money family,
#: Accounts onto V-flip, the Brand Manager onto returns). So the alarm that used
#: to compare defaults against the matrix compares the *seeded* rows against the
#: ruling instead: retuning a live install is data, but shipping a different
#: default is a decision, and this is where it gets made.
RATIFIED_APPROVERS = {
    "writeoff": (["store_manager", "ho_ops", "owner"], ["ho_ops", "owner"]),
    "adjustment": (["store_manager", "ho_ops", "owner"], ["ho_ops", "owner"]),
    "vflip": (["accounts", "owner"], ["owner"]),
    "return_to_brand": (["brand_manager", "owner"], ["owner"]),
    "transfer": (["ho_ops", "owner"], ["ho_ops", "owner"]),
    "stock_request": (["ho_ops", "owner"], ["ho_ops", "owner"]),
    "pt_reverse": (["accounts", "owner"], ["accounts", "owner"]),
    "gap_closure": (["ho_ops", "owner"], ["ho_ops", "owner"]),
    "damage": (["warehouse", "owner"], ["warehouse", "owner"]),
}


def test_every_wired_family_reads_its_approvers_from_the_ratified_row(db):
    """The live answer is stored policy, not a role list frozen in code."""
    for kind in KINDS.values():
        policy = ApprovalPolicy.objects.get(kind=kind.code)
        band, escalated = RATIFIED_APPROVERS[kind.code]
        assert policy.band_roles == band, kind.code
        assert policy.escalated_roles == escalated, kind.code


def test_no_seeded_family_lets_admin_or_a_cashier_approve():
    """Two cells of the ratified table, asserted across every family at once.

    Admin has no Money — IT Admin was taken off these lists by the ruling and a
    later retune of one row must not quietly put it back. And the only store
    seat that approves anything is the Store Manager, inside the band: a cashier
    never signs off what their own store lost.
    """
    for code, (band, escalated) in RATIFIED_APPROVERS.items():
        assert "it_admin" not in set(band) | set(escalated), code
        assert "store_cashier" not in set(band) | set(escalated), code
        assert "store_manager" not in escalated, code


#: Where the ruling deliberately seats an approver the sheet gives less than
#: ``approve`` on that family's own section. Each is a decision from #104, named
#: here so it stays one — the alarm below is what stops a *sixth* appearing by
#: accident when somebody retunes a seed.
RULING_OVERRIDES_THE_SHEET = {
    ("writeoff", "store_manager"): "the in-charge clears a small loss without going to HO",
    ("adjustment", "store_manager"): "same band, on the variance counting produces",
    ("vflip", "accounts"): "Accounts executes the flip, so Accounts signs the small ones",
    ("damage", "warehouse"): "a store reports damage; the warehouse confirms it (#138)",
    (
        "return_to_brand",
        "brand_manager",
    ): "the brand's own manager signs off returns to that brand, inside the band (#75)",
}


def test_every_seeded_approver_is_trusted_by_the_sheet_or_named_as_a_ruling():
    """The drift alarm, pointed at the ruling instead of only at the sheet.

    Approvers used to be read straight off the RBAC matrix, and a test asserted
    they never named a role the sheet gives only ``view``. #104 overrides the
    sheet on purpose in four places, so the assertion cannot simply be dropped —
    it becomes: an approver either holds ``approve`` on that family's section,
    or it is one of the four the ruling put there, with the reason written down.
    """
    for code, (band, escalated) in RATIFIED_APPROVERS.items():
        section = APPROVAL_SECTION.get(code)
        if section is None:
            continue  # a family the outbound slices have not wired yet
        trusted = set(roles_with_capability(section, CAP_APPROVE))
        for role in set(band) | set(escalated):
            if role in trusted:
                continue
            reason = RULING_OVERRIDES_THE_SHEET.get((code, role))
            assert reason, f"{code}: {role!r} approves but the sheet does not trust it"


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
    trusted.add("store_manager")  # the ratified within-band in-charge
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
    policy = ApprovalPolicy.objects.get(kind="writeoff")
    policy.band_roles = STALE_APPROVERS
    policy.escalated_roles = STALE_APPROVERS
    policy.save(update_fields=["band_roles", "escalated_roles"])
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

    before = set(ApprovalPolicy.objects.values_list("kind", flat=True))
    migration.correct_stored_approvers(django_apps, None)
    assert set(ApprovalPolicy.objects.values_list("kind", flat=True)) == before


def test_the_migration_leaves_a_small_pending_adjustment_with_the_in_charge(db):
    """Correcting a running install must not take the store manager off a
    variance the design says is his.

    The migration rewrites the approver list frozen onto every pending
    approval. Reading the band as zero while it did so would push every small
    adjustment to HO — so the ₹25,000 band decides, and ₹5,000 stays local.
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
#: The two gates that stayed in code once who-may-act became data (#131) —
#: both are floor rules, and a floor stored in editable policy could configure
#: itself away. A change to this set is a decision, which is exactly what the
#: test is here to force.
EXPECTED_EXCEPTIONS = {
    "accounts.access_administrators_floor",
    "accounts.head_office_value_actors_floor",
    # #173, the third and the decision this list exists to force. The access
    # matrix became editable, so rule 2 ("a store never posts value to the
    # books") needed a *cell* floor as well as the engine one - and the matrix
    # is keyed by role while store-ness is a property of scope, so the two store
    # seats have to be named. The other two floors reuse the lists already here
    # rather than retyping them, which is why only one name is new.
    "accounts.store_seats_floor",
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
    "inbound/views.py:GrnDetailView",
    # --- mail: ungated by design, and the only family here that is ----------
    #
    # Every other entry in this list is a view whose *rows* are protected some
    # other way. Mail is different in kind: there is no section to gate it on,
    # and there should not be one.
    #
    # A section cell answers "may this role reach this part of the business".
    # Mail is not part of the business — it is the caller's own inbox, and no
    # role in KDPS should be denied its own mail. Adding a fourteenth section
    # would have meant editing the ratified SIDEBAR RBAC sheet to add a row
    # whose every cell reads "yes", which is a change to a ratified artefact
    # that buys nothing.
    #
    # What replaces the gate is a stricter rule, not a looser one. Every read
    # starts at `request.user` and reaches a message only through that person's
    # own account (`mail/views.py:my_messages`), so the answer is not "the rows
    # this section allows" but "the rows that are yours" — a boundary per
    # person rather than per store, which is tighter than any cell could be.
    # It is enforced from the outside in `tests/test_mail_inbox.py`, including
    # the case where one person asks for another's message by its real id.
    "mail/views.py:MailStatusView",
    "mail/views.py:MailConnectView",
    "mail/views.py:MailCompleteView",
    "mail/views.py:MailDisconnectView",
    "mail/views.py:MailMessagesView",
    "mail/views.py:MailMessageView",
    "mail/views.py:MailReadView",
    "mail/views.py:MailUnreadView",
    "mail/views.py:MailAttachmentView",
    "mail/views.py:MailSendView",
    "masters/views.py:LegalEntityListView",
    # #147: the list of places stock may be *sent* to. Open on purpose, and the
    # one entry here that is a decision rather than a baseline. A store person
    # may send a carton to any sister store while holding no right at all at the
    # receiving end, so a section gate here would put the empty destination
    # picker straight back and take store-to-store transfer away again. It
    # answers with identity fields only — code, name, type, registration, state —
    # so an open answer discloses nothing a scope was keeping from anyone. The
    # acts it feeds stay gated where acts belong: create and dispatch check the
    # source store, receive checks the destination.
    "masters/views.py:LocationListView",
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
    # #74: record-scoped via _stock_requests (fail-closed on the queryset, both
    # ends of the ask) — same shape as the other detail views above.
    "outbound/views.py:StockRequestDetailView",
    # #74: the cross-location search is deliberately open past its own store —
    # showing quantity and identity everywhere is the whole point (Anand's
    # ruling of 26 July), the same "identity discloses nothing" shape as
    # LocationListView above and StockOnHandView below. What a section gate
    # would actually need to protect — cost, landed value, margin — is masked
    # per row instead, against the caller's own stores, not behind a section.
    "outbound/views.py:CrossLocationStockSearchView",
    "ptmapper/views.py:PtFileFromGrnView",
    "ptmapper/views.py:PtFileDetailView",
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
