from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import AccessChange, ActorPolicy, LoginAttempt, Role, User


class AccessReadOnlyAdmin:
    """Access changes go through Setup's maker-checker flow, never admin save."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Role)
class RoleAdmin(AccessReadOnlyAdmin, admin.ModelAdmin):
    list_display = ["name", "code", "landing_page", "is_system", "is_active"]
    list_filter = ["is_system", "is_active"]
    search_fields = ["name", "code"]


@admin.register(User)
class UserAdmin(AccessReadOnlyAdmin, DjangoUserAdmin):
    ordering = ["username"]
    list_display = ["username", "full_name", "role", "scope_type", "is_active", "is_superuser"]
    list_filter = ["role", "scope_type", "is_active", "is_superuser"]
    search_fields = ["username", "full_name"]
    filter_horizontal = ["stores", "groups", "user_permissions"]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Profile", {"fields": ("full_name", "role")}),
        ("Scope", {"fields": ("scope_type", "entity", "stores")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "full_name", "role", "scope_type"),
            },
        ),
    )


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ["identifier", "failures", "locked_until", "updated_at"]
    search_fields = ["identifier"]


@admin.register(ActorPolicy)
class ActorPolicyAdmin(AccessReadOnlyAdmin, admin.ModelAdmin):
    list_display = ["action", "label", "roles", "updated_at"]


@admin.register(AccessChange)
class AccessChangeAdmin(AccessReadOnlyAdmin, admin.ModelAdmin):
    list_display = ["summary", "created_by", "applied_by", "created_at", "applied_at"]
