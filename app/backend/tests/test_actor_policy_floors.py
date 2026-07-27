"""Issue #131 — configurable actors above four immutable people rules.

These tests stay at public seams: an API request succeeds or is refused, and a
ledger post either exists or does not.  They deliberately do not assert the
shape of the permission helpers that produce those answers.
"""

from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from accounts.models import ActorPolicy, Role, User
from accounts.rbac_matrix import section_access_for
from approvals.models import Approval, ApprovalPolicy
from core.gl import GLAccount, GLEntry
from core.posting import PostingFloorError, PostingRef, cr, dr, post_entries
from vendors.models import Vendor


def _user(
    username: str,
    role_code: str,
    *,
    scope_type: str = "all",
    section_access: dict | None = None,
) -> User:
    # Seeded from the ratified sheet exactly as `seed_foundation` does, unless a
    # test is about the access itself and says otherwise. A role built empty
    # would be refused everything and prove nothing about the floor underneath.
    role = Role.objects.create(
        code=role_code,
        name=role_code,
        section_access=section_access
        if section_access is not None
        else section_access_for(role_code),
    )
    user = User.objects.create(username=username, role=role, scope_type=scope_type)
    user.set_password("Policy-test-password-131!")
    user.save()
    return user


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_actor_policy_change_takes_effect_on_the_next_request(db):
    actor = _user("policy_actor", "warehouse")
    maker = _user("policy_maker", "owner")
    checker = _user("policy_checker", "it_admin")
    ActorPolicy.objects.update_or_create(
        action="masters.writes",
        defaults={"label": "Master writes", "roles": [], "description": ""},
    )
    assert _client(actor).post("/api/vendors", {}, format="json").status_code == 403

    proposed = _client(maker).patch(
        "/api/auth/admin/actor-policies/masters.writes",
        {"roles": ["warehouse"]},
        format="json",
    )
    assert proposed.status_code == 202
    assert _client(actor).post("/api/vendors", {}, format="json").status_code == 403

    decided = _client(checker).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )
    assert decided.status_code == 200
    admitted = _client(actor).post("/api/vendors", {}, format="json")
    assert admitted.status_code != 403


def test_policy_migration_retunes_only_untouched_existing_defaults(db):
    migration = import_module("approvals.migrations.0004_seed_approval_policies")
    writeoff = ApprovalPolicy.objects.get(kind="writeoff")
    for field, value in migration.SUPERSEDED["writeoff"].items():
        setattr(writeoff, field, value)
    writeoff.save()
    custom = ApprovalPolicy.objects.get(kind="vflip")
    custom.band_roles = ["brand_manager"]
    custom.save(update_fields=["band_roles"])

    migration.seed_policies(django_apps, None)

    writeoff.refresh_from_db()
    custom.refresh_from_db()
    assert writeoff.band_paise == 25_00_000
    assert writeoff.band_roles == ["store_manager", "ho_ops", "owner"]
    assert custom.band_roles == ["brand_manager"]


def test_store_scope_cannot_post_value_even_when_policy_grants_money_manage(db):
    actor = _user(
        "store_bookkeeper",
        "store_bookkeeper",
        scope_type="store",
        section_access={"money": {"capability": "manage", "label": "All"}},
    )
    vendor = Vendor.objects.create(code="floor-vendor", name="Floor Vendor")

    response = _client(actor).post(
        "/api/finledger/vendor/bill",
        {"vendor_id": vendor.pk, "amount": "1250.00", "description": "must not post"},
        format="json",
    )

    assert response.status_code == 403
    assert "store" in response.json()["detail"].lower()
    assert not GLEntry.objects.exists()


def test_brand_liability_cannot_post_without_a_named_head_office_person(db):
    voucher = PostingRef(doc_type="BILL", doc_number="26-27/HO/BILL/131")

    try:
        post_entries(
            voucher,
            [
                dr(GLAccount.INVENTORY, 125_000),
                cr(
                    GLAccount.VENDOR_PAYABLE,
                    125_000,
                    party_type="vendor",
                    party_code="FLOOR-VENDOR",
                ),
            ],
        )
    except PostingFloorError as exc:
        assert "head-office" in str(exc).lower()
    else:  # pragma: no cover - the assertion explains the required failure
        raise AssertionError("vendor liability posted without a named head-office person")

    assert not GLEntry.objects.exists()


@pytest.mark.parametrize("doc_type", ["PT", "VFL"])
def test_pt_and_vflip_cannot_post_without_a_named_head_office_person(db, doc_type):
    voucher = PostingRef(doc_type=doc_type, doc_number=f"26-27/HO/{doc_type}/131")
    actor = _user(f"{doc_type.lower()}_warehouse", "warehouse")

    with pytest.raises(PostingFloorError, match="Accounts or Owner"):
        post_entries(
            voucher,
            [
                dr(GLAccount.INVENTORY, 125_000),
                cr(GLAccount.CASH, 125_000),
            ],
            posted_by=actor,
        )

    assert not GLEntry.objects.exists()


def test_break_glass_passes_the_pt_floor_but_never_the_store_one(db):
    """The emergency key inwards a PT; it still cannot post value from a store.

    Rule 3 asks for a *named head-office human*, and break-glass is one — the
    ruling says so in the same breath as removing IT Admin from PT inwarding.
    Rule 2 has no such exemption, so the same superuser scoped to a store is
    refused.
    """
    role = Role.objects.create(code="it_admin", name="IT Admin")
    breakglass = User.objects.create(
        username="superadmin",
        full_name="System Superadmin (break-glass)",
        role=role,
        scope_type="all",
        is_superuser=True,
    )

    post_entries(
        PostingRef(doc_type="PT", doc_number="26-27/HO/PT/BREAKGLASS"),
        [dr(GLAccount.INVENTORY, 100), cr(GLAccount.CASH, 100)],
        posted_by=breakglass,
    )
    assert GLEntry.objects.count() == 2

    breakglass.scope_type = "store"
    breakglass.save(update_fields=["scope_type"])
    with pytest.raises(PostingFloorError, match="store-scoped"):
        post_entries(
            PostingRef(doc_type="PT", doc_number="26-27/HO/PT/BREAKGLASS-2"),
            [dr(GLAccount.INVENTORY, 100), cr(GLAccount.CASH, 100)],
            posted_by=breakglass,
        )
    assert GLEntry.objects.count() == 2


def test_unsaved_accounts_actor_is_not_a_named_head_office_person(db):
    role = Role.objects.create(code="accounts", name="Accounts")
    actor = User(username="synthetic_accounts", role=role, scope_type="all")
    voucher = PostingRef(doc_type="PT", doc_number="26-27/HO/PT/SYNTHETIC")

    with pytest.raises(PostingFloorError, match="named Accounts or Owner"):
        post_entries(
            voucher,
            [dr(GLAccount.INVENTORY, 100), cr(GLAccount.CASH, 100)],
            posted_by=actor,
        )


def test_policy_cannot_make_a_document_maker_their_own_checker(db):
    maker = _user("self_checker", "owner")
    subject = Role.objects.create(code="subject-role", name="Subject role")
    approval = Approval.objects.create(
        kind="floor_test",
        kind_label="Floor test",
        title="Self approval must stay impossible",
        content_type=ContentType.objects.get_for_model(subject),
        object_id=subject.pk,
        approver_roles=["owner"],
        made_by=maker,
        requested_by=maker,
    )

    response = _client(maker).post(
        f"/api/approvals/{approval.pk}/decide",
        {"action": "approve"},
        format="json",
    )

    assert response.status_code == 403
    assert "cannot approve" in response.json()["error"].lower()


def test_role_change_is_applied_only_after_a_second_access_admin_approves(db):
    maker = _user("role_change_maker", "owner")
    checker = _user("role_change_checker", "it_admin")
    target = Role.objects.create(code="retuned-role", name="Before")

    proposed = _client(maker).patch(
        f"/api/auth/admin/roles/{target.pk}",
        {"name": "After"},
        format="json",
    )
    assert proposed.status_code == 202
    target.refresh_from_db()
    assert target.name == "Before"

    self_decision = _client(maker).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )
    assert self_decision.status_code == 403
    target.refresh_from_db()
    assert target.name == "Before"

    second_decision = _client(checker).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )
    assert second_decision.status_code == 200
    target.refresh_from_db()
    assert target.name == "After"


def test_superuser_without_owner_or_it_admin_role_cannot_change_access(db):
    maker = _user("strict_floor_owner", "owner")
    outsider = _user("strict_floor_superuser", "warehouse")
    outsider.is_superuser = True
    outsider.save(update_fields=["is_superuser"])
    target = Role.objects.create(code="strict-floor-target", name="Before")

    refused_proposal = _client(outsider).patch(
        f"/api/auth/admin/roles/{target.pk}",
        {"name": "Bypassed"},
        format="json",
    )
    assert refused_proposal.status_code == 403

    proposed = _client(maker).patch(
        f"/api/auth/admin/roles/{target.pk}",
        {"name": "After"},
        format="json",
    )
    refused_decision = _client(outsider).post(
        f"/api/approvals/{proposed.json()['approval_id']}/decide",
        {"action": "approve"},
        format="json",
    )

    assert refused_decision.status_code == 403
    assert "owner or it admin" in refused_decision.json()["error"].lower()
    target.refresh_from_db()
    assert target.name == "Before"


def test_attempt_to_configure_away_a_floor_rule_is_refused_clearly(db):
    """An invented switch is refused out loud, not dropped on the floor.

    DRF ignores a field it does not know, which here would answer 202 to
    "allow_store_value_posting: true" and let an administrator believe they had
    turned a floor rule off.
    """
    owner = _user(
        "floor_editor", "owner", section_access={"setup": {"capability": "manage", "label": "F"}}
    )

    response = _client(owner).patch(
        "/api/auth/admin/actor-policies/masters.writes",
        {"allow_store_value_posting": True},
        format="json",
    )

    assert response.status_code == 400
    body = response.json()
    assert "floor rules" in body["detail"].lower()
    assert body["fields"] == ["allow_store_value_posting"]


def test_holding_the_floor_role_is_not_enough_without_the_setup_rung(db):
    """The floor sits *under* the ladder, it does not replace it.

    Owner and IT Admin are the only roles the ratified sheet gives
    ``setup: manage``, so both gates normally agree. They must both still be
    asked: an Owner whose Setup access was retuned away is not an administrator
    just because of the name on their role.
    """
    demoted = _user("owner_without_setup", "owner", section_access={})

    assert _client(demoted).get("/api/auth/admin/roles").status_code == 403


def test_actor_policy_cannot_add_a_role_outside_the_value_floor(db):
    owner = _user("value_floor_editor", "owner")
    Role.objects.create(code="accounts", name="Accounts")
    Role.objects.create(code="warehouse", name="Warehouse")

    response = _client(owner).patch(
        "/api/auth/admin/actor-policies/outbound.execute_vflip",
        {"roles": ["accounts", "owner", "warehouse"]},
        format="json",
    )

    assert response.status_code == 400
    assert "floor rule" in str(response.json()).lower()
