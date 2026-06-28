from __future__ import annotations

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.views import (
    AdminMetaView,
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
    path("refresh", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
    path("admin/meta", AdminMetaView.as_view(), name="rbac-admin-meta"),
    path("admin/roles", RoleListCreateView.as_view(), name="rbac-role-list"),
    path("admin/roles/<int:pk>", RoleDetailView.as_view(), name="rbac-role-detail"),
    path("admin/users", UserListCreateView.as_view(), name="rbac-user-list"),
    path("admin/users/<int:pk>", UserDetailView.as_view(), name="rbac-user-detail"),
]
