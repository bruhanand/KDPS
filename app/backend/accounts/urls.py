from __future__ import annotations

from django.urls import path

from accounts.views import (
    ActorPolicyDetailView,
    ActorPolicyListView,
    AdminMetaView,
    ApprovalPolicyDetailView,
    ApprovalPolicyListCreateView,
    CookieRefreshView,
    LoginView,
    LogoutView,
    MeView,
    RoleDetailView,
    RoleListCreateView,
    UserDetailView,
    UserListCreateView,
)

urlpatterns = [
    path("login", LoginView.as_view(), name="login"),
    path("refresh", CookieRefreshView.as_view(), name="token-refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
    path("admin/meta", AdminMetaView.as_view(), name="rbac-admin-meta"),
    path("admin/roles", RoleListCreateView.as_view(), name="rbac-role-list"),
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
