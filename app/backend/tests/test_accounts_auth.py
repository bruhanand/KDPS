"""Unit tests for accounts.authentication + accounts.views — covering cookie-based
JWT auth, login/brute-force, logout, me, refresh, and RBAC admin endpoints."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import LoginAttempt, Role, ScopeType, User
from masters.models import Gstin, LegalEntity, Store


@pytest.fixture
def user(db):
    return User.objects.create_user(username="tester", password="Tester@123")


@pytest.fixture
def owner_role(db):
    return Role.objects.create(
        code="owner",
        name="Owner",
        nav_groups=["home", "master_data", "ledgers"],
        is_system=True,
    )


@pytest.fixture
def admin_user(db, owner_role):
    user = User.objects.create_user(username="admin_owner", password="Admin@123")
    user.role = owner_role
    user.scope_type = ScopeType.ALL
    user.save()
    return user


@pytest.fixture
def client():
    return APIClient()


# --- CookieOrHeaderJWTAuthentication -------------------------------------------


@pytest.mark.django_db
class TestCookieOrHeaderAuth:
    def test_header_auth_works(self, user, client):
        token = RefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.data["username"] == "tester"

    def test_cookie_auth_works(self, user, client):
        token = RefreshToken.for_user(user)
        client.cookies["access_token"] = str(token.access_token)
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.data["username"] == "tester"

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401


# --- LoginView -----------------------------------------------------------------


@pytest.mark.django_db
class TestLoginView:
    def test_successful_login(self, user, client):
        resp = client.post(
            "/api/auth/login",
            {"username": "tester", "password": "Tester@123"},
            format="json",
        )
        assert resp.status_code == 200
        assert "access" in resp.data
        assert "refresh" in resp.data
        assert "user" in resp.data
        # Cookies are set
        assert "access_token" in resp.cookies
        assert "refresh_token" in resp.cookies

    def test_bad_password(self, user, client):
        resp = client.post(
            "/api/auth/login",
            {"username": "tester", "password": "WrongPass!"},
            format="json",
        )
        assert resp.status_code == 401

    def test_brute_force_lockout(self, user, client):
        for _ in range(5):
            client.post(
                "/api/auth/login",
                {"username": "tester", "password": "Wrong!"},
                format="json",
            )
        # Sixth attempt with the correct password should be locked
        resp = client.post(
            "/api/auth/login",
            {"username": "tester", "password": "Tester@123"},
            format="json",
        )
        assert resp.status_code == 429
        assert "too many" in resp.data["detail"].lower()

    def test_successful_login_resets_failure_counter(self, user, client):
        # Two failed attempts
        for _ in range(2):
            client.post(
                "/api/auth/login",
                {"username": "tester", "password": "Wrong!"},
                format="json",
            )
        # Successful login resets the counter
        resp = client.post(
            "/api/auth/login",
            {"username": "tester", "password": "Tester@123"},
            format="json",
        )
        assert resp.status_code == 200
        attempt = LoginAttempt.objects.get(identifier="tester")
        assert attempt.failures == 0
        assert attempt.locked_until is None


# --- LogoutView ----------------------------------------------------------------


@pytest.mark.django_db
class TestLogoutView:
    def test_logout_blacklists_token(self, user, client):
        token = RefreshToken.for_user(user)
        client.force_authenticate(user=user)
        resp = client.post(
            "/api/auth/logout",
            {"refresh": str(token)},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["detail"] == "Logged out."
        # Cookies are cleared
        assert resp.cookies.get("access_token").value == ""

    def test_logout_with_invalid_refresh(self, user, client):
        client.force_authenticate(user=user)
        resp = client.post(
            "/api/auth/logout",
            {"refresh": "invalid-token"},
            format="json",
        )
        # Should still return 200 (graceful — invalid token is just ignored)
        assert resp.status_code == 200


# --- CookieRefreshView ---------------------------------------------------------


@pytest.mark.django_db
class TestCookieRefreshView:
    def test_refresh_from_body(self, user, client):
        token = RefreshToken.for_user(user)
        resp = client.post(
            "/api/auth/refresh",
            {"refresh": str(token)},
            format="json",
        )
        assert resp.status_code == 200
        assert "access" in resp.data

    def test_refresh_from_cookie(self, user, client):
        token = RefreshToken.for_user(user)
        client.cookies["refresh_token"] = str(token)
        resp = client.post("/api/auth/refresh", format="json")
        assert resp.status_code == 200
        assert "access" in resp.data

    def test_no_refresh_token_returns_400(self, client):
        resp = client.post("/api/auth/refresh", format="json")
        assert resp.status_code == 400

    def test_expired_refresh_returns_401(self, user, client):
        resp = client.post(
            "/api/auth/refresh",
            {"refresh": "expired.invalid.token"},
            format="json",
        )
        assert resp.status_code == 401


# --- MeView -------------------------------------------------------------------


@pytest.mark.django_db
class TestMeView:
    def test_returns_user_profile(self, user, client):
        client.force_authenticate(user=user)
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.data["username"] == "tester"
        assert "scope_type" in resp.data
        assert "nav_groups" in resp.data


# --- RBAC Admin endpoints ------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestAdminMetaView:
    def test_accessible_by_owner(self, admin_user, client):
        client.force_authenticate(user=admin_user)
        resp = client.get("/api/auth/admin/meta")
        assert resp.status_code == 200
        assert "nav_groups" in resp.data
        assert "scope_types" in resp.data
        assert "stores" in resp.data

    def test_rejected_for_non_admin(self, user, client):
        client.force_authenticate(user=user)
        resp = client.get("/api/auth/admin/meta")
        assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
class TestRoleListCreateView:
    def test_list_roles(self, admin_user, owner_role, client):
        client.force_authenticate(user=admin_user)
        resp = client.get("/api/auth/admin/roles")
        assert resp.status_code == 200
        assert len(resp.data) >= 1

    def test_create_role(self, admin_user, client):
        client.force_authenticate(user=admin_user)
        resp = client.post(
            "/api/auth/admin/roles",
            {
                "code": "store_mgr",
                "name": "Store Manager",
                "nav_groups": ["home", "store_ops"],
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["code"] == "store_mgr"

    def test_create_role_invalid_nav_group(self, admin_user, client):
        client.force_authenticate(user=admin_user)
        resp = client.post(
            "/api/auth/admin/roles",
            {"code": "bad", "name": "Bad Role", "nav_groups": ["unknown_group"]},
            format="json",
        )
        assert resp.status_code == 400


@pytest.mark.django_db(transaction=True)
class TestUserListCreateView:
    def test_list_users(self, admin_user, client):
        client.force_authenticate(user=admin_user)
        resp = client.get("/api/auth/admin/users")
        assert resp.status_code == 200
        assert len(resp.data) >= 1

    def test_create_user(self, admin_user, owner_role, client):
        client.force_authenticate(user=admin_user)
        entity = LegalEntity.objects.create(code="kdps", name="KDPS")
        gstin = Gstin.objects.create(
            legal_entity=entity, gstin="10AABCK1234A1Z5", state_code="10", state_name="Bihar"
        )
        store = Store.objects.create(code="DEO", name="Deoghar", gstin=gstin)
        resp = client.post(
            "/api/auth/admin/users",
            {
                "username": "new_user",
                "full_name": "New User",
                "password": "NewUser@123!",
                "role_id": owner_role.pk,
                "scope_type": "store",
                "store_ids": [store.pk],
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["username"] == "new_user"

    def test_create_user_without_password_fails(self, admin_user, client):
        client.force_authenticate(user=admin_user)
        resp = client.post(
            "/api/auth/admin/users",
            {"username": "nopass", "full_name": "No Pass"},
            format="json",
        )
        assert resp.status_code == 400

    def test_rejected_for_non_admin(self, user, client):
        client.force_authenticate(user=user)
        resp = client.get("/api/auth/admin/users")
        assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
class TestUserDetailView:
    def test_update_user(self, admin_user, owner_role, client):
        target = User.objects.create_user(username="target_user", password="Target@123")
        client.force_authenticate(user=admin_user)
        resp = client.patch(
            f"/api/auth/admin/users/{target.pk}",
            {"full_name": "Updated Name"},
            format="json",
        )
        assert resp.status_code == 200
        target.refresh_from_db()
        assert target.full_name == "Updated Name"

    def test_update_user_password(self, admin_user, client):
        target = User.objects.create_user(username="pwuser", password="Old@123!")
        client.force_authenticate(user=admin_user)
        resp = client.patch(
            f"/api/auth/admin/users/{target.pk}",
            {"password": "New@Pass456!"},
            format="json",
        )
        assert resp.status_code == 200
        target.refresh_from_db()
        assert target.check_password("New@Pass456!")
