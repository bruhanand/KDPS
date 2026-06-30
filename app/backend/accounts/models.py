"""Users, configurable roles, and the data-scope dimension (RBAC foundation).

Access is configurable *data*, not code (Rule 12): a `Role` row carries which
sidebar groups and which page-actions it may use, so a trained admin can add or
retune a role with no release. The deep permission matrix and second-eye spine
land with their slice; this is the working set the foundation needs.

Scope is a separate dimension from role (ADR-0003): a user is scoped `all /
entity / region / store_group / store` against the `LegalEntity → GSTIN → Store`
hierarchy, never by minting a per-store role.
"""

from __future__ import annotations

from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from accounts.managers import UserManager
from core.base import TimeStampedModel

# Canonical sidebar groups (the five layers + edges/admin + store quick-actions).
NAV_GROUPS = [
    "home",
    "master_data",
    "documents",
    "ledgers",
    "controls",
    "intelligence",
    "edges_admin",
    "store_ops",
]


class Role(TimeStampedModel):
    """A configurable role → what a user assigned to it can see and do."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=240, blank=True, default="")
    landing_page = models.CharField(max_length=60, default="home")
    nav_groups = models.JSONField(default=list)  # subset of NAV_GROUPS
    permissions_map = models.JSONField(default=dict)  # fine-grained, later
    is_system = models.BooleanField(default=False)  # protected from deletion
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ScopeType(models.TextChoices):
    ALL = "all", "All (network-wide)"
    ENTITY = "entity", "Legal entity"
    REGION = "region", "Region / state"
    STORE_GROUP = "store_group", "Store group"
    STORE = "store", "Single store"


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    username = models.CharField(max_length=60, unique=True)
    full_name = models.CharField(max_length=120, blank=True, default="")
    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="users"
    )
    scope_type = models.CharField(max_length=20, choices=ScopeType.choices, default=ScopeType.ALL)
    entity = models.ForeignKey(
        "masters.LegalEntity",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )
    stores = models.ManyToManyField("masters.Store", blank=True, related_name="users")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        ordering = ["username"]

    def __str__(self) -> str:
        return self.full_name or self.username


class LoginAttempt(models.Model):
    """Lightweight brute-force guard: N failures inside the window locks login."""

    identifier = models.CharField(max_length=120, unique=True)  # username
    failures = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.identifier}: {self.failures} fails"
