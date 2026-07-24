from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.models import NAV_GROUPS, Role, User
from accounts.permissions import visible_sections
from accounts.sections import CAPABILITY_ORDER, is_valid_capability, is_valid_section
from masters.models import Store
from masters.scoping import scoped_stores, visible_store_ids

_T = TypeVar("_T")


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
            "section_access",
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

    def validate_section_access(self, value: dict[str, Any]) -> dict[str, Any]:
        # Retuning access is a data edit (Rule 12) — but keep it well-formed so a
        # typo can't silently open or hide a section. Every key must be a known
        # section and every capability a known rung.
        if not isinstance(value, dict):
            raise serializers.ValidationError("section_access must be an object.")
        unknown = sorted(k for k in value if not is_valid_section(k))
        if unknown:
            raise serializers.ValidationError(f"Unknown section(s): {', '.join(unknown)}")
        for section, entry in value.items():
            capability = entry.get("capability") if isinstance(entry, dict) else None
            if not is_valid_capability(capability or ""):
                raise serializers.ValidationError(
                    f"{section}: capability must be one of {', '.join(CAPABILITY_ORDER)}."
                )
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
    # SIDEBAR RBAC contract (issue #85): the server, not the client, decides what
    # each person sees and may do. `sections` is the ordered, role-filtered
    # sidebar with a capability per section; `capabilities` is the flat
    # {section: capability} the client gates on; `business_units` is the units
    # the user may act in (fail-closed — empty ⇒ nothing).
    sections = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()
    business_units = serializers.SerializerMethodField()
    all_business_units = serializers.SerializerMethodField()

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
            "sections",
            "capabilities",
            "business_units",
            "all_business_units",
        ]

    def get_nav_groups(self, obj: User) -> list[str]:
        if obj.is_superuser:
            return list(NAV_GROUPS)
        return list(obj.role.nav_groups) if obj.role else []

    def get_landing_page(self, obj: User) -> str:
        return obj.role.landing_page if obj.role else "home"

    def _cached(self, obj: User, key: str, compute: Callable[[], _T]) -> _T:
        """Memoize a derived value per (field, object) so the shared scope and
        section walks run once per response — this serializer renders four
        SerializerMethodFields off the same two computations."""
        store = self.__dict__.setdefault("_derived", {})
        cache_key = (key, id(obj))
        if cache_key not in store:
            store[cache_key] = compute()
        result: _T = store[cache_key]
        return result

    def get_stores(self, obj: User) -> list[dict[str, Any]]:
        return self._cached(
            obj, "stores", lambda: StoreMiniSerializer(scoped_stores(obj), many=True).data
        )

    def get_sections(self, obj: User) -> list[dict[str, Any]]:
        return self._cached(obj, "sections", lambda: visible_sections(obj))

    def get_capabilities(self, obj: User) -> dict[str, str]:
        # Flat {section: capability} the client gates on — projected from the
        # already-computed sections list, not a second resolution pass.
        return {str(s["code"]): str(s["capability"]) for s in self.get_sections(obj)}

    def get_business_units(self, obj: User) -> list[dict[str, Any]]:
        # The units the user may act in are exactly their scoped stores. `all`-
        # scoped users act network-wide, so the concrete list is every store
        # (with `all_business_units` flagged so the switcher can offer an "All
        # units" option instead of 17 rows).
        return self.get_stores(obj)

    def get_all_business_units(self, obj: User) -> bool:
        return self._cached(obj, "all_units", lambda: visible_store_ids(obj) is None)


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
        scope = attrs.get("scope_type") or getattr(self.instance, "scope_type", "store")
        stores = attrs.get("stores")
        if scope == "store" and stores is not None and len(stores) == 0:
            raise serializers.ValidationError(
                {"store_ids": "A store-scoped user needs at least one store."}
            )
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
