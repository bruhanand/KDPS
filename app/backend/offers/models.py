"""The rulebook (D5). One row per offer, in one open shape.

D5 Q1 rejected eight separate forms for eight patterns, and it rejected a
free-form rule script too. What is left is the middle: **trigger + reward +
dials**, where a new pattern is a new combination of values rather than a new
table and a release. That is Rule 12 applied to the thing that changes fastest
in this business - a brand can invent a mechanic in a WhatsApp message on a
Tuesday, and the counter has to price it on the Wednesday.

The consequence is that most of an offer lives in four JSON columns. They are not
a shrug: `offers/resolution.py` is the schema, written as an engine and pinned by
twelve golden carts, and the serializer below refuses a shape the engine could
not read. What the columns buy is that adding "buy 2 get 2" needed no migration.

Two rules about the row itself, both money-critical:

* **A live rule is never edited in place.** The till has already cached it, and a
  bill printed under yesterday's wording must stay explicable. Changing a running
  offer means ending it and starting another (`end_and_replace` below), which is
  the same documents-snapshot discipline every posted document in this system
  obeys.
* **A new store is never auto-enrolled** (D5 Q4). `store_scope` therefore holds a
  *list of stores*, resolved when the offer is written, even when the author
  chose "all". A wildcard evaluated at billing time would quietly opt a shop that
  opened last week into a promotion nobody costed it into.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.db import models

from core.base import TimeStampedModel


class OfferQuerySet(models.QuerySet["Offer"]):
    def live_on(self, day: date) -> OfferQuerySet:
        """Rules a counter should be pricing with on `day`.

        `status` and the dates are two different questions and both are asked:
        an approved rule whose start date has not arrived is not running, and a
        live rule whose end date has passed is not running either, whoever last
        touched the row.
        """
        return self.filter(
            status=Offer.Status.LIVE,
            starts_on__lte=day,
        ).filter(models.Q(ends_on__isnull=True) | models.Q(ends_on__gte=day))

    def for_store(self, store_code: str) -> OfferQuerySet:
        return self.filter(store_scope__stores__contains=[store_code.upper()])


class Offer(TimeStampedModel):
    """One rule: what must happen, what the customer gets, and where it applies."""

    class Layer(models.TextChoices):
        BRAND = "brand", "Brand offer"
        STOREWIDE = "storewide", "Storewide add-on"
        BANK = "bank", "Bank / tender add-on"

    class Funder(models.TextChoices):
        BRAND = "brand", "Funded by the brand"
        KDPS = "kdps", "Funded by KDPS"

    class Trigger(models.TextChoices):
        NONE = "none", "No condition"
        SPEND = "spend", "Spend threshold"
        QTY = "qty", "Quantity threshold"
        GROUP = "group", "Buy X get Y"

    class Reward(models.TextChoices):
        PCT_OFF = "pct_off", "Percent off"
        AMT_OFF = "amt_off", "Amount off"
        ITEM_FREE = "item_free", "Item free"
        FIXED_PRICE = "fixed_price", "Fixed price"
        GIFT = "gift", "Gift"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        LIVE = "live", "Live"
        ENDED = "ended", "Ended"

    name = models.CharField(max_length=160)
    brand = models.ForeignKey(
        "masters.Brand",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="offers",
        help_text="Empty means the rule is not one brand's - a storewide or KDPS offer.",
    )
    funder = models.CharField(max_length=8, choices=Funder.choices, default=Funder.BRAND)
    layer = models.CharField(max_length=12, choices=Layer.choices, default=Layer.BRAND)

    trigger_type = models.CharField(max_length=8, choices=Trigger.choices, default=Trigger.NONE)
    trigger_config = models.JSONField(default=dict, blank=True)
    reward_type = models.CharField(max_length=12, choices=Reward.choices)
    reward_config = models.JSONField(default=dict, blank=True)
    item_scope = models.JSONField(default=dict, blank=True)
    store_scope = models.JSONField(
        default=dict,
        blank=True,
        help_text="{'kind': 'all'|'specific', 'stores': ['DEO', ...]} - always a list, "
        "resolved when the offer was written, so a new store is never auto-enrolled.",
    )

    starts_on = models.DateField()
    ends_on = models.DateField(
        null=True, blank=True, help_text="Empty means it rolls until somebody stops it (D5 Q5)."
    )
    combinable = models.BooleanField(
        default=False,
        help_text="Stacking is opt-in, per offer. Every new offer defaults to non-combining.",
    )
    priority = models.IntegerField(
        default=100, help_text="Lower wins a tie on rupees. Then the id does."
    )
    is_fallback = models.BooleanField(
        default=False, help_text="The named default that fills a gap in a brand's timeline (D5 Q5)."
    )

    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offers_approved",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offers_authored",
    )
    #: What this rule replaced, when it was written to end-and-replace a live one.
    replaces = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replaced_by"
    )

    objects: models.Manager[Offer] = OfferQuerySet.as_manager()

    class Meta:
        ordering = ["priority", "id"]
        indexes = [
            models.Index(fields=["layer", "starts_on", "ends_on"], name="offers_window_idx"),
            models.Index(fields=["brand"], name="offers_brand_idx"),
            # The dataset delta reads this and nothing else on the busy path.
            models.Index(fields=["updated_at"], name="offers_synced_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__isnull=True)
                | models.Q(ends_on__gte=models.F("starts_on")),
                name="offer_ends_after_it_starts",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="live") | models.Q(approved_by__isnull=False),
                name="offer_live_only_after_approval",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - admin/debug convenience
        return f"{self.name} ({self.get_layer_display()})"

    @property
    def brand_name(self) -> str:
        return self.brand.name if self.brand is not None else ""

    def is_live_on(self, day: date) -> bool:
        if self.status != Offer.Status.LIVE or day < self.starts_on:
            return False
        return self.ends_on is None or day <= self.ends_on

    def as_rule_payload(self) -> dict[str, Any]:
        """The rule as it rides to the till, and as the server re-reads it.

        Exactly the fields `offers.resolution.Rule` needs and not one more. The
        till is a shop-floor device: it gets the rulebook, never the margin
        behind it, which is why `funder` is absent here and present on the
        authoring screen.
        """
        return {
            "id": self.id,
            "name": self.name,
            "layer": self.layer,
            "brand": self.brand_name,
            "trigger_type": self.trigger_type,
            "trigger_config": self.trigger_config or {},
            "reward_type": self.reward_type,
            "reward_config": self.reward_config or {},
            "item_scope": self.item_scope or {},
            "starts_on": self.starts_on.isoformat(),
            "ends_on": self.ends_on.isoformat() if self.ends_on else None,
            "combinable": self.combinable,
            "priority": self.priority,
        }
