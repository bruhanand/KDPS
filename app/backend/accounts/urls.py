from __future__ import annotations

from django.urls import path

from accounts.views import (
    AccessMatrixView,
    ActorPolicyDetailView,
    ActorPolicyListView,
    AdminMetaView,
    ApprovalPolicyDetailView,
    ApprovalPolicyListCreateView,
    CookieRefreshView,
    LoginView,
    LogoutView,
    MeView,
    RoleAccessView,
    RoleDetailView,
    RoleListCreateView,
    TillPinView,
    UserDetailView,
    UserListCreateView,
)

urlpatterns = [
    path("login", LoginView.as_view(), name="login"),
    path("refresh", CookieRefreshView.as_view(), name="token-refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
    # A manager's own counter PIN (#182). Under `me/` because that is exactly its
    # scope: this endpoint can only ever write the caller's own row.
    path("me/till-pin", TillPinView.as_view(), name="me-till-pin"),
    path("admin/meta", AdminMetaView.as_view(), name="rbac-admin-meta"),
    # The access matrix (#173). The api-contract sketched these at
    # `/api/accounts/...`, a prefix this project does not mount - accounts has
    # always lived under `/api/auth/`, and its admin surface under
    # `/api/auth/admin/`. Same endpoints, this app's own shelf.
    path("admin/access-matrix", AccessMatrixView.as_view(), name="access-matrix"),
    path("admin/roles", RoleListCreateView.as_view(), name="rbac-role-list"),
    # Keyed by role *code*, as the contract says: the grid knows codes, and a
    # code survives a reseed where a primary key does not. Declared above the
    # `<int:pk>` detail route only for readability; the converters keep them apart.
    path("admin/roles/<slug:code>/access", RoleAccessView.as_view(), name="rbac-role-access"),
    path("admin/roles/<int:pk>", RoleDetailView.as_view(), name="rbac-role-detail"),
    path("admin/users", UserListCreateView.as_view(), name="rbac-user-list"),
    path("admin/users/<int:pk>", UserDetailView.as_view(), name="rbac-user-detail"),
    path("admin/actor-policies", ActorPolicyListView.as_view(), name="actor-policy-list"),
    path(
        "admin/actor-policies/<path:action>",
        ActorPolicyDetailView.as_view(),
        name="actor-policy-detail",
    ),
    path(
        "admin/approval-policies",
        ApprovalPolicyListCreateView.as_view(),
        name="approval-policy-list",
    ),
    path(
        "admin/approval-policies/<str:kind>",
        ApprovalPolicyDetailView.as_view(),
        name="approval-policy-detail",
    ),
]
