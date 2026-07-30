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
from django.db.models import Count
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
from accounts.floors import RULES, cell_limits, describe_floors, floor_violations
from accounts.matrix import diff, invalid_cells, replacement_row, stored_row
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
from accounts.sections import (
    CAP_MANAGE,
    CAPABILITY_ORDER,
    CAPABILITY_WORDS,
    SECTIONS,
)
from accounts.serializers import (
    ActorPolicySerializer,
    AdminRoleSerializer,
    AdminUserSerializer,
    ApprovalPolicyAdminSerializer,
    CustomTokenObtainPairSerializer,
    UserProfileSerializer,
)
from accounts.till_pin import hash_till_pin, may_hold_till_pin, pin_problem
from approvals.models import ApprovalPolicy
from core.textsearch import search_term, text_filter
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


class TillPinView(APIView):
    """Set your own counter PIN (#182). Your own, and nobody else's.

    Self-service on purpose. An override's whole value is that it names who was
    standing at the counter, so an administrator who could set a manager's PIN
    could authorise a discount in that manager's name - which is why the caller
    proves who they are with their own password and the row written is their own.

    Not a `PATCH` on the user admin endpoint either: that surface is the
    two-administrator access-change path (`PendingAccessChangeMixin`), and a
    person changing their own credential is not an access change waiting on
    somebody else's approval - it is the same shape as changing a password.
    """

    permission_classes = [IsAuthenticated]

    def put(self, request: Request) -> Response:
        user = request.user
        if not may_hold_till_pin(user):
            return _refuse(
                "A counter PIN authorises an exception at a till, so it belongs to "
                "somebody who holds the second eye on selling at a store. Ask an "
                "administrator if that should be you.",
                "NOT_A_TILL_MANAGER",
                status.HTTP_403_FORBIDDEN,
            )
        pin = str(request.data.get("pin") or "")
        problem = pin_problem(pin)
        if problem:
            return _refuse(problem, "VALIDATION", status.HTTP_400_BAD_REQUEST)
        # The password check comes second so a bad PIN is answered as a bad PIN.
        # It comes at all because a counter is a shared machine: a screen left
        # signed in is otherwise a way to give yourself somebody else's override.
        if not user.check_password(str(request.data.get("current_password") or "")):
            return _refuse(
                "That is not your password, so the PIN was not changed.",
                "PASSWORD_WRONG",
                status.HTTP_403_FORBIDDEN,
            )
        user.till_pin_hash = hash_till_pin(pin)
        user.save(update_fields=["till_pin_hash"])
        # The till learns about it on its next sync, like every other fact about
        # this store - there is no push, and there does not need to be.
        return Response({"status": "set"})


def _refuse(message: str, code: str, http_status: int) -> Response:
    """The `{"error", "code"}` body every endpoint written for the till uses."""
    return Response({"error": message, "code": code}, status=http_status)


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


class AccessMatrixView(APIView):
    """The roles x sections grid an administrator edits (#173).

    The answer is the **stored** matrix - ``Role.section_access`` as it is
    today, not the seed table it started from - plus the cells the money floor
    has locked and the sentence to show over each. The grid is data all the way
    down: sections, rungs, roles and locks all arrive from here, so adding a
    section or ratifying a floor needs no front-end release (Rule 12).
    """

    # Both gates, like every sibling admin endpoint. The Setup rung and the
    # access-administrator floor are separate questions (a role can be granted
    # `setup: manage` and still not be Owner or IT Admin), and reading who may
    # do what across the whole business, with head counts, is the same secret
    # the roles list keeps.
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]

    def get(self, request: Request) -> Response:
        roles = Role.objects.annotate(head_count=Count("users")).order_by("name")
        return Response(
            {
                "sections": [{"code": code, "label": label} for code, label in SECTIONS],
                # The ladder with its words, so the grid never has to keep its
                # own copy of what "operate" means (Rule 12: the screen renders
                # the payload, it does not restate it).
                "capabilities": [
                    {"code": cap, "label": CAPABILITY_WORDS[cap]} for cap in CAPABILITY_ORDER
                ],
                # All four ratified rules, including the two no cell can express,
                # so the screen states the whole floor rather than the part it
                # happens to grey out.
                "rules": [{"rule": number, "text": text} for number, text in sorted(RULES.items())],
                "roles": [
                    {
                        "code": role.code,
                        "name": role.name,
                        "is_system": role.is_system,
                        "is_active": role.is_active,
                        "user_count": role.head_count,
                        "section_access": stored_row(role),
                        "locked": cell_limits(role.code),
                    }
                    for role in roles
                ],
            }
        )


class RoleAccessView(APIView):
    """Replace one role's row of the matrix - as a proposal, never as a save.

    Two things stand between an administrator and the stored row, and both are
    floor rules rather than policy:

    · the **money floor** (``accounts.floors``) refuses a cell that would put a
      store seat on the books or hand full Money or full Setup to a role the
      ruling does not trust - cell by cell, naming each one;
    · **"never by one person alone"** (rule 4) makes the write a proposal a
      second Owner or IT Admin applies through the existing approvals
      machinery. The api-contract sketched an immediate 200 here; a direct write
      would have been the one door in the system where one person could change
      a role, which is exactly what the rule this ticket is enforcing forbids.
      So the endpoint answers 202 with the approval to clear.
    """

    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]

    def put(self, request: Request, code: str) -> Response:
        try:
            role = Role.objects.get(code=code)
        except Role.DoesNotExist:
            return Response(
                {"error": f"No role with code {code!r}.", "code": "NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )

        unknown = sorted(set(request.data) - {"section_access"})
        if unknown:
            return Response(
                {
                    "error": (
                        "This endpoint sets section access and nothing else, and the "
                        "four floor rules cannot be configured away by adding a "
                        f"setting: {', '.join(unknown)}."
                    ),
                    "code": "VALIDATION",
                    "fields": unknown,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        requested = request.data.get("section_access")
        if not isinstance(requested, dict):
            return Response(
                {"error": "section_access must be an object.", "code": "VALIDATION"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invalid = invalid_cells(requested)
        if invalid:
            return Response(
                {"error": "; ".join(invalid), "code": "VALIDATION"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        crossed = floor_violations(role.code, requested)
        if crossed:
            return Response(
                {
                    "error": " ".join(describe_floors(crossed)),
                    "code": "FLOOR_LOCKED",
                    "cells": crossed,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        before = stored_row(role)
        after = replacement_row(requested, current=before)
        cells = diff(before, after)
        if not cells:
            return Response(
                {
                    "status": "unchanged",
                    "detail": "Nothing changed, so nobody was asked to approve anything.",
                    "code": role.code,
                    "section_access": before,
                }
            )

        change, approval = propose_access_change(
            resource=AccessChange.Resource.ROLE,
            actor=request.user,
            data={"section_access": after},
            target=role,
            partial=True,
            # The row as it stands *now* rides along with the diff. The proposal
            # is a whole-row replacement built from a grid somebody looked at
            # minutes ago, so the applier compares this against the row it is
            # about to overwrite and refuses if a second administrator moved it
            # in between - otherwise a stale column silently reverts their work.
            annotations={"cells": cells, "before": before},
            summary=(
                f"Access change: {role.name} - "
                + ", ".join(f"{c['section']} {c['from']}->{c['to']}" for c in cells)
            ),
        )
        response = _pending_response(change, approval)
        response.data["cells"] = cells
        return response


#: Users & Roles (#106) — name / code, same as every other master list.
ROLE_SEARCH_FIELDS = ("code", "name")
USER_SEARCH_FIELDS = ("username", "full_name")


class RoleListCreateView(PendingAccessChangeMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsRbacAdmin, IsAccessAdministrator]
    serializer_class = AdminRoleSerializer
    access_resource = AccessChange.Resource.ROLE

    def get_queryset(self) -> Any:
        qs = Role.objects.all().order_by("name")
        return text_filter(qs, search_term(self.request), ROLE_SEARCH_FIELDS)


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
        qs = (
            User.objects.select_related("role", "entity")
            .prefetch_related("stores", "brands")
            .order_by("username")
        )
        return text_filter(qs, search_term(self.request), USER_SEARCH_FIELDS)


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
