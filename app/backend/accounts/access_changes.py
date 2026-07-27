"""Two-person application of user, role and permission changes (#131)."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from accounts.models import AccessChange, ActorPolicy, Role, User
from accounts.role_lists import ACCESS_ADMINISTRATORS
from accounts.serializers import (
    ActorPolicySerializer,
    AdminRoleSerializer,
    AdminUserSerializer,
    ApprovalPolicyAdminSerializer,
)
from approvals.models import ApprovalPolicy
from approvals.services import ApprovalError, ApprovalRightsError, request_approval


class AccessChangeError(ApprovalError):
    """A pending access change can no longer be applied safely."""


class AccessChangeRightsError(ApprovalRightsError):
    """The checker is outside the immutable access-administrator floor."""


SERIALIZERS = {
    AccessChange.Resource.ROLE: AdminRoleSerializer,
    AccessChange.Resource.USER: AdminUserSerializer,
    AccessChange.Resource.ACTOR_POLICY: ActorPolicySerializer,
    AccessChange.Resource.APPROVAL_POLICY: ApprovalPolicyAdminSerializer,
}


def is_access_administrator(user: Any) -> bool:
    if not (user and getattr(user, "is_authenticated", False)):
        return False
    return getattr(getattr(user, "role", None), "code", "") in ACCESS_ADMINISTRATORS


def _json_payload(resource: str, validated: dict[str, Any]) -> dict[str, Any]:
    if resource != AccessChange.Resource.USER:
        return dict(validated)

    payload: dict[str, Any] = {}
    for key, value in validated.items():
        if key in {"role", "entity"}:
            payload[f"{key}_id"] = value.pk if value is not None else None
        elif key in {"stores", "brands"}:
            payload[f"{key[:-1]}_ids"] = [row.pk for row in value]
        elif key == "password":
            if value:
                payload["password_hash"] = make_password(value)
        else:
            payload[key] = value
    return payload


@transaction.atomic
def propose_access_change(
    *,
    resource: str,
    actor: User,
    data: dict[str, Any],
    target: Any = None,
    partial: bool = False,
) -> tuple[AccessChange, Any]:
    """Validate and freeze a Setup mutation, then ask a second admin to apply it."""
    serializer_class = SERIALIZERS[resource]
    serializer = serializer_class(instance=target, data=data, partial=partial)
    serializer.is_valid(raise_exception=True)
    payload = _json_payload(resource, serializer.validated_data)
    operation = (
        AccessChange.Operation.UPDATE if target is not None else AccessChange.Operation.CREATE
    )
    target_name = (
        str(target) if target is not None else str(payload.get("name") or payload.get("code"))
    )
    summary = f"{operation.title()} {resource.replace('_', ' ')}: {target_name or 'new row'}"
    change = AccessChange.objects.create(
        resource=resource,
        operation=operation,
        target_id=getattr(target, "pk", None),
        payload=payload,
        summary=summary[:240],
        created_by=actor,
    )
    approval = request_approval(
        change,
        kind="access_change",
        kind_label="Access change",
        title=change.summary,
        made_by=actor,
        requested_by=actor,
        approver_roles=list(ACCESS_ADMINISTRATORS),
    )
    return change, approval


def _target(model: type, change: AccessChange) -> Any:
    if change.operation == AccessChange.Operation.CREATE:
        return model()
    try:
        return model.objects.select_for_update().get(pk=change.target_id)
    except model.DoesNotExist as exc:
        raise AccessChangeError("The row this access change targeted no longer exists.") from exc


def _apply_role(change: AccessChange) -> None:
    role = _target(Role, change)
    for key, value in change.payload.items():
        setattr(role, key, value)
    role.save()


def _apply_user(change: AccessChange) -> None:
    user = _target(User, change)
    payload = dict(change.payload)
    store_ids = payload.pop("store_ids", None)
    brand_ids = payload.pop("brand_ids", None)
    password_hash = payload.pop("password_hash", "")
    for key, value in payload.items():
        setattr(user, key, value)
    if password_hash:
        user.password = password_hash
    user.save()
    if store_ids is not None:
        user.stores.set(store_ids)
    if brand_ids is not None:
        user.brands.set(brand_ids)


def _apply_plain(model: type, change: AccessChange) -> None:
    row = _target(model, change)
    for key, value in change.payload.items():
        setattr(row, key, value)
    row.save()


@transaction.atomic
def apply_access_change(change: AccessChange, *, actor: User) -> None:
    """Approval callback: apply once, naming the second person who applied it."""
    if not is_access_administrator(actor):
        raise AccessChangeRightsError("Only Owner or IT Admin may apply access changes.")
    locked = AccessChange.objects.select_for_update().get(pk=change.pk)
    if locked.applied_at is not None:
        raise AccessChangeError("This access change has already been applied.")
    if locked.resource == AccessChange.Resource.ROLE:
        _apply_role(locked)
    elif locked.resource == AccessChange.Resource.USER:
        _apply_user(locked)
    elif locked.resource == AccessChange.Resource.ACTOR_POLICY:
        _apply_plain(ActorPolicy, locked)
    elif locked.resource == AccessChange.Resource.APPROVAL_POLICY:
        _apply_plain(ApprovalPolicy, locked)
    else:  # pragma: no cover - choices and the database constrain this
        raise AccessChangeError(f"Unsupported access resource {locked.resource!r}.")
    locked.applied_by = actor
    locked.applied_at = timezone.now()
    locked.save(update_fields=["applied_by", "applied_at", "updated_at"])
