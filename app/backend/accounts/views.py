"""Auth endpoints (JWT, simplejwt — ADR-0001 typed DRF stack).

`/api/auth/login` returns access + refresh + the full user profile (role, scope,
allowed stores, nav groups) so the PWA can resolve the shell before any other
call. Brute-force is guarded by a simple failure counter (flag-don't-block: it
only ever slows a *failing* login, never a working one).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.models import NAV_GROUPS, LoginAttempt, Role, ScopeType, User
from accounts.serializers import (
    AdminRoleSerializer,
    AdminUserSerializer,
    CustomTokenObtainPairSerializer,
    UserProfileSerializer,
)
from masters.models import Store

MAX_FAILURES = 5
LOCK_MINUTES = 15
RBAC_ADMIN_ROLES = {"owner", "it_admin"}


class IsRbacAdmin(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        role_code = getattr(getattr(request.user, "role", None), "code", "")
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or role_code in RBAC_ADMIN_ROLES)
        )


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        username = str(request.data.get("username", "")).strip()
        attempt = None
        if username:
            attempt, _ = LoginAttempt.objects.get_or_create(identifier=username)
            if attempt.locked_until and attempt.locked_until > timezone.now():
                mins = int((attempt.locked_until - timezone.now()).total_seconds()) // 60 + 1
                return Response(
                    {"detail": f"Too many failed attempts. Try again in {mins} min."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            if attempt:
                attempt.failures += 1
                if attempt.failures >= MAX_FAILURES:
                    attempt.locked_until = timezone.now() + timedelta(minutes=LOCK_MINUTES)
                    attempt.failures = 0
                attempt.save()
            raise

        if attempt:
            attempt.failures = 0
            attempt.locked_until = None
            attempt.save()
        response = Response(serializer.validated_data, status=status.HTTP_200_OK)
        _set_auth_cookies(
            response,
            access=str(serializer.validated_data.get("access", "")),
            refresh=str(serializer.validated_data.get("refresh", "")),
        )
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(UserProfileSerializer(request.user).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        refresh = request.data.get("refresh")
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                pass
        response = Response({"detail": "Logged out."})
        _clear_auth_cookies(response)
        return response


def _set_auth_cookies(response: Response, *, access: str, refresh: str | None = None) -> None:
    if access:
        response.set_cookie(
            "access_token",
            access,
            max_age=settings.JWT_ACCESS_COOKIE_MAX_AGE,
            httponly=True,
            secure=settings.JWT_COOKIE_SECURE,
            samesite=settings.JWT_COOKIE_SAMESITE,
            path="/",
        )
    if refresh:
        response.set_cookie(
            "refresh_token",
            refresh,
            max_age=settings.JWT_REFRESH_COOKIE_MAX_AGE,
            httponly=True,
            secure=settings.JWT_COOKIE_SECURE,
            samesite=settings.JWT_COOKIE_SAMESITE,
            path="/",
        )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/", samesite=settings.JWT_COOKIE_SAMESITE)
    response.delete_cookie("refresh_token", path="/", samesite=settings.JWT_COOKIE_SAMESITE)


class CookieRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        token_value = request.data.get("refresh") or request.COOKIES.get("refresh_token")
        if not token_value:
            return Response({"detail": "Refresh token is required."}, status=400)
        try:
            serializer = TokenRefreshSerializer(data={"refresh": str(token_value)})
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            response = Response(data, status=200)
            _set_auth_cookies(
                response,
                access=str(data.get("access", "")),
                refresh=str(data.get("refresh", "")) if data.get("refresh") else None,
            )
            return response
        except TokenError:
            response = Response({"detail": "Token is invalid or expired."}, status=401)
            _clear_auth_cookies(response)
            return response


class AdminMetaView(APIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin]

    def get(self, request: Request) -> Response:
        return Response(
            {
                "nav_groups": list(NAV_GROUPS),
                "scope_types": [
                    {"value": value, "label": label} for value, label in ScopeType.choices
                ],
                "stores": [
                    {"id": s.id, "code": s.code, "name": s.name, "store_type": s.store_type}
                    for s in Store.objects.filter(is_active=True).order_by("name")
                ],
            }
        )


class RoleListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin]
    serializer_class = AdminRoleSerializer
    queryset = Role.objects.all().order_by("name")


class RoleDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin]
    serializer_class = AdminRoleSerializer
    queryset = Role.objects.all()


class UserListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin]
    serializer_class = AdminUserSerializer

    def get_queryset(self) -> Any:
        return (
            User.objects.select_related("role", "entity")
            .prefetch_related("stores")
            .order_by("username")
        )


class UserDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin]
    serializer_class = AdminUserSerializer

    def get_queryset(self) -> Any:
        return User.objects.select_related("role", "entity").prefetch_related("stores")
