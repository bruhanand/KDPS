from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import Token


class CookieOrHeaderJWTAuthentication(JWTAuthentication):
    """Authenticate with Authorization header first, then httpOnly access cookie."""

    # simplejwt's `AuthUser` is a TypeVar *constrained* to (AbstractBaseUser,
    # TokenUser) rather than bounded by AbstractBaseUser, so any override that
    # pins the return type - even correctly - reads as incompatible to mypy.
    # This class never overrides `get_user`, and the inherited `get_user`
    # (authentication.py:120) only ever looks up `self.user_model` - a real
    # Django user, never a `TokenUser` - so `AbstractBaseUser` is what this
    # method actually returns; the annotation was already accurate before this
    # pass, it is simplejwt's stub that cannot express it.
    def authenticate(  # type: ignore[override]
        self, request: Request
    ) -> tuple[AbstractBaseUser, Token] | None:
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is not None:
                validated_token = self.get_validated_token(raw_token)
                return self.get_user(validated_token), validated_token

        raw_cookie = request.COOKIES.get("access_token")
        if not raw_cookie:
            return None
        # `get_validated_token` is typed to take `bytes`, but the token backend
        # it delegates to (`backends.py:145`) branches on `isinstance(token,
        # bytes)` and otherwise treats the value as already-decoded text, so a
        # `str` cookie value works today - the declared parameter type is
        # stricter than the real implementation.
        validated_token = self.get_validated_token(raw_cookie)  # type: ignore[arg-type]
        return self.get_user(validated_token), validated_token
