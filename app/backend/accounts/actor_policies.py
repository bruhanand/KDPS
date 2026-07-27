"""Stored who-may-act policy, above the immutable people-rule floor (#131)."""

from __future__ import annotations

from typing import Any

from accounts.models import ActorPolicy


def user_may_act(user: Any, action: str) -> bool:
    """Read the live policy for every decision; a missing row fails closed."""
    if not (user and getattr(user, "is_authenticated", False)):
        return False
    if getattr(user, "is_superuser", False):
        return True
    role_code = getattr(getattr(user, "role", None), "code", "")
    if not role_code:
        return False
    roles = ActorPolicy.objects.filter(action=action).values_list("roles", flat=True).first()
    return roles is not None and role_code in roles
