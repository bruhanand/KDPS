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

from accounts.access_changes import is_access_administrator, propose_access_change
from accounts.models import (
    NAV_GROUPS,
    AccessChange,
    ActorPolicy,
    LoginAttempt,
    Role,
    ScopeType,
    User,
)
from accounts.permissions import require_section
from accounts.sections import CAP_MANAGE, CAPABILITY_ORDER, SECTIONS
from accounts.serializers import (
    ActorPolicySerializer,
    AdminRoleSerializer,
    AdminUserSerializer,
    ApprovalPolicyAdminSerializer,
    CustomTokenObtainPairSerializer,
    UserProfileSerializer,
)
from approvals.models import ApprovalPolicy
from masters.models import Brand, Store

MAX_FAILURES = 5
LOCK_MINUTES = 15

# Managing users and roles *is* the Setup section. Gate the admin APIs on the
# section capability (config-driven) rather than a hardcoded role list: only
# Owner and Admin hold `setup: manage` in the RBAC matrix, so this is
# behaviour-identical to the old role check but now retunable as data (#85).
IsRbacAdmin = require_section("setup", CAP_MANAGE)


class IsAccessAdministrator(BasePermission):
    """Floor rule: editable Setup grants cannot grant permission to edit Setup."""

    message = "Only Owner or IT Admin may propose user, role, or permission changes."

    def has_permission(self, request: Request, view: Any) -> bool:
        return is_access_administrator(request.user)


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
                "nav_groups": list(NAV_GROUPS),  # legacy; nothing navigates by it
                # What the role editor actually edits: the sections in sidebar
                # order and the ladder each may be set to. Sent as data so adding
                # a section needs no front-end release (Rule 12).
                "sections": [{"code": code, "label": label} for code, label in SECTIONS],
                "capabilities": list(CAPABILITY_ORDER),
                "scope_types": [
                    {"value": value, "label": label} for value, label in ScopeType.choices
                ],
                "stores": [
                    {"id": s.id, "code": s.code, "name": s.name, "store_type": s.store_type}
                    for s in Store.objects.filter(is_active=True).order_by("name")
                ],
                # Brand-scoped users (a brand manager) are assigned brands, not
                # stores — the user editor needs the list to pick from (#88).
                "brands": [
                    {"id": b.id, "code": b.code, "name": b.name}
                    for b in Brand.objects.filter(is_active=True).order_by("name")
                ],
            }
        )


def _pending_response(change: AccessChange, approval: Any) -> Response:
    return Response(
        {
            "change_id": change.pk,
            "approval_id": approval.pk,
            "status": "pending_approval",
            "detail": "A different Owner or IT Admin must approve this change.",
        },
        status=status.HTTP_202_ACCEPTED,
    )


class PendingAccessChangeMixin:
    """Every Setup write becomes a proposal a second administrator applies."""

    access_resource: str

    def _propose(self, request: Request, *, target: Any = None, partial: bool = False) -> Response:
        # A field this serializer does not know is refused rather than dropped.
        # DRF's default is to ignore it, which is the one answer this endpoint
        # must never give: somebody sending `allow_self_approval: true` to
        # switch off a floor rule would get 202 and believe it worked. There is
        # no such flag and there never will be — so say so, out loud.
        writable = {
            name for name, field in self.get_serializer().fields.items() if not field.read_only
        }
        unknown = sorted(set(request.data) - writable)
        if unknown:
            return Response(
                {
                    "detail": (
                        "These are not settings on this row, and the four floor rules "
                        "cannot be configured away by adding one: "
                        f"{', '.join(unknown)}."
                    ),
                    "fields": unknown,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        change, approval = propose_access_change(
            resource=self.access_resource,
            actor=request.user,
            data=request.data,
            target=target,
            partial=partial,
        )
        return _pending_response(change, approval)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._propose(request)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._propose(
            request,
            target=self.get_object(),
            partial=bool(kwargs.get("partial", False)),
        )


class RoleListCreateView(PendingAccessChangeMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = AdminRoleSerializer
    queryset = Role.objects.all().order_by("name")
    access_resource = AccessChange.Resource.ROLE


class RoleDetailView(PendingAccessChangeMixin, generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = AdminRoleSerializer
    queryset = Role.objects.all()
    access_resource = AccessChange.Resource.ROLE


class UserListCreateView(PendingAccessChangeMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = AdminUserSerializer
    access_resource = AccessChange.Resource.USER

    def get_queryset(self) -> Any:
        return (
            User.objects.select_related("role", "entity")
            .prefetch_related("stores", "brands")
            .order_by("username")
        )


class UserDetailView(PendingAccessChangeMixin, generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = AdminUserSerializer
    access_resource = AccessChange.Resource.USER

    def get_queryset(self) -> Any:
        return User.objects.select_related("role", "entity").prefetch_related("stores", "brands")


class ActorPolicyListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = ActorPolicySerializer
    queryset = ActorPolicy.objects.all()


class ActorPolicyDetailView(PendingAccessChangeMixin, generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = ActorPolicySerializer
    queryset = ActorPolicy.objects.all()
    access_resource = AccessChange.Resource.ACTOR_POLICY
    lookup_field = "action"
    lookup_url_kwarg = "action"


class ApprovalPolicyListCreateView(PendingAccessChangeMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = ApprovalPolicyAdminSerializer
    queryset = ApprovalPolicy.objects.all()
    access_resource = AccessChange.Resource.APPROVAL_POLICY


class ApprovalPolicyDetailView(PendingAccessChangeMixin, generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = ApprovalPolicyAdminSerializer
    queryset = ApprovalPolicy.objects.all()
    access_resource = AccessChange.Resource.APPROVAL_POLICY
    lookup_field = "kind"
    lookup_url_kwarg = "kind"
