"""Django settings for the KDPS backend — K0 scaffold.

Intentionally minimal: this is the empty skeleton the CI gate proves green.
Auth/sessions (K5), roles/scoping (K6), the posting engine (K7) and the business
apps all arrive in later slices. Nothing business-shaped lives here yet.
"""

from __future__ import annotations

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key-not-for-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "core.apps.CoreConfig",
]

MIDDLEWARE: list[str] = []

ROOT_URLCONF = "config.urls"

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", "postgres://localhost:5432/kdps_dev"),
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Kolkata"
LANGUAGE_CODE = "en-us"
