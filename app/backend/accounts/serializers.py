from __future__ import annotations

from typing import Any

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.models import NAV_GROUPS, Role, User
from masters.models import Store
from masters.scoping import scoped_stores


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


class AdminRoleSerializer(serializers.ModelSerializer):
    user_count = serializers.IntegerField(source="users.count", read_only=True)

    class Meta:
        model = Role
        fields = [
            "id",
            "code",
            "name",
            "description",
            "landing_page",
            "nav_groups",
            "permissions_map",
            "is_system",
            "is_active",
            "user_count",
        ]
        read_only_fields = ["is_system", "user_count"]

    def validate_nav_groups(self, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(NAV_GROUPS))
        if unknown:
            raise serializers.ValidationError(f"Unknown nav group(s): {', '.join(unknown)}")
        return value

    def validate_code(self, value: str) -> str:
        if self.instance and self.instance.is_system and value != self.instance.code:
            raise serializers.ValidationError("System role codes cannot be changed.")
        return value


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


class AdminUserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.filter(is_active=True),
        source="role",
        write_only=True,
        required=False,
        allow_null=True,
    )
    scope_label = serializers.CharField(source="get_scope_type_display", read_only=True)
    entity_name = serializers.CharField(source="entity.name", read_only=True)
    stores = StoreMiniSerializer(many=True, read_only=True)
    store_ids = serializers.PrimaryKeyRelatedField(
        queryset=Store.objects.filter(is_active=True),
        source="stores",
        write_only=True,
        many=True,
        required=False,
    )
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "role",
            "role_id",
            "scope_type",
            "scope_label",
            "entity",
            "entity_name",
            "stores",
            "store_ids",
            "is_active",
            "is_staff",
            "is_superuser",
            "date_joined",
            "password",
        ]
        read_only_fields = ["is_superuser", "date_joined"]

    def validate_password(self, value: str) -> str:
        if value:
            validate_password(value)
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        scope = attrs.get("scope_type") or getattr(self.instance, "scope_type", "all")
        stores = attrs.get("stores")
        if scope == "store" and stores is not None and len(stores) == 0:
            raise serializers.ValidationError({"store_ids": "A store-scoped user needs at least one store."})
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Password is required for a new user."})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> User:
        stores = validated_data.pop("stores", [])
        password = validated_data.pop("password", "")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        user.stores.set(stores)
        return user

    def update(self, instance: User, validated_data: dict[str, Any]) -> User:
        stores = validated_data.pop("stores", None)
        password = validated_data.pop("password", "")
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        if stores is not None:
            instance.stores.set(stores)
        return instance


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
