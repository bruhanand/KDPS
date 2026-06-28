"""Django settings for the KDPS backend.

Foundation slice (Phase 0): the empty K0 skeleton is grown into the foundation —
auth (custom user + JWT, the `accounts` app), the masters spine (`masters` app),
DRF + drf-spectacular for the typed API seam (ADR-0001), and CORS for the PWA.
The money/ledger kernel lives untouched in `core`.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env (DATABASE_URL, secrets, seed admin creds) — the served process and
# local manage.py commands both read it. Protected vars never go in code.
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ["DJANGO_DEBUG"] == "1"
ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    # KDPS apps
    "core.apps.CoreConfig",
    "masters.apps.MastersConfig",
    "accounts.apps.AccountsConfig",
    "files.apps.FilesConfig",
    "vendors.apps.VendorsConfig",
    "inbound.apps.InboundConfig",
    "ptmapper.apps.PtmapperConfig",
    "stockledger.apps.StockledgerConfig",
    "finledger.apps.FinledgerConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ["DATABASE_URL"],
        conn_max_age=600,
    )
}

# The kernel's invariants — append-only ledgers, cross-store isolation — are
# meaningless on SQLite. Fail loudly rather than let the foundation tests pass
# vacuously on the wrong engine.
_engine = str(DATABASES["default"].get("ENGINE", ""))
if not _engine.endswith("postgresql"):
    raise RuntimeError(
        f"KDPS requires PostgreSQL, got ENGINE={_engine!r}. "
        "Point DATABASE_URL at a postgres:// URL."
    )

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "accounts.authentication.CookieOrHeaderJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "KDPS Operating System API",
    "DESCRIPTION": "Deterministic retail ERP for KDPS Lifestyle Pvt Ltd.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://.*\.emergentagent\.com$",
    r"^https://.*\.preview\.emergentagent\.com$",
    r"^http://localhost:\d+$",
    r"^http://127\.0\.0\.1:\d+$",
]
# Extra explicit origins for non-Emergent deployments (comma-separated env).
CORS_ALLOWED_ORIGINS = [
    o for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o
]
CSRF_TRUSTED_ORIGINS = [
    o
    for o in os.environ.get(
        "CSRF_TRUSTED_ORIGINS",
        "https://*.emergentagent.com",
    ).split(",")
    if o
]

JWT_COOKIE_SECURE = os.environ.get("JWT_COOKIE_SECURE", "1") == "1"
JWT_COOKIE_SAMESITE = os.environ.get("JWT_COOKIE_SAMESITE", "Lax")
JWT_ACCESS_COOKIE_MAX_AGE = int(os.environ.get("JWT_ACCESS_COOKIE_MAX_AGE", "3600"))
JWT_REFRESH_COOKIE_MAX_AGE = int(os.environ.get("JWT_REFRESH_COOKIE_MAX_AGE", "604800"))

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Kolkata"
LANGUAGE_CODE = "en-us"
