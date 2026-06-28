from __future__ import annotations

from django.urls import path

from files.views import download

urlpatterns = [
    path("<int:pk>/download", download, name="file-download"),
]
