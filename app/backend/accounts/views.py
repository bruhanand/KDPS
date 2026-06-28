"""Auth endpoints (JWT, simplejwt — ADR-0001 typed DRF stack).

`/api/auth/login` returns access + refresh + the full user profile (role, scope,
allowed stores, nav groups) so the PWA can resolve the shell before any other
call. Brute-force is guarded by a simple failure counter (flag-don't-block: it
only ever slows a *failing* login, never a working one).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.models import LoginAttempt
from accounts.serializers import CustomTokenObtainPairSerializer, UserProfileSerializer

MAX_FAILURES = 5
LOCK_MINUTES = 15


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
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


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
        return Response({"detail": "Logged out."})
