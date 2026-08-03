"""Master-data spine (D8) — the load-bearing registries every later slice copies
from. Foundation scope: the `LegalEntity → GSTIN → Store` hierarchy (ADR-0007),
the season calendar, the brand register with its two-axis commercial model, and
the date-effective apparel GST slab.

These are mutable masters (SCD-2 versioning arrives with the money slices); they
extend `core.base.TimeStampedModel`, not the append-only ledger base.
"""

from __future__ import annotations

from django.db import models

from core.base import TimeStampedModel
from core.money import MoneyField


class LegalEntity(TimeStampedModel):
    """The legal company. KDPS is one PAN / one legal entity / one Tally company,
    fronting two GSTINs (Bihar + Jharkhand)."""

    code = models.SlugField(max_length=24, unique=True)
    name = models.CharField(max_length=160)
    pan = models.CharField(max_length=10, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "legal entities"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Gstin(TimeStampedModel):
    """A state tax identity. Two GSTINs = two 'distinct persons'; the first two
    digits are the state code that drives intra- vs cross-state (IGST) treatment."""

    legal_entity = models.ForeignKey(LegalEntity, on_delete=models.PROTECT, related_name="gstins")
    gstin = models.CharField(max_length=15, unique=True)
    state_code = models.CharField(max_length=2)  # e.g. "10" Bihar, "20" Jharkhand
    state_name = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "GSTIN"
        ordering = ["state_name"]

    def __str__(self) -> str:
        return f"{self.gstin} ({self.state_name})"


class Store(TimeStampedModel):
    """A store or warehouse. Maps to exactly one state GSTIN, so its state is the
    tax context for every document raised there."""

    class StoreType(models.TextChoices):
        STORE = "store", "Store"
        WAREHOUSE = "warehouse", "Warehouse"

    code = models.SlugField(max_length=16, unique=True)  # e.g. "DEO"
    name = models.CharField(max_length=120)
    store_type = models.CharField(max_length=12, choices=StoreType.choices, default=StoreType.STORE)
    gstin = models.ForeignKey(Gstin, on_delete=models.PROTECT, related_name="stores")
    city = models.CharField(max_length=80, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"


class StoreTarget(TimeStampedModel):
    """The rupee number a store is asked to sell in one month (#171, D10).

    Set at HO by the Operations Head and read by the store Dashboard's manager
    row (month-to-date vs target). A master, not a document: nothing posts and
    nothing balances, so setting it again *corrects* it rather than appending a
    second answer - which is what the unique key below makes true, and why the
    endpoint is a PUT.

    `month` is the month itself, stored as its first day. The CHECK is what keeps
    that honest: without it two callers sending the 15th and the 20th of August
    would create two rows that both mean August, and the Dashboard would have to
    pick one.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="targets")
    month = models.DateField(help_text="The month, as its first day (2026-08-01 = August 2026).")
    target_paise = MoneyField(
        help_text="Net sales asked of this store for the month, in integer paise. "
        "Nought is a real answer - a store shut for the month is not an unset target."
    )
    set_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="store_targets_set",
        help_text="Who last set this number. The only route from a Dashboard figure "
        "back to the person who chose it.",
    )

    class Meta:
        ordering = ["store__code", "month"]
        constraints = [
            models.UniqueConstraint(fields=["store", "month"], name="uq_storetarget_store_month"),
            models.CheckConstraint(
                condition=models.Q(month__day=1),
                name="ck_storetarget_month_is_first_of_month",
            ),
            models.CheckConstraint(
                condition=models.Q(target_paise__gte=0),
                name="ck_storetarget_target_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.store.code} · {self.month:%b %Y}"


class Season(TimeStampedModel):
    """The selling period — a name, never a date (Open → EOSS → Closed)."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        EOSS = "eoss", "EOSS"
        CLOSED = "closed", "Closed"

    code = models.SlugField(max_length=24, unique=True)  # e.g. "SS26"
    name = models.CharField(max_length=80)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["-sort_order", "code"]

    def __str__(self) -> str:
        return self.name


class Brand(TimeStampedModel):
    """A brand and its commercial model, stored as two axes (ownership ×
    return-terms) with a derived friendly label — a first-class dimension, not a
    flag (ADR / Rule 12)."""

    class Ownership(models.TextChoices):
        OWNED = "owned", "KDPS-owned"
        BRAND_OWNED = "brand_owned", "Brand-owned"

    class ReturnTerms(models.TextChoices):
        NONE = "none", "No returns"
        CAPPED = "capped", "Capped allowance"
        UNCAPPED = "uncapped", "Uncapped"
        ROLLING = "rolling", "Uncapped + rolling top-up"

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    ownership = models.CharField(max_length=12, choices=Ownership.choices, default=Ownership.OWNED)
    return_terms = models.CharField(
        max_length=12, choices=ReturnTerms.choices, default=ReturnTerms.NONE
    )
    return_window_days = models.IntegerField(
        default=0,
        help_text="How long after a piece arrives the brand will still take it back "
        "(60–120 days, negotiated per brand). 0 means nobody has agreed one yet — "
        "the return screen says so rather than guessing a deadline.",
    )
    return_cap_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="The Correction goods-return allowance, as a percentage of the "
        "brand's delivered value (the 10 of 25-18-10, stretchable to 12/15). Read "
        "only for Correction brands — the other three models have no cap.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def commercial_label(self) -> str:
        """The derived friendly label from the two axes."""
        o, r = self.ownership, self.return_terms
        if o == self.Ownership.OWNED:
            return "Correction" if r == self.ReturnTerms.CAPPED else "Outright"
        return "Consignment" if r == self.ReturnTerms.ROLLING else "SOR"

    @property
    def takes_returns(self) -> bool:
        """Will this brand take stock back at all?

        Three of the four commercial models will: SOR and Consignment because the
        goods were never ours, Correction because a capped allowance was
        negotiated. Outright bought the stock outright, so nothing goes back and
        its pieces never reach the returnable pool (#75).
        """
        return self.commercial_label != "Outright"

    @property
    def cap_applies(self) -> bool:
        """Is this brand's return room a finite, negotiated number?

        Only Correction's is. SOR and Consignment return everything unsold with
        no cap, so showing them a percentage of anything would be an invention.
        """
        return self.commercial_label == "Correction"


class GstSlab(TimeStampedModel):
    """Date-effective apparel GST slab (GST 2.0): a per-piece threshold splits a
    low rate from a high rate. Held as data (Rule 12) — re-verify before go-live."""

    name = models.CharField(max_length=80, default="Apparel")
    hsn_prefix = models.CharField(max_length=8, blank=True, default="")
    threshold_paise = MoneyField(default=250000)  # ₹2,500 / piece
    rate_below = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    rate_above = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    effective_from = models.DateField()

    class Meta:
        ordering = ["-effective_from"]
        # No `updated_at` index here, unlike `Sku` and `Cohort`, and `db-design.md`
        # asked for one: the till's dataset sends every slab whole on every response
        # rather than deltaing a table with a handful of rows in it, so nothing
        # filters this column. An index nobody queries is a false statement about how
        # a table is read.

    def __str__(self) -> str:
        return f"{self.name} (from {self.effective_from})"


class CategoryMargin(TimeStampedModel):
    """Default retail margin per merchandising ITEM (Master-Sheet item value), with
    the allowed operator band — the data behind deterministic non-brand pricing
    (D2 Q7, Rule 12: variation is data, not code). ``item=""`` is the global
    fallback row. Seeded at 33% (band 30–35) — per-category numbers are still
    awaited from KDPS; a steward edits rows, never code."""

    item = models.CharField(max_length=160, unique=True, blank=True, default="")
    margin_pct = models.DecimalField(max_digits=5, decimal_places=2, default=33)
    band_min_pct = models.DecimalField(max_digits=5, decimal_places=2, default=30)
    band_max_pct = models.DecimalField(max_digits=5, decimal_places=2, default=35)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["item"]

    def __str__(self) -> str:
        return f"{self.item or 'DEFAULT'} @ {self.margin_pct}%"


class Sku(TimeStampedModel):
    """Canonical product identity — the barcode IS the SKU (D-grain). Registered /
    refreshed whenever a PT posts; the queryable home of the unit's MRP and its
    merchandising dimensions, so downstream slices stop re-deriving identity from
    free-text ledger rows."""

    barcode = models.CharField(max_length=64, unique=True, db_index=True)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    mrp_paise = MoneyField(null=True, blank=True)
    no_discount = models.BooleanField(
        default=False,
        help_text="The AMM/NOD flag: this piece is never discounted, by any offer "
        "or by any cashier. Rides down to the till in its dataset (B4, D5 Q3).",
    )
    first_doc_number = models.CharField(max_length=128, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["barcode"]
        indexes = [
            models.Index(fields=["brand"], name="masters_sku_brand_idx"),
            models.Index(fields=["design"], name="masters_sku_design_idx"),
            # The till's dataset asks each synced master "what changed since this
            # timestamp" (#179), and `updated_at` is already the honest answer -
            # `TimeStampedModel` has been stamping it since these tables existed.
            # So the watermark the db-design calls a new column is a new *index*
            # on an old one, and there is deliberately no backfill: the values in
            # there are real edit times, and setting them all to migration time
            # would throw away the only history a delta can read.
            models.Index(fields=["updated_at"], name="masters_sku_synced_idx"),
        ]

    def __str__(self) -> str:
        return self.barcode


class Cohort(TimeStampedModel):
    """A buying cohort = (barcode, season): the same SKU can be bought across
    seasons at different locked unit costs. Holds the per-unit `unit_cost_paise`
    (the PT P RATE), DB-guarded `unit_cost ≤ mrp` so a cost can never exceed the
    ticketed price even via a raw write."""

    sku = models.ForeignKey(Sku, on_delete=models.CASCADE, related_name="cohorts")
    barcode = models.CharField(max_length=64, db_index=True)
    season = models.CharField(max_length=120)
    unit_cost_paise = MoneyField()
    mrp_paise = MoneyField(null=True, blank=True)
    last_doc_number = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        ordering = ["barcode", "season"]
        constraints = [
            models.UniqueConstraint(fields=["barcode", "season"], name="uq_cohort_barcode_season"),
            models.CheckConstraint(
                condition=models.Q(mrp_paise__isnull=True)
                | models.Q(unit_cost_paise__lte=models.F("mrp_paise")),
                name="ck_cohort_unit_cost_le_mrp",
            ),
        ]
        indexes = [
            models.Index(fields=["season"], name="masters_cohort_season_idx"),
            # The till's dataset watermark (#179) - see `Sku.Meta`.
            models.Index(fields=["updated_at"], name="masters_cohort_synced_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.barcode}@{self.season}"


class PriceChange(TimeStampedModel):
    """Every movement of a ticket, kept for ever (D11 §4).

    The ticket itself lives on ``Sku`` and ``Cohort``, one number each, because
    that is what the till reads. This is the *history* beside it, and it exists
    for the questions a column cannot answer: what was this piece priced at on the
    day that bill was made, who moved it, and why. Append-only — a correction is
    another row, never an edit, for the same reason no posted document in this
    system is editable.

    ``effective_from`` rather than only a timestamp, because a re-ticket is a
    business date: head office decides a piece sells at ₹2,999 *from Monday*, and
    a bill printed on Sunday has to keep reading Sunday's ticket.
    """

    class Source(models.TextChoices):
        PT = "pt", "PT posting"
        REPRICE = "reprice", "Re-ticket"

    barcode = models.CharField(max_length=64, db_index=True)
    sku = models.ForeignKey(
        Sku, null=True, blank=True, on_delete=models.SET_NULL, related_name="price_changes"
    )
    #: Null on the first row a barcode ever gets — there was no ticket before it.
    from_paise = MoneyField(null=True, blank=True)
    to_paise = MoneyField()
    effective_from = models.DateField()
    source = models.CharField(max_length=12, choices=Source.choices)
    #: The document that moved it, where one did (a PT's inward voucher number).
    doc_number = models.CharField(max_length=32, blank=True, default="")
    reason = models.CharField(max_length=200, blank=True, default="")
    changed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-effective_from", "-id"]
        indexes = [
            models.Index(fields=["barcode", "effective_from"], name="masters_price_day_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.barcode}: {self.from_paise or 0} → {self.to_paise}"


class Customer(TimeStampedModel):
    """One row per mobile number - the counter's first customer master (#242).

    Written only by the sale-accept step (Rule 4: one owner; no admin form, no
    API write, no seed command in v1), so provenance is derivable from the
    bills carrying that mobile rather than an actor column (Rule 10). A bill
    still snapshots its own `customer_name`/`customer_mobile` as text (Rule 3)
    - a later edit here never rewrites yesterday's bill.

    Deliberately not store-scoped: a Deoghar regular must be recognised in
    Ranchi too. No delete path - a changed number is a new row (v1 ruling),
    not an edit to this one.
    """

    mobile = models.CharField(
        max_length=15, unique=True, help_text="Digits only, normalised at the accept boundary."
    )
    name = models.CharField(max_length=120, blank=True, default="")
    gstin = models.CharField(
        max_length=15, blank=True, default="", help_text="Normalised uppercase."
    )

    class Meta:
        ordering = ["mobile"]
        indexes = [
            # The till's dataset watermark (#245) - see `Sku.Meta`.
            models.Index(fields=["updated_at"], name="masters_customer_synced_idx"),
        ]

    def __str__(self) -> str:
        return self.name or self.mobile
