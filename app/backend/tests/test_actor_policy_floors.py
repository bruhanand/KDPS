"""Issue #131 — configurable actors above four immutable people rules.

These tests stay at public seams: an API request succeeds or is refused, and a
ledger post either exists or does not.  They deliberately do not assert the
shape of the permission helpers that produce those answers.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from accounts.models import ActorPolicy, Role, User
from approvals.models import Approval
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
    role = Role.objects.create(
        code=role_code,
        name=role_code,
        section_access=section_access or {},
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
    voucher = PostingRef(doc_type="PT", doc_number="26-27/HO/PT/131")

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
    owner = _user("floor_editor", "owner")

    response = _client(owner).patch(
        "/api/auth/admin/actor-policies/masters.writes",
        {"allow_store_value_posting": True},
        format="json",
    )

    assert response.status_code == 400
    assert "cannot be configured" in response.json()["detail"].lower()
