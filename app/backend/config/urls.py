"""Project URL configuration.

The API seam lives under `/api/...` (the Kubernetes ingress routes `/api` to the
backend). Auth, masters and dashboard are mounted here; the OpenAPI schema +
Swagger UI back the generated typed TS client (ADR-0001).
"""

from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def health(_request):
    return JsonResponse({"status": "ok", "service": "kdps-backend"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", health),
    path("api/auth/", include("accounts.urls")),
    path("api/masters/", include("masters.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
