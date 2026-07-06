"""Project URL configuration.

The API seam lives under `/api/...` (the Kubernetes ingress routes `/api` to the
backend). Auth, masters and dashboard are mounted here; the OpenAPI schema +
Swagger UI back the generated typed TS client (ADR-0001).
"""

from __future__ import annotations

import os

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import IsAuthenticated


def health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "kdps-backend"})


# Django admin ships with a seeded superuser; exposing /admin in production widens
# the attack surface. Mount it only in DEBUG (preview/dev) or when explicitly
# enabled via ENABLE_DJANGO_ADMIN=1.
_ENABLE_ADMIN = settings.DEBUG or os.environ.get("ENABLE_DJANGO_ADMIN") == "1"

urlpatterns = [
    path("api/health", health),
    path("api/auth/", include("accounts.urls")),
    path("api/masters/", include("masters.urls")),
    path("api/files/", include("files.urls")),
    path("api/", include("vendors.urls")),
    path("api/inbound/", include("inbound.urls")),
    path("api/ptmapper/", include("ptmapper.urls")),
    path("api/stockledger/", include("stockledger.urls")),
    path("api/finledger/", include("finledger.urls")),
    path(
        "api/schema/",
        SpectacularAPIView.as_view(permission_classes=[IsAuthenticated]),
        name="schema",
    ),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[IsAuthenticated]),
        name="docs",
    ),
]

if _ENABLE_ADMIN:
    urlpatterns.insert(0, path("admin/", admin.site.urls))
