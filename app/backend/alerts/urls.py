from __future__ import annotations

from django.urls import path

from alerts.views import AlertInboxView

urlpatterns = [
    path("alerts", AlertInboxView.as_view(), name="alert-inbox"),
]
