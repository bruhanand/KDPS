"""The Sale and everything a bill drags behind it (D10, the till's documents).

The sale is the busiest money document in the system and the only one whose
number is assigned by the *writer* rather than by the server: the till bills
offline, so the bill is printed and in the customer's hand before the server ever
hears about it. `Sale.mint_number()` is where that lands - it accepts the number
the till brought instead of allocating one, and the kernel
(`VoucherSeries.accept_external`) decides whether it may be used.

Two shapes here are worth reading before the rest:

* **A posted document is immutable, in the database, by trigger.** That is why
  the credit note stores its face value and nothing else: a balance that goes
  down cannot live on a posted document, so `remaining_paise` is derived from
  the redemption rows appended against it. The document is the fact; the
  redemptions are the ledger of what happened to it.
* **Flags are rows, not columns.** Everything the business can absorb - a hole in
  the numbering, an unrecognised credit note, a bill whose tax disagrees with
  today's slab - becomes a `ContinuityFlag` on the store's queue and the bill
  still lands (Rule 8, flag don't block).
"""

from __future__ import annotations

from datetime import date

from django.db import models
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.base import TimeStampedModel
from core.documents import DocStatus, Document, MintedNumber, VoucherSeries
from core.money import MoneyField
from masters.models import Gstin

#: Doc types this app mints. `SAL` is till-assigned (see the kernel's
#: `EXTERNAL_NUMBER_DOC_TYPES`); `CRN` and `SRT` are ordinary server-allocated
#: counters - a plain return needs the network by design (grill Q7), so there is
#: nothing offline about its number.
SALE_DOC_TYPE = "SAL"
CREDIT_NOTE_DOC_TYPE = "CRN"
RETURN_DOC_TYPE = "SRT"


class SellPolicy(TimeStampedModel):
    """The shop floor's money dials, as data rather than as constants (Rule 12).

    One row, because each dial is one decision head office makes for the chain and
    none of them varies by store today. It is read on every accept, so it is
    deliberately tiny.

    ``manual_discount_cap_percent`` is the B2 rule: a discount the rulebook did
    not produce is a *manual* discount, and beyond the cap the bill will not close
    without a manager's OK recorded on it. It ships at zero - no keyed-in discount
    at all without a manager - because that is the safe end of the dial for a
    number nobody has decided yet: the requirements register defers the exact
    limits and the per-role grid to D4, which left them thin. Head office widens
    it; nothing widens itself.

    ``credit_note_validity_days`` is how long a note issued here stays spendable.
    Six months is the Indian norm and the grill recorded it as data, not a rule.

    ``uncosted_aging_days`` is how long a line sold before its paperwork may sit in
    the costing queue before somebody is told about it (#186). The queue drains
    itself when the PT lands, so the dial is not a deadline - it is the point past
    which "the paperwork is on its way" stops being a fair description. Three days
    is a starting number, not a ruling: nothing in the corpus fixes one, and it is
    a dial precisely so head office can move it without a deploy (Rule 12).

    ``return_window_days`` is how long after a bill a piece may be brought back
    without a manager saying so explicitly (#184). Grill Q7 puts the window in
    data rather than in code, and past it the return is not refused - it takes the
    manager's *second* answer, the window override, and lands flagged. Thirty days
    is a starting number for the same reason the one above is: nothing in the
    corpus fixes a customer-facing window (the 60-120 days in the domain facts are
    the *brand's* return terms, which are a different clock entirely), and head
    office moves this one without a release.
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
    uncosted_aging_days = models.IntegerField(
        default=3,
        help_text="How many days a sold-before-inward line may wait to be costed "
        "before the store's exception list carries it.",
    )
    return_window_days = models.IntegerField(
        default=30,
        help_text="How many days after a bill a piece comes back without a manager "
        "having to override the window.",
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
            models.CheckConstraint(
                condition=models.Q(uncosted_aging_days__gte=0),
                name="ck_sellpolicy_aging_is_not_negative",
            ),
            # Nought is a legitimate setting - "every return needs the window
            # override" - so the floor is nought and not one.
            models.CheckConstraint(
                condition=models.Q(return_window_days__gte=0),
                name="ck_sellpolicy_window_is_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"cap {self.manual_discount_cap_percent}% · "
            f"credit notes valid {self.credit_note_validity_days}d · "
            f"uncosted flagged after {self.uncosted_aging_days}d · "
            f"returns inside {self.return_window_days}d"
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
    """A named seller at a store - the per-line credit on a bill.

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
    document may not be UPDATEd - the FSM trigger refuses every column change but
    the move to cancelled - so a balance that falls as the note is spent cannot
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
        help_text="The bill that issued it - an exchange whose returns exceeded its sales.",
    )
    source_return = models.ForeignKey(
        "sell.Return",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credit_notes_issued",
        help_text="The plain return that issued it. Exactly one of the two sources "
        "is ever set - a note is handed over either at the end of a bill or at the "
        "end of a return, and never both.",
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

    #: What `with_balance` annotates the balance as. Not `remaining_paise`, because
    #: Django refuses to annotate over a property (there is no setter), and not a
    #: name each caller invents, because then the balance would be spelled twice.
    BALANCE = "remaining"

    @classmethod
    def with_balance(cls, rows: models.QuerySet[CreditNote]) -> models.QuerySet[CreditNote]:
        """`rows` with each note's balance worked out in SQL rather than per note.

        The same subtraction `remaining_paise` does, and the only other place it is
        spelled: a *list* of notes (the till's dataset asks for every one this store
        issued) must not pay a query per row for its balance, and the fix for that
        must not be a second copy of the arithmetic somewhere else.

        Read it off `note.remaining` (`CreditNote.BALANCE`) and hand it to
        `status_at`, rather than reading `note.status`, which would go back to the
        database for the balance the row already carries.
        """
        return rows.annotate(
            **{
                cls.BALANCE: models.F("value_paise")
                - Coalesce(models.Sum("redemptions__amount_paise"), models.Value(0))
            }
        )

    @property
    def status(self) -> str:
        return self.status_at(self.remaining_paise, timezone.localdate())

    def status_at(self, remaining_paise: int, today: date) -> str:
        """`status`, told its two inputs instead of fetching them.

        The rule lives here and only here, but a *list* of notes must not pay a
        query per note for its balance (the till's dataset asks for every open one
        this store issued). So the caller that already has the balance in hand -
        annotated by `with_balance` - and the day it is asking about hands both in,
        and gets the same answer the property gives.
        """
        if self.docstatus == DocStatus.CANCELLED:
            return self.Status.CANCELLED
        if remaining_paise <= 0:
            return self.Status.SPENT
        if self.expires_on < today:
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
        help_text="What the customer pays. May be negative - an exchange whose "
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
    # The manager's tap at the counter (#182). It sits on the bill as well as on
    # the line it excused, because what a manager authorises is not always a line:
    # an unrecognised credit note is a *tender*, and the lines it helped pay for
    # are ordinary lines. A daily check reading "somebody took an unknown note
    # here" with no name against it would be looking at the one place the
    # counter's second eye was supposed to leave a mark.
    override_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_authorised",
        help_text="The manager who authorised whatever on this bill needed it.",
    )
    override_kind = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="What was authorised - one of `sell.serializers.OVERRIDE_KINDS`: "
        "over_cap_discount, credit_note, or over_cap_discount+credit_note when a "
        "manager was asked both at once.",
    )
    override_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The till's clock when the manager's PIN was accepted, which is "
        "not the same moment as Save & Print.",
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

    @property
    def gstin(self) -> Gstin:
        """The registration the bill was raised under (the store's).

        A property rather than a column: a store belongs to exactly one GSTIN and
        the store is already on the bill, so storing it again would be a second
        copy of one fact. It exists because `post_entries` snapshots
        `doc.store`/`doc.gstin` onto every leg, and Bihar and Jharkhand are
        separate registered persons - a value leg that could not say which one it
        belonged to would be no use to either return.
        """
        return self.store.gstin

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

    `direction` carries the sign - `qty` is always positive. A `return` line is
    the exchange leg: a piece coming back inside the same bill, priced at what the
    customer actually paid for it on the original (D2), never at today's price.
    """

    class Direction(models.TextChoices):
        SALE = "sale", "Sold"
        RETURN = "return", "Returned (exchange leg)"

    class Condition(models.TextChoices):
        GOOD = "good", "Good - back on the shelf"
        DAMAGED = "damaged", "Damaged - into quarantine"

    class CostingStatus(models.TextChoices):
        POSTED = "posted", "Costed"
        DEFERRED = "deferred", "Waiting on the paperwork"

    class CostBook(models.TextChoices):
        """Which book this piece's cost came out of, snapshotted at billing.

        Not derived on demand, and that is the point. An exchange unwinds a
        posting that already happened, so it has to unwind the one that actually
        happened - and a brand's commercial model is editable master data. A brand
        flipped from SOR to Outright between the sale and the exchange would
        otherwise reverse a brand-owned piece into our own inventory and strand
        what the brand is still owed. The trial balance would stay at zero and the
        subledger tie would still pass, which is exactly why this is a column and
        not a lookup (Rule 3).

        Blank means the books could not place the piece at all: nothing posted, and
        the line waits in `DeferredCosting`.
        """

        OWN = "own", "KDPS-owned - out of our own inventory"
        BRAND = "brand", "Brand-owned - against what we owe the brand"

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
    offer = models.ForeignKey(
        "offers.Offer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sale_lines",
        help_text="The brand-layer rule that won this line. An add-on that stacked "
        "on top is in the evidence, not here: this is 'which offer was this sold "
        "under', which has exactly one answer.",
    )
    offer_evidence = models.JSONField(
        default=dict,
        blank=True,
        help_text="Which rule won, what it beat, and by how much (B3). Kept beside "
        "the FK rather than replaced by it: the rule can be ended and replaced, and "
        "what this bill was priced under has to stay readable afterwards (Rule 3).",
    )
    manual_desc = models.CharField(
        max_length=200, blank=True, default="", help_text="A line the scan could not resolve."
    )
    sold_before_inward = models.BooleanField(default=False)
    costing_status = models.CharField(
        max_length=8, choices=CostingStatus.choices, default=CostingStatus.POSTED
    )
    cost_book = models.CharField(max_length=8, choices=CostBook.choices, blank=True, default="")
    cost_vendor = models.ForeignKey(
        "vendors.Vendor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sale_lines_accrued",
        help_text="Who the brand-owned piece is settled with, frozen at billing. "
        "PROTECT because a return reverses the accrual against this row.",
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

    @property
    def is_return(self) -> bool:
        return self.direction == self.Direction.RETURN

    @property
    def value_paise(self) -> int:
        """What this line is worth on the bill - the price paid, or the refund.

        The same word a plain return's line answers to, so the posting engine can
        take either without asking which table it came from (#184). `direction`
        already carries the sign, so this is a magnitude on both.
        """
        return int(self.net_paise or 0)

    @property
    def cost_paise(self) -> int:
        """What this line's pieces cost the books, at the rate frozen on it."""
        return int(self.unit_cost_paise or 0) * int(self.qty)


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
            # The reverse does not hold - an unverified note is accepted on a
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


class Return(Document):
    """A piece brought back with nothing bought in its place (#184, grill Q7).

    The sibling of the exchange, and everything that differs between the two
    follows from one sentence: an exchange is a *bill*, and this is not. A bill
    has a customer paying for something, so it can carry a return leg inside it
    and net the two. A plain return has no sale to hide behind - the counter is
    only giving value back - which makes it the best-documented theft channel at
    any POS, and so:

    * **No cash leg exists on this document by construction.** The customer takes
      a credit note for what they actually paid, and the money stays inside the
      system until it is spent on a real bill.
    * **Every one of them takes a manager's tap.** `override_by` is not nullable
      in practice - the pipeline refuses a return without a manager of this store
      behind it - and the column is what a daily check reads.
    * **The number comes from the server.** Returns are rare and risky, so the
      till disables the whole flow while it is offline (the in-bill exchange still
      works). There is nothing to number offline and no queue to replay.

    `original_sale` is PROTECT rather than SET_NULL: what the customer is owed is
    what they paid on that bill, so a return whose original had gone would be a
    refund with nothing behind it.
    """

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="returns")
    fy = models.CharField(max_length=7)
    original_sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="plain_returns")
    returned_at = models.DateTimeField(help_text="When the counter took the piece back.")
    customer_name = models.CharField(max_length=120, blank=True, default="")
    customer_mobile = models.CharField(max_length=15, blank=True, default="")
    window_override = models.BooleanField(
        default=False,
        help_text="The manager took this back past the return window in SellPolicy. "
        "A second, explicit answer - not something the ordinary override covers.",
    )
    override_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="returns_authorised",
        help_text="The manager who stood behind this return. PROTECT because the "
        "name is the evidence.",
    )
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="returns_taken"
    )

    class Meta(Document.Meta):
        db_table = "sell_return"
        ordering = ["-returned_at", "-id"]
        constraints = [*Document.Meta.constraints]
        indexes = [
            models.Index(fields=["store", "returned_at"], name="return_store_taken_idx"),
        ]

    def __str__(self) -> str:
        return self.doc_number or f"Return(draft #{self.pk})"

    @property
    def doc_type(self) -> str:
        return RETURN_DOC_TYPE

    @property
    def gstin(self) -> Gstin:
        """The registration the return posts under - the store's, as a sale's is.

        `post_entries` snapshots this onto every leg, and Bihar and Jharkhand are
        separate registered persons: a reversal of a Bihar sale has to land in
        Bihar's books whichever counter it was taken at.
        """
        return self.store.gstin

    def series_lookup(self) -> tuple[str, str, str]:
        return self.fy, self.store.code, RETURN_DOC_TYPE


class ReturnLine(TimeStampedModel):
    """One piece off one bill, given back.

    Everything money-shaped here is copied off the line it gives back rather than
    worked out again (D2, Rule 3). What the customer gets is what they paid -
    never today's price - and which book the cost came out of is the book the
    *sale* posted to, whatever the brand's terms have become since.
    """

    return_doc = models.ForeignKey(Return, on_delete=models.CASCADE, related_name="lines")
    line_no = models.IntegerField()
    original_line = models.ForeignKey(
        SaleLine, on_delete=models.PROTECT, related_name="plain_returned_by"
    )
    barcode = models.CharField(max_length=64, db_index=True)
    season = models.CharField(max_length=120, blank=True, default="")
    # The same seven merchandising dims a bill line snapshots, for the same
    # reason: a ledger row read years later must not depend on the masters still
    # saying what they said.
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()
    refund_paise = MoneyField(
        default=0, help_text="What the customer actually paid for this quantity (D2)."
    )
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_paise = MoneyField(
        default=0, help_text="The tax inside the refund, at the rate the bill charged."
    )
    unit_cost_paise = MoneyField(
        default=0, help_text="The cost frozen on the original line. Zero when it was never priced."
    )
    cost_book = models.CharField(
        max_length=8, choices=SaleLine.CostBook.choices, blank=True, default=""
    )
    cost_vendor = models.ForeignKey(
        "vendors.Vendor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="return_lines_reversed",
    )
    reason = models.CharField(max_length=40, blank=True, default="")
    condition = models.CharField(
        max_length=8, choices=SaleLine.Condition.choices, default=SaleLine.Condition.GOOD
    )

    class Meta:
        db_table = "sell_return_line"
        ordering = ["return_doc_id", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["return_doc", "line_no"], name="uq_returnline_doc_line_no"
            ),
            models.CheckConstraint(
                condition=models.Q(qty__gt=0), name="ck_returnline_qty_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.return_doc_id}/{self.line_no} · {self.barcode} × {self.qty}"

    @property
    def is_return(self) -> bool:
        """Always. It exists so a return line and a bill's own exchange leg can be
        handed to the same stock and costing code, which asks exactly this."""
        return True

    @property
    def value_paise(self) -> int:
        """What this line is worth - see `SaleLine.value_paise`."""
        return int(self.refund_paise or 0)

    @property
    def cost_paise(self) -> int:
        return int(self.unit_cost_paise or 0) * int(self.qty)


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
        # #187. Not in db-design's original six: the B2B ticket asks for the
        # buyer's GSTIN to be "validated softly (flag, not block)", and the five
        # existing kinds all mean something else. Folding it into GST_MISMATCH
        # would put "a character of this registration is mistyped" and "the tax
        # on this bill is not the dated slab's" in one bucket, and head office
        # answers those two with entirely different work.
        GSTIN_INVALID = "gstin_invalid", "The buyer's GSTIN is not well formed"
        # #184. Two things a plain return can be that nothing else here means.
        #
        # A **late** return is one taken past the window in `SellPolicy`. The
        # `window_override` column on the document says a manager answered for
        # it; this row is what puts it on the store's morning queue, because the
        # window is the one policy at this counter a manager can set aside on
        # their own say-so and the whole point of grill Q7 is that returns are
        # watched.
        #
        # An **uncosted** return is a piece given back before the books could
        # ever price it - sold before its paperwork arrived (#186) and returned
        # before the PT landed. The money reverses, the stock comes back, and
        # there is no cost event to unwind because none was ever posted. It is
        # flagged rather than deferred: `DeferredCosting` hangs off a `SaleLine`
        # and a plain return has none, and posting a guess at what the piece cost
        # is the one outcome worse than telling somebody.
        RETURN_LATE = "return_late", "Taken back after the return window closed"
        RETURN_UNCOSTED = "return_uncosted", "Given back before the books could price it"

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

    class Reason(models.TextChoices):
        """What the books are actually waiting for.

        Three different waits, and the sweep has to tell them apart. An
        `unpriced` piece has no cost of record, so nothing has moved for it yet -
        not the cost event and not the stock leg either, since a piece that was
        never inwarded cannot come off a shelf it was never on. The other two
        *are* on the shelf and *did* leave it: their stock is already posted and
        only the value is missing, so re-posting the movement would take the piece
        out twice.

        They also drain through different doors, which is why `sell.signals` has
        two. An `unpriced` row is released by the PT that prices its cohort. The
        other two are waiting on **master data**, not on an inward - somebody
        adding the brand, or naming its supplier - so no PT will ever release them
        and a brand or supplier edit is what does. Until one arrives they sit in
        the queue: visible, aged by the daily check, and deliberately not posted,
        because a guess about whose stock it was is the one outcome worse than a
        wait.

        A reason is not a fact about the past, either. A line waiting for its price
        can be priced by a PT and still not be placeable, at which point the sweep
        re-labels it as waiting on the masters instead. What the row *has* moved is
        never read off here - see `sell.services.costing_sweep`.
        """

        UNPRICED = "unpriced", "No cost of record - sold before inward"
        MODEL_UNKNOWN = "model_unknown", "The masters do not know this brand"
        VENDOR_UNKNOWN = "vendor_unknown", "Brand-owned, but no supplier of record"

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
    reason = models.CharField(max_length=16, choices=Reason.choices, default=Reason.UNPRICED)
    posted_doc_number = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "sell_deferred_costing"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.barcode} × {self.qty} ({self.status} · {self.reason})"


class HeldBill(TimeStampedModel):
    """A cart the counter put down to serve the next customer (grill Q13).

    The one row in this app that is **not** a fact about money. A hold moves no
    stock, takes no bill number and posts nothing: it is a cart, and a cart is
    just what somebody is thinking about buying.

    It is also the one row the till owns rather than the server. The counter's
    IndexedDB is authoritative - a hold has to survive a dead line, and the
    person who parked it is standing in front of it - and this table exists so
    the Dashboard can say "2 bills on hold" without a manager walking to the
    counter to look. That is why the push replaces the store's whole list rather
    than adding to it: a hold resumed at the counter has to *disappear* here, and
    the till has no per-hold delete to send.

    `payload` is the cart as the till holds it, opaque to the server on purpose.
    Repricing a kept bill happens at the counter on retrieval, against that day's
    rules, so the server has no reason to understand what is inside - and reading
    it as if it meant something would make a mirror into a second opinion.
    """

    class ExpiresPolicy(models.TextChoices):
        TODAY = "today", "Expires at day close unless the store keeps it"
        KEPT = "kept", "The store chose to carry it forward"

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="held_bills")
    held_uuid = models.UUIDField()
    label = models.CharField(max_length=120, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    held_at = models.DateTimeField()
    expires_policy = models.CharField(
        max_length=8, choices=ExpiresPolicy.choices, default=ExpiresPolicy.TODAY
    )

    class Meta:
        db_table = "sell_held_bill"
        ordering = ["held_at", "id"]
        constraints = [
            # Unique **per store**, not across the estate. db-design says
            # "held_uuid UUID unique" and that is a key the till mints, so estate
            # -wide uniqueness looks free - but it makes the store part of the
            # key optional at the upsert, and an upsert that finds a row by uuid
            # alone would move another store's hold onto this counter. Scoping
            # the constraint is what makes the scoped lookup the only one the
            # database will accept.
            models.UniqueConstraint(fields=["store", "held_uuid"], name="uq_heldbill_store_uuid"),
        ]
        indexes = [
            models.Index(fields=["store", "held_at"], name="heldbill_store_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.label or 'Held bill'} · {self.store_id}"


class RegisterHandover(TimeStampedModel):
    """A manager moving a store's bill series onto a different machine (#189).

    The till owns its counter, so a dead or replaced machine takes the counter
    with it (grill Q1). The recovery is deliberate rather than automatic: a named
    manager says "this store is billing from a new device now", gives a reason,
    and the server answers with the number to resume from and the bills it never
    received - which the store re-enters from their printed copies.

    Why the act is recorded at all, when the numbering would work without it:
    every hole this leaves behind is a bill somebody has to go and find on paper,
    and a store that cannot say *when* the machine changed cannot tell a hole
    that has an explanation from one that does not. So this is an audit row in
    the `AccessChange` sense - who, when, why, and what the frontier was at the
    time - and nothing reads it back into a decision.

    It is append-only in practice: nothing in the product updates or deletes a
    row here, because a handover is something that happened.
    """

    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="register_handovers"
    )
    fy = models.CharField(max_length=7)
    reason = models.CharField(max_length=240)
    #: The frontier at the moment of the handover - what the server had accepted
    #: from the old machine. Stored rather than recomputed: the whole value of the
    #: row is that it says what was true then, and by tomorrow it will not be.
    last_accepted_seq = models.IntegerField()
    #: How many numbers below that frontier had never arrived. The list itself is
    #: not stored - it is derivable, it can be five thousand long, and what a
    #: person asks of this row a month later is "how bad was it".
    hole_count = models.IntegerField(default=0)
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="register_handovers"
    )

    class Meta:
        db_table = "sell_register_handover"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["store", "-created_at"], name="handover_store_idx"),
        ]

    def __str__(self) -> str:
        return f"Handover {self.store_id} · {self.fy} · from {self.last_accepted_seq}"


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
