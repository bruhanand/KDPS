from __future__ import annotations

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Users, Roles & Access"

    def ready(self) -> None:
        from accounts.access_changes import apply_access_change
        from accounts.models import AccessChange
        from approvals.hooks import register_on_approved

        register_on_approved(AccessChange, apply_access_change)
