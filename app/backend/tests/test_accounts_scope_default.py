"""Fail-closed default (review medium: default scope_type=ALL was fail-open).

A user created without an explicit scope must default to the narrowest scope
(store → nothing until stores are assigned), never network-wide. Hermetic.
"""

from __future__ import annotations

from _creds import TEST_PASSWORD

from accounts.models import ScopeType, User


def test_new_user_defaults_to_narrowest_scope(db):
    user = User.objects.create(username="noscope")
    assert user.scope_type == ScopeType.STORE


def test_superuser_is_still_explicitly_all(db):
    su = User.objects.create_superuser(username="root", password=TEST_PASSWORD)
    assert su.scope_type == ScopeType.ALL
