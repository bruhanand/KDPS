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
from corsheaders.defaults import default_headers
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env (DATABASE_URL, secrets, seed admin creds) — the served process and
# local manage.py commands both read it. Protected vars never go in code.
#
# override=True: this file is the authority on which local stack we are part of.
# .env is gitignored and only ever written by scripts/dev.sh, which stamps it
# with THIS worktree's DATABASE_URL — each Conductor workspace runs its own
# Postgres on its own port (scripts/workspace-env.sh). Default dotenv behaviour
# is the opposite, letting an inherited environment variable win, and that is a
# silent wrong-database bug: a shell that exported another workspace's URL, or a
# Conductor [environment_variables] entry, would migrate and seed a database
# belonging to somebody else's branch with nothing on screen to say so.
#
# Inert everywhere it must be. Render (render.yaml) and GitHub CI supply
# DATABASE_URL as real environment variables and never have a .env file to read,
# so there is nothing for override to override.
load_dotenv(BASE_DIR / ".env", override=True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "ci-secret-not-for-production")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

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
    "approvals.apps.ApprovalsConfig",
    "outbound.apps.OutboundConfig",
    "sell.apps.SellConfig",
    "alerts.apps.AlertsConfig",
    "offers.apps.OffersConfig",
    # Per-person Google Workspace inbox in the top bar. Reads no other app and
    # is read by none — mail writes no ledger and no document.
    "mail.apps.MailConfig",
    # Composition roots: read across the domain apps, imported by none of them.
    "search.apps.SearchConfig",
    "storefront.apps.StorefrontConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves Django's own static (admin, DRF browsable API) when
    # DEBUG=False, so the API can run as a single process behind Render/uvicorn
    # without a separate static server. The React app is a separate static site.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # The business unit / brand the caller picked in the top-bar switcher (#88).
    # Narrows what the scoping helpers answer; it can never widen it.
    "masters.unit_context.ActiveContextMiddleware",
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
# Cross-origin dev (PWA on :3000 → API on :8000) must be allowed to send the
# switcher's context headers, or every call silently falls back to network view.
CORS_ALLOW_HEADERS = (*default_headers, "x-kdps-unit", "x-kdps-brand")
# The broad Emergent-preview + localhost regexes are a credentialed wildcard on a
# *shared* preview domain (any `<x>.emergentagent.com` could ride the cookie), so
# they are gated to DEBUG (preview/dev) only. In production (DEBUG=0) CORS is driven
# purely by the explicit, exact-origin CORS_ALLOWED_ORIGINS allowlist below.
CORS_ALLOWED_ORIGIN_REGEXES = (
    [
        r"^https://.*\.emergentagent\.com$",
        r"^https://.*\.preview\.emergentagent\.com$",
        r"^http://localhost:\d+$",
        r"^http://127\.0\.0\.1:\d+$",
    ]
    if DEBUG
    else []
)
# Exact origins for non-Emergent / production deployments (comma-separated env).
CORS_ALLOWED_ORIGINS = [o for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o]
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

# WhiteNoise compressed storage (no manifest, so a missing reference can never
# 500 the admin). Run `manage.py collectstatic` at build time.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Kolkata"
LANGUAGE_CODE = "en-us"
