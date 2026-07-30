from __future__ import annotations

from datetime import date

from rest_framework import serializers

from masters.models import Brand, Gstin, LegalEntity, Season, Store, StoreTarget


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


class StoreTargetSerializer(serializers.ModelSerializer):
    """One cell of the target grid: which store, which month, how many paise.

    `store` is the store *code* both ways round - the code is what HO says out
    loud ("Deoghar's August") and what the Dashboard already holds, so making the
    screen carry a row id it would only ever translate back adds a lookup and a
    way to be wrong.
    """

    store = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = StoreTarget
        fields = ["store", "month", "target_paise"]


class StoreTargetWriteSerializer(serializers.Serializer):
    """What a PUT is allowed to say. Deliberately not a `ModelSerializer`:

    * `store` is validated as a *name* here and resolved against the caller's
      scope in the view, because "no such store" (404) and "not your store" (403)
      are different answers and a `SlugRelatedField` gives one for both;
    * `month` is a month, so a mid-month date is refused rather than truncated -
      the same rule the table's CHECK holds, stated here so the caller gets a
      sentence instead of a database error;
    * `target_paise` is integer paise (ADR-0004). A rupee decimal reaching this
      field means the conversion was skipped upstream, and rounding it here would
      hide that.
    """

    store = serializers.CharField(max_length=16)
    month = serializers.DateField()
    target_paise = serializers.IntegerField(min_value=0)

    def validate_month(self, value: date) -> date:
        if value.day != 1:
            raise serializers.ValidationError(
                "A target belongs to a month, so give the month's first day "
                f"({value:%Y-%m}-01), not {value.isoformat()}."
            )
        return value


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
