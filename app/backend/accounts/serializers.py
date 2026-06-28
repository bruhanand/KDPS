from __future__ import annotations

from typing import Any

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.models import NAV_GROUPS, Role, User
from masters.views import scoped_stores


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = [
            "id",
            "code",
            "name",
            "description",
            "landing_page",
            "nav_groups",
            "is_system",
            "is_active",
        ]


class StoreMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    store_type = serializers.CharField()
    state_name = serializers.CharField(source="gstin.state_name")
    state_code = serializers.CharField(source="gstin.state_code")
    gstin_number = serializers.CharField(source="gstin.gstin")


class UserProfileSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    nav_groups = serializers.SerializerMethodField()
    landing_page = serializers.SerializerMethodField()
    scope_label = serializers.CharField(source="get_scope_type_display", read_only=True)
    entity_name = serializers.CharField(source="entity.name", read_only=True)
    stores = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "is_superuser",
            "role",
            "scope_type",
            "scope_label",
            "entity",
            "entity_name",
            "stores",
            "nav_groups",
            "landing_page",
        ]

    def get_nav_groups(self, obj: User) -> list[str]:
        if obj.is_superuser:
            return list(NAV_GROUPS)
        return list(obj.role.nav_groups) if obj.role else []

    def get_landing_page(self, obj: User) -> str:
        return obj.role.landing_page if obj.role else "home"

    def get_stores(self, obj: User) -> list[dict[str, Any]]:
        return StoreMiniSerializer(scoped_stores(obj), many=True).data


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user: User) -> Any:  # type: ignore[override]
        token = super().get_token(user)
        token["full_name"] = user.full_name
        token["role"] = user.role.code if user.role else None
        token["scope_type"] = user.scope_type
        return token

    def validate(self, attrs: Any) -> Any:
        data = super().validate(attrs)
        data["user"] = UserProfileSerializer(self.user).data
        return data
