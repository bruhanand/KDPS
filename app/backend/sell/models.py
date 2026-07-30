"""The Sale and everything a bill drags behind it (D10, the till's documents).

The sale is the busiest money document in the system and the only one whose
number is assigned by the *writer* rather than by the server: the till bills
offline, so the bill is printed and in the customer's hand before the server ever
hears about it. `Sale.mint_number()` is where that lands — it accepts the number
the till brought instead of allocating one, and the kernel
(`VoucherSeries.accept_external`) decides whether it may be used.

Two shapes here are worth reading before the rest:

* **A posted document is immutable, in the database, by trigger.** That is why
  the credit note stores its face value and nothing else: a balance that goes
  down cannot live on a posted document, so `remaining_paise` is derived from
  the redemption rows appended against it. The document is the fact; the
  redemptions are the ledger of what happened to it.
* **Flags are rows, not columns.** Everything the business can absorb — a hole in
  the numbering, an unrecognised credit note, a bill whose tax disagrees with
  today's slab — becomes a `ContinuityFlag` on the store's queue and the bill
  still lands (Rule 8, flag don't block).
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.utils import timezone

from core.base import TimeStampedModel
from core.documents import DocStatus, Document, MintedNumber, VoucherSeries
from core.fiscal import financial_year
from core.money import MoneyField

#: Doc types this app mints. `SAL` is till-assigned (see the kernel's
#: `EXTERNAL_NUMBER_DOC_TYPES`); `CRN` is an ordinary server-allocated counter.
SALE_DOC_TYPE = "SAL"
CREDIT_NOTE_DOC_TYPE = "CRN"


class SellPolicy(TimeStampedModel):
    """The shop floor's money dials, as data rather than as constants (Rule 12).

    One row, because both dials are one decision head office makes for the chain
    and neither varies by store today. It is read on every accept, so it is
    deliberately tiny.

    ``manual_discount_cap_percent`` is the B2 rule: a discount the rulebook did
    not produce is a *manual* discount, and beyond the cap the bill will not close
    without a manager's OK recorded on it. It ships at zero — no keyed-in discount
    at all without a manager — because that is the safe end of the dial for a
    number nobody has decided yet: the requirements register defers the exact
    limits and the per-role grid to D4, which left them thin. Head office widens
    it; nothing widens itself.

    ``credit_note_validity_days`` is how long a note issued here stays spendable.
    Six months is the Indian norm and the grill recorded it as data, not a rule.
    """

    SINGLETON_PK = 1

    manual_discount_cap_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Discount a cashier may key in without a manager, as a percent of MRP.",
    )
    credit_note_validity_days = models.IntegerField(
        default=180,
        help_text="How many days a credit note issued at the counter stays spendable.",
    )

    class Meta:
        db_table = "sell_policy"
        verbose_name_plural = "sell policies"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="ck_sellpolicy_singleton"),
            models.CheckConstraint(
                condition=models.Q(manual_discount_cap_percent__gte=0)
                & models.Q(manual_discount_cap_percent__lte=100),
                name="ck_sellpolicy_cap_is_a_percent",
            ),
            models.CheckConstraint(
                condition=models.Q(credit_note_validity_days__gt=0),
                name="ck_sellpolicy_validity_is_positive",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"cap {self.manual_discount_cap_percent}% · "
            f"credit notes valid {self.credit_note_validity_days}d"
        )

    @classmethod
    def current(cls) -> SellPolicy:
        """The live dials, creating the row at its defaults if it is somehow gone.

        Fail-safe rather than fail-closed on purpose: the defaults are the strict
        end (no manual discount), so a missing row cannot loosen anything.
        """
        row, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return row


class Salesman(TimeStampedModel):
    """A named seller at a store — the per-line credit on a bill.

    Not a system login: the person who sold the shirt is frequently not the
    person operating the till. When HRMS lands this becomes the staff master's
    till view, which is why it is shaped to gain an FK rather than to be replaced.
    """

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="salesmen")
    code = models.CharField(max_length=16)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sell_salesman"
        ordering = ["store__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["store", "code"], name="uq_salesman_store_code"),
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"


class CreditNote(Document):
    """What the counter hands back instead of cash (grill Q7).

    Face value only. `remaining_paise` and `status` are **derived**, not stored,
    and that is a consequence of the kernel rather than a preference: a submitted
    document may not be UPDATEd — the FSM trigger refuses every column change but
    the move to cancelled — so a balance that falls as the note is spent cannot
    live here. It lives where it actually happens, in the redemption rows, and
    the note reads its own balance off them. The same argument that makes ledgers
    append-only makes this the right shape anyway.

    Same-store redemption only in v1 (grill Q4): the note names its issuing store
    and the accept pipeline refuses one from anywhere else.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        SPENT = "spent", "Spent"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="credit_notes_issued"
    )
    fy = models.CharField(max_length=7)
    customer_name = models.CharField(max_length=120, blank=True, default="")
    customer_mobile = models.CharField(max_length=15, blank=True, default="")
    value_paise = MoneyField(help_text="Face value at issue, in integer paise. Never changes.")
    expires_on = models.DateField(
        help_text="Validity is data (grill Q7); set from SellPolicy at issue."
    )
    source_sale = models.ForeignKey(
        "sell.Sale",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credit_notes_issued",
        help_text="The bill that issued it — an exchange whose returns exceeded its sales.",
    )
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta(Document.Meta):
        db_table = "sell_credit_note"
        ordering = ["-created_at"]
        constraints = [
            *Document.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(value_paise__gt=0), name="ck_creditnote_value_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.doc_number or f"CreditNote(draft #{self.pk})"

    @property
    def doc_type(self) -> str:
        return CREDIT_NOTE_DOC_TYPE

    def series_lookup(self) -> tuple[str, str, str]:
        return self.fy, self.store.code, CREDIT_NOTE_DOC_TYPE

    @property
    def spent_paise(self) -> int:
        return int(self.redemptions.aggregate(total=models.Sum("amount_paise"))["total"] or 0)

    @property
    def remaining_paise(self) -> int:
        return int(self.value_paise or 0) - self.spent_paise

    @property
    def status(self) -> str:
        if self.docstatus == DocStatus.CANCELLED:
            return self.Status.CANCELLED
        if self.remaining_paise <= 0:
            return self.Status.SPENT
        if self.expires_on < timezone.localdate():
            return self.Status.EXPIRED
        return self.Status.OPEN


class Sale(Document):
    """One bill. The till assigns its number; the server accepts it exactly once.

    `(store, fy, till_seq)` is the till's key and is unique here as well as in the
    rendered `doc_number`, so a second writer on one series is refused by the
    database rather than by a check somebody could forget to run.
    """

    class Origin(models.TextChoices):
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"
        PAPER = "paper", "Re-entered from a paper bill"

    class B2bTaxKind(models.TextChoices):
        NONE = "none", "Not a B2B bill"
        CGST_SGST = "cgst_sgst", "CGST + SGST (same state)"
        IGST = "igst", "IGST (different state)"

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="sales")
    fy = models.CharField(max_length=7)
    till_seq = models.IntegerField(help_text="The number the till assigned, before syncing.")
    origin = models.CharField(max_length=8, choices=Origin.choices, default=Origin.OFFLINE)
    billed_at = models.DateTimeField(help_text="The till's clock at Save & Print.")
    customer_name = models.CharField(max_length=120, blank=True, default="")
    customer_mobile = models.CharField(max_length=15, blank=True, default="", db_index=True)
    buyer_gstin = models.CharField(
        max_length=15, blank=True, default="", help_text="Present = a B2B tax invoice."
    )
    b2b_tax_kind = models.CharField(
        max_length=10, choices=B2bTaxKind.choices, default=B2bTaxKind.NONE
    )
    gross_paise = MoneyField(default=0)
    discount_paise = MoneyField(default=0)
    net_paise = MoneyField(
        default=0,
        help_text="What the customer pays. May be negative — an exchange whose "
        "returns outweigh its sales issues a credit note for the difference.",
    )
    gst_paise = MoneyField(default=0)
    round_paise = MoneyField(default=0)
    exchange_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="exchanges"
    )
    salesman_default = models.ForeignKey(
        Salesman, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="sales_billed"
    )

    class Meta(Document.Meta):
        db_table = "sell_sale"
        ordering = ["-billed_at", "-id"]
        constraints = [
            *Document.Meta.constraints,
            models.UniqueConstraint(
                fields=["store", "fy", "till_seq"], name="uq_sale_store_fy_seq"
            ),
            models.CheckConstraint(
                condition=models.Q(till_seq__gt=0), name="ck_sale_till_seq_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["store", "billed_at"], name="sale_store_billed_idx"),
            models.Index(fields=["store", "origin"], name="sale_store_origin_idx"),
        ]

    def __str__(self) -> str:
        return self.doc_number or f"Sale(draft #{self.pk})"

    @property
    def doc_type(self) -> str:
        return SALE_DOC_TYPE

    def series_lookup(self) -> tuple[str, str, str]:
        return self.fy, self.store.code, SALE_DOC_TYPE

    def mint_number(self) -> MintedNumber:
        """Take the number the till already printed, rather than allocating one.

        The kernel decides whether it may be used and reports what it jumped over;
        the accept pipeline reads that off `post()` and raises the hole flag.
        """
        fy, store_code, doc_type = self.series_lookup()
        accepted = VoucherSeries.accept_external(
            fy=fy, store_code=store_code, doc_type=doc_type, seq=self.till_seq
        )
        return MintedNumber(
            series=accepted.series, doc_number=accepted.doc_number, accepted=accepted
        )


class SaleLine(TimeStampedModel):
    """One line of a bill, with the piece described as it was at billing (Rule 3).

    `direction` carries the sign — `qty` is always positive. A `return` line is
    the exchange leg: a piece coming back inside the same bill, priced at what the
    customer actually paid for it on the original (D2), never at today's price.
    """

    class Direction(models.TextChoices):
        SALE = "sale", "Sold"
        RETURN = "return", "Returned (exchange leg)"

    class Condition(models.TextChoices):
        GOOD = "good", "Good — back on the shelf"
        DAMAGED = "damaged", "Damaged — into quarantine"

    class CostingStatus(models.TextChoices):
        POSTED = "posted", "Costed"
        DEFERRED = "deferred", "Waiting on the paperwork"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    line_no = models.IntegerField()
    direction = models.CharField(max_length=8, choices=Direction.choices, default=Direction.SALE)
    barcode = models.CharField(max_length=64, db_index=True)
    season = models.CharField(max_length=120, blank=True, default="")
    # The seven merchandising dims, snapshotted at billing.
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()
    mrp_paise = MoneyField(default=0)
    disc_paise = MoneyField(default=0)
    net_paise = MoneyField(
        default=0, help_text="GST-inclusive line value; on a return leg, the refund."
    )
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_paise = MoneyField(default=0)
    unit_cost_paise = MoneyField(
        default=0,
        help_text="Cost of record from the cohort, frozen at billing. Zero only on a "
        "line the books cannot price yet (sold before inward).",
    )
    salesman = models.ForeignKey(
        Salesman, null=True, blank=True, on_delete=models.PROTECT, related_name="lines"
    )
    offer_evidence = models.JSONField(
        default=dict,
        blank=True,
        help_text="Which rule won, what it beat, and by how much (B3). The FK onto "
        "offers.Offer arrives with the offer engine; until then the winner's id "
        "rides inside this evidence.",
    )
    manual_desc = models.CharField(
        max_length=200, blank=True, default="", help_text="A line the scan could not resolve."
    )
    sold_before_inward = models.BooleanField(default=False)
    costing_status = models.CharField(
        max_length=8, choices=CostingStatus.choices, default=CostingStatus.POSTED
    )
    return_reason = models.CharField(max_length=40, blank=True, default="")
    condition = models.CharField(max_length=8, choices=Condition.choices, blank=True, default="")
    original_line = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="returned_by",
        help_text="The line on the original bill this exchange leg gives back.",
    )
    override_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sale_lines_overridden",
        help_text="The manager whose OK let this line's discount past the cap (H3).",
    )

    class Meta:
        db_table = "sell_sale_line"
        ordering = ["sale_id", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["sale", "line_no"], name="uq_saleline_sale_line_no"),
            models.CheckConstraint(condition=models.Q(qty__gt=0), name="ck_saleline_qty_positive"),
            # A sold piece always has a name against it (Rule 10); a returned one
            # is credited to whoever sold it originally, not to whoever took it back.
            models.CheckConstraint(
                condition=~models.Q(direction="sale") | models.Q(salesman__isnull=False),
                name="ck_saleline_sale_has_salesman",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sale_id}/{self.line_no} · {self.barcode} × {self.qty}"


class SaleTender(TimeStampedModel):
    """How the bill was paid. The rows sum to `Sale.net_paise` (checked at accept)."""

    class Mode(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        UPI = "upi", "UPI"
        CREDIT_NOTE = "credit_note", "Credit note"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="tenders")
    mode = models.CharField(max_length=12, choices=Mode.choices)
    amount_paise = MoneyField()
    credit_note = models.ForeignKey(
        CreditNote,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="tenders",
        help_text="Set when the note was recognised. A note the till could not verify "
        "is taken on a manager's OK and flagged, so this stays empty there.",
    )

    class Meta:
        db_table = "sell_sale_tender"
        ordering = ["sale_id", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_paise__gt=0), name="ck_saletender_amount_positive"
            ),
            # One direction only: a note may only be named by a credit-note tender.
            # The reverse does not hold — an unverified note is accepted on a
            # manager's OK and has no row to point at.
            models.CheckConstraint(
                condition=models.Q(credit_note__isnull=True) | models.Q(mode="credit_note"),
                name="ck_saletender_note_only_on_note_mode",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_mode_display()} {self.amount_paise}"


class CreditNoteRedemption(TimeStampedModel):
    """One spend against a credit note. The note's balance is the sum of these."""

    credit_note = models.ForeignKey(
        CreditNote, on_delete=models.PROTECT, related_name="redemptions"
    )
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="credit_note_spends")
    amount_paise = MoneyField()

    class Meta:
        db_table = "sell_credit_note_redemption"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["credit_note", "sale"], name="uq_redemption_note_sale"),
            models.CheckConstraint(
                condition=models.Q(amount_paise__gt=0), name="ck_redemption_amount_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.credit_note_id} −{self.amount_paise}"


class ContinuityFlag(TimeStampedModel):
    """Something a human should look at, on a bill that was taken anyway.

    The sell face of the exception-queue pattern (`TransferReceiptException`,
    `ReviewItem`). Rule 8 in one table: the counter is never the place a problem
    is argued out, so everything the business can absorb lands here and shows on
    the store's action queue instead of refusing the customer.
    """

    class Kind(models.TextChoices):
        NUMBER_HOLE = "number_hole", "Bills missing before this one"
        CN_UNVERIFIED = "cn_unverified", "Credit note taken without verification"
        RETURN_ORIG_MISSING = "return_orig_missing", "Returned against a bill we do not hold"
        OFFER_MISMATCH = "offer_mismatch", "Offer applied differs from the rulebook"
        GST_MISMATCH = "gst_mismatch", "Tax charged differs from the dated slab"
        AGED_UNCOSTED = "aged_uncosted", "Sold before inward, still unpriced"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        IGNORED = "ignored", "Ignored"

    kind = models.CharField(max_length=24, choices=Kind.choices)
    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="continuity_flags"
    )
    sale = models.ForeignKey(
        Sale, null=True, blank=True, on_delete=models.SET_NULL, related_name="flags"
    )
    details = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    resolved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sell_continuity_flag"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "status"], name="continuityflag_store_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} · {self.store_id}"


class DeferredCosting(TimeStampedModel):
    """A sold line the books cannot price yet (grill Q5, sold-before-inward).

    Rule 5 says no posting at zero value and Rule 8 says no blocked sale; both
    hold because the line waits here instead. When the GRN/PT prices its cohort,
    the sweep posts the cost event and the stock leg against the original bill.
    """

    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting on inward"
        POSTED = "posted", "Posted"

    sale_line = models.OneToOneField(
        SaleLine, on_delete=models.CASCADE, related_name="deferred_costing"
    )
    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="deferred_costings"
    )
    barcode = models.CharField(max_length=64, db_index=True)
    season = models.CharField(max_length=120, blank=True, default="")
    qty = models.IntegerField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.WAITING)
    posted_doc_number = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "sell_deferred_costing"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.barcode} × {self.qty} ({self.status})"


class IrnQueueItem(TimeStampedModel):
    """A B2B bill waiting for head office to raise its IRN (grill Q8).

    Above the e-invoice threshold every GSTIN-bearing counter sale must receive an
    IRN within 30 days or it is invalid and the customer loses input credit. The
    deadline is data (Rule 11) and it is head office's duty, not the store's.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        GENERATED = "generated", "Generated"
        FAILED = "failed", "Failed"

    sale = models.OneToOneField(Sale, on_delete=models.CASCADE, related_name="irn_queue_item")
    due_on = models.DateField(help_text="billed_at + 30 days.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    irn = models.CharField(max_length=64, blank=True, default="")
    handled_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sell_irn_queue"
        ordering = ["due_on", "id"]

    def __str__(self) -> str:
        return f"IRN due {self.due_on} · {self.sale_id}"


def sale_financial_year(when: Any) -> str:
    """The Indian FY a bill belongs to, from its billing moment."""
    moment = when or timezone.now()
    return financial_year(moment.date() if hasattr(moment, "date") else moment)
