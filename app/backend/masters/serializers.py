from __future__ import annotations

from rest_framework import serializers

from masters.models import Brand, Gstin, LegalEntity, Season, Store


class LegalEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalEntity
        fields = ["id", "code", "name", "pan", "is_active"]


class GstinSerializer(serializers.ModelSerializer):
    legal_entity_name = serializers.CharField(source="legal_entity.name", read_only=True)

    class Meta:
        model = Gstin
        fields = [
            "id",
            "gstin",
            "state_code",
            "state_name",
            "legal_entity",
            "legal_entity_name",
            "is_active",
        ]


class StoreSerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source="gstin.state_name", read_only=True)
    state_code = serializers.CharField(source="gstin.state_code", read_only=True)
    gstin_number = serializers.CharField(source="gstin.gstin", read_only=True)

    class Meta:
        model = Store
        fields = [
            "id",
            "code",
            "name",
            "store_type",
            "city",
            "gstin",
            "gstin_number",
            "state_name",
            "state_code",
            "is_active",
        ]


class LocationSerializer(serializers.ModelSerializer):
    """A place in the network, as a picker needs to name it (#147).

    Deliberately thinner than `StoreSerializer`: identity, and the registration
    a transfer's tax treatment turns on. Nothing costed, nothing a caller's
    scope exists to keep from them.

    `gstin` is the registration's row id, not the number — enough to ask "is
    this the same distinct person?", which is exactly the question
    `StoreTransfer.save()` asks when it sets `is_cross_state`. The state travels
    alongside it because that is what the screen *says* out loud ("Bihar ↔
    Jharkhand"); the two must not be allowed to drift apart.
    """

    state_name = serializers.CharField(source="gstin.state_name", read_only=True)
    state_code = serializers.CharField(source="gstin.state_code", read_only=True)

    class Meta:
        model = Store
        fields = ["id", "code", "name", "store_type", "gstin", "state_code", "state_name"]


class SeasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Season
        fields = ["id", "code", "name", "status", "sort_order"]


class BrandSerializer(serializers.ModelSerializer):
    commercial_label = serializers.CharField(read_only=True)
    #: Derived, so the return screen never re-implements the two-axis rules.
    takes_returns = serializers.BooleanField(read_only=True)
    cap_applies = serializers.BooleanField(read_only=True)

    class Meta:
        model = Brand
        fields = [
            "id",
            "code",
            "name",
            "ownership",
            "return_terms",
            "commercial_label",
            "return_window_days",
            "return_cap_percent",
            "takes_returns",
            "cap_applies",
            "is_active",
        ]
