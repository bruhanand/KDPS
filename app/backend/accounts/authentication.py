from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import Token


class CookieOrHeaderJWTAuthentication(JWTAuthentication):
    """Authenticate with Authorization header first, then httpOnly access cookie."""

    def authenticate(self, request: Request) -> tuple[AbstractBaseUser, Token] | None:
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is not None:
                validated_token = self.get_validated_token(raw_token)
                return self.get_user(validated_token), validated_token

        raw_cookie = request.COOKIES.get("access_token")
        if not raw_cookie:
            return None
        validated_token = self.get_validated_token(raw_cookie)
        return self.get_user(validated_token), validated_token
