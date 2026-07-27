"""Admin for the maker-checker spine (#70).

``ApprovalPolicy`` is editable because that is the whole point of it: the
tolerance and the value band are business numbers the owner retunes as stores
and volumes change, not constants that need a release (Rule 12).

``Approval`` is read-only. It is an audit record — who asked, who decided, when
and why — and a record you can quietly edit in the admin is not a record. The
one write path is ``approvals.services``.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin

from approvals.models import Approval, ApprovalPolicy


@admin.register(ApprovalPolicy)
class ApprovalPolicyAdmin(admin.ModelAdmin):
    list_display = ("kind", "tolerance_paise", "band_paise", "band_roles", "escalated_roles")
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(Approval)
class ApprovalAdmin(admin.ModelAdmin):
    list_display = ("kind_label", "title", "status", "made_by", "decided_by", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("title",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False
