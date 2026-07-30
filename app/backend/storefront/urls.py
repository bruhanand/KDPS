from __future__ import annotations

from django.urls import path

from storefront.views import DashboardView

urlpatterns = [
    path("dashboard", DashboardView.as_view(), name="store-dashboard"),
]
