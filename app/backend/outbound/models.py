"""Outbound documents — every stock movement *out* of a location.

Each document inherits the kernel's `Document` base (docstatus FSM, gap-free
numbering, immutability guards). Posting logic lives in `outbound.posting`.
"""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.utils import timezone

from approvals.models import ApprovalStatus
from approvals.services import approval_for
from core.base import TimeStampedModel
from core.documents import DocStatus, Document
from core.fiscal import financial_year
from core.money import MoneyField

# ---------------------------------------------------------------------------
# Controlled-vocabulary choices
# ---------------------------------------------------------------------------


class TransferReason(models.TextChoices):
    SISTER_STORE_REQUEST = "sister_store_request", "Sister store request"
    SLOW_MOVER = "slow_mover", "Slow mover"
    SEASONAL_SWAP = "seasonal_swap", "Seasonal swap"
    FREE_FLOOR_SPACE = "free_floor_space", "Free floor space"
    CUSTOMER_WAITING = "customer_waiting", "Customer waiting"
    OTHER = "other", "Other"


class TransportMode(models.TextChoices):
    PUBLIC_BUS = "public_bus", "Public bus"
    COURIER = "courier", "Courier"
    OWN_VEHICLE = "own_vehicle", "Own vehicle"
    HAND_CARRIED = "hand_carried", "Hand-carried"


class AdjustmentReason(models.TextChoices):
    SHRINKAGE = "shrinkage", "Shrinkage"
    MISCOUNT = "miscount", "Miscount"
    DAMAGE = "damage", "Damage"
    SURPLUS_FOUND = "surplus_found", "Surplus found"
    OTHER = "other", "Other"


class ReceiptStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETE = "complete", "Complete"
    SHORTFALL = "shortfall", "Shortfall"


class ReceiptExceptionKind(models.TextChoices):
    """The three things that go wrong at receive (#71), as structured outcomes.

    Free text cannot be counted, chased or reported on, so each one is a row
    with a quantity: **short** (sent but never scanned in — stays in-transit on
    the open transfer), **extra** (a piece arrived that the transfer never sent
    — accepted with a flag, never silently swallowed) and **damaged** (arrived
    broken — raised as a damage document, which quarantines it if the receiver
    holds the confirming rung and otherwise flags it for a warehouse or HO
    person, #138).
    """

    SHORT = "short", "Short — sent but not scanned in"
    EXTRA = "extra", "Extra / wrong item — not on this transfer"
    DAMAGED = "damaged", "Damaged on arrival — raised as a damage flag"


class GapReason(models.TextChoices):
    """Why a transfer's gap is being closed — the three real answers (#71).

    A gap is short pieces still sitting in the in-transit bucket. Each reason
    posts different resolving entries, so the reason is not a note: it is the
    instruction to the ledger.
    """

    FOUND_LATER = "found_later", "Found later — the pieces did arrive"
    LOST_IN_TRANSIT = "lost_in_transit", "Lost in transit — written off"
    WRONGLY_SCANNED = "wrongly_scanned", "Wrongly scanned — never left the sender"


class TransferType(models.TextChoices):
    STORE_SPLIT = "store_split", "Store split (warehouse → store)"
    INTER_STORE = "inter_store", "Inter-store transfer"


class StockRequestStatus(models.TextChoices):
    """The honest status a store sees on its ask (#74) — derived, never stored.

    A stock request posts nothing of its own (the transfer it pre-fills is what
    moves stock), so none of this lives on the document row: after ``post()``
    the kernel FSM freezes every column on it, and the story keeps changing for
    weeks after that (a transfer dispatches, arrives, or a second one follows).
    ``StockRequest.status`` derives it fresh from the approval plus whatever
    transfers now point at it, the same way a transfer's own ``gap_state`` is
    read off its receipt rather than stored.
    """

    PENDING_APPROVAL = "pending_approval", "Pending approval"
    APPROVED = "approved", "Approved"
    DECLINED = "declined", "Declined"
    BEING_FULFILLED = "being_fulfilled", "Being fulfilled"
    PARTLY_FULFILLED = "partly_fulfilled", "Partly fulfilled"
    CLOSED = "closed", "Closed"


class ReturnType(models.TextChoices):
    DEFECTIVE = "defective", "Defective / GR return"
    SEASONAL = "seasonal", "Season-end return"


class LogisticsRoute(models.TextChoices):
    STORE_PICKUP = "store_pickup", "Brand collects from store (Madura)"
    WAREHOUSE_CONSOLIDATION = "warehouse", "Consolidated at warehouse"


# ---------------------------------------------------------------------------
# 1. Store Transfer (store-split + inter-store, same- & cross-state)
# ---------------------------------------------------------------------------


class StoreTransfer(Document):
    """A stock transfer between two locations.

    Store-split (warehouse → store, same GSTIN, no GL) and inter-store
    (MBO → MBO, optional cross-state flag) share the same document.
    """

    source_store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="transfers_out"
    )
    destination_store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="transfers_in"
    )
    transfer_type = models.CharField(
        max_length=16, choices=TransferType.choices, default=TransferType.INTER_STORE
    )
    is_cross_state = models.BooleanField(
        default=False,
        help_text="Auto-set: True when source & destination GSTINs differ.",
    )
    reason = models.CharField(max_length=24, choices=TransferReason.choices, blank=True, default="")

    # Transport tracking (first-class per user requirement)
    transport_mode = models.CharField(
        max_length=16, choices=TransportMode.choices, blank=True, default=""
    )
    transport_ref = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Bus number / courier AWB / vehicle plate",
    )
    dispatcher_name = models.CharField(max_length=120, blank=True, default="")
    expected_arrival_note = models.CharField(max_length=240, blank=True, default="")
    eway_bill_number = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text="Mandatory for cross-state (Bihar ↔ Jharkhand).",
    )

    # Dispatch & receipt tracking
    dispatched_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfers_dispatched",
    )
    dispatch_date = models.DateTimeField(null=True, blank=True)

    # Receipt fields are stored on the companion TransferReceipt model
    # (submitted documents are DB-level immutable per kernel rule)

    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfers_approved",
        help_text="Stamped from the approvals inbox at dispatch — never typed (#137).",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfers_created",
    )
    fulfils_request = models.ForeignKey(
        "StockRequest",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fulfilling_transfers",
        help_text="The store's ask this transfer answers, if any (#74). Set once, "
        "at creation — approving a request approves the ask, never the move, so "
        "this transfer still needs its own gate (#137) before anything dispatches.",
    )
    approvals = GenericRelation("approvals.Approval")

    class Meta(Document.Meta):
        db_table = "outbound_store_transfer"
        ordering = ["-created_at"]

    @property
    def approval_subject(self) -> str:
        """What the approvals inbox leads the row with.

        A transfer is a movement, so the destination is the fact the Operations
        Head is being asked about — the source is already in the line below it.
        Cross-state is called out because those two locations are distinct
        persons under GST: that transfer raises a tax invoice and an e-way bill,
        which is the reason no transfer is left to a store's own say-so (#137).
        """
        destination = self.destination_store.code
        return f"To {destination} · cross-state" if self.is_cross_state else f"To {destination}"

    def series_lookup(self) -> tuple[str, str, str]:
        dt = self.created_at or timezone.now()
        return (
            financial_year(dt.date() if hasattr(dt, "date") else dt),
            self.source_store.code,
            "STO",
        )

    @staticmethod
    def crosses_a_state_line(source: Any, destination: Any) -> bool:
        """Would a move between these two locations be a taxable supply?

        Two GSTINs are two distinct persons under GST, so this decides whether
        an e-way bill is required and whether an IGST invoice must be raised.
        A ``staticmethod`` because the question is asked of a *proposed* move —
        while validating a payload, before any transfer exists — as well as of a
        saved one, and the answer must be the same both times.
        """
        return bool(source and destination and source.gstin_id != destination.gstin_id)

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Auto-compute cross-state flag from GSTIN state codes
        if self.source_store_id and self.destination_store_id:
            self.is_cross_state = self.crosses_a_state_line(
                self.source_store, self.destination_store
            )
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.doc_number or f"Transfer(draft #{self.pk})"


class StoreTransferLine(TimeStampedModel):
    """One line on a store transfer — a (barcode × qty) being moved.

    ``qty_planned`` is the plan (typed / grid-filled on the draft; NULL for
    scan-to-build transfers). ``qty_dispatched`` is what was actually scanned
    out — the only quantity that posts. A planned≠dispatched gap is flagged,
    never blocked (Rule 5).
    """

    transfer = models.ForeignKey(StoreTransfer, on_delete=models.CASCADE, related_name="lines")
    request_line = models.ForeignKey(
        "StockRequestLine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfer_lines",
        help_text="Which line of the store's ask this line fulfils (#74) — how a "
        "request's honest status reads how much of it has actually arrived.",
    )
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty_planned = models.IntegerField(null=True, blank=True)
    qty_dispatched = models.IntegerField(default=0)
    qty_received = models.IntegerField(default=0)
    qty_resolved = models.IntegerField(
        default=0,
        help_text="Pieces a posted gap closure accounted for (#71) — found later, "
        "returned to the sender, or written off as lost. Deliberately not folded "
        "into qty_received: only two of those three ever reached the destination, "
        "and the receipt must keep saying what was actually scanned in.",
    )
    unit_cost_paise = MoneyField(default=0)
    mrp_paise = MoneyField(
        null=True,
        blank=True,
        help_text="The SKU's ticketed price, snapshotted at dispatch alongside the "
        "cost (Rule 2, snapshot masters). The transfer's PT prints it, and a later "
        "re-ticketing of the SKU must not change what the paper in the carton said.",
    )

    @property
    def qty_in_transit(self) -> int:
        """Derived, never stored: dispatched, not scanned in, and not yet
        accounted for by a gap closure."""
        return self.qty_dispatched - self.qty_received - self.qty_resolved

    class Meta:
        db_table = "outbound_store_transfer_line"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.sku_code} × {self.qty_dispatched}"


class TransferPT(TimeStampedModel):
    """The PT file that travels with a transfer's carton (#72).

    Generated once, at dispatch, from the scanned lines — the document the store
    at the other end opens is the same list of pieces the ledger moved. There is
    deliberately no write path: ``rows`` is a frozen copy of what
    ``outbound.transfer_pt.build_transfer_pt_rows`` produced, and regenerating
    from the (immutable) scanned lines is the only way it could ever change.

    Storing it rather than deriving it on every read is the point: this is the
    paper that went in the box, so months later the question "what did the
    document say?" has an answer that is not a recomputation.
    """

    transfer = models.OneToOneField(StoreTransfer, on_delete=models.CASCADE, related_name="pt")
    rows = models.JSONField(
        default=list,
        help_text="KDPS PT rows, keyed by the KDPS column names. Never hand-edited.",
    )
    generated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfer_pts_generated",
    )

    class Meta:
        db_table = "outbound_transfer_pt"
        ordering = ["-created_at"]

    @property
    def generated_at(self) -> Any:
        """When the PT was cut. The row is created once and never touched, so
        that is simply when it was created — a second timestamp column would be
        a copy guaranteed to agree."""
        return self.created_at

    def __str__(self) -> str:
        return f"PT for {self.transfer}"


class TransferReceipt(TimeStampedModel):
    """Companion record for transfer receipt (submitted transfers are immutable).

    Created when goods are received at the destination. One receipt per transfer.
    """

    transfer = models.OneToOneField(StoreTransfer, on_delete=models.CASCADE, related_name="receipt")
    received_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfers_received",
    )
    receipt_date = models.DateTimeField(auto_now_add=True)
    receipt_status = models.CharField(
        max_length=12, choices=ReceiptStatus.choices, default=ReceiptStatus.COMPLETE
    )
    shortfall_notes = models.TextField(
        blank=True,
        default="",
        help_text="What the receiver typed about the shortfall. The screen has "
        "always asked for it; until #71 the payload dropped it before the server "
        "saw it, so the one sentence explaining a gap was thrown away.",
    )

    class Meta:
        db_table = "outbound_transfer_receipt"
        ordering = ["-receipt_date"]

    def __str__(self) -> str:
        return f"Receipt for {self.transfer}"


class TransferReceiptException(TimeStampedModel):
    """One thing that went wrong at receive — short, extra or damaged (#71).

    Structured, quantified and kept on the receipt for good, so a wrong delivery
    is a number somebody can chase rather than a chip that disappears when the
    page reloads. ``unit_cost_paise`` is what the books said the piece was worth
    at the moment of receiving; a zero on an *extra* means the books could not
    price the piece at all, so it was recorded but deliberately not brought into
    stock (see ``outbound.posting.post_transfer_receipt``).
    """

    receipt = models.ForeignKey(
        TransferReceipt, on_delete=models.CASCADE, related_name="exceptions"
    )
    kind = models.CharField(max_length=12, choices=ReceiptExceptionKind.choices)
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()
    unit_cost_paise = MoneyField(default=0)
    note = models.CharField(max_length=240, blank=True, default="")

    class Meta:
        db_table = "outbound_transfer_receipt_exception"
        ordering = ["kind", "id"]

    def __str__(self) -> str:
        return f"{self.kind} {self.sku_code} × {self.qty}"


# ---------------------------------------------------------------------------
# 1a. Stock request — the pull side of a transfer (#74)
# ---------------------------------------------------------------------------


class StockRequest(Document):
    """A store's ask for stock held at another location.

    Two gates, not one (Anand's ruling of 26 July): approving *this* document
    approves the ask — that the fulfilling store may commit to sending the
    stock. The transfer it later pre-fills is a separate draft, still gated by
    the Operations Head before anything actually leaves a shelf (#137). This
    document posts no ledger of its own; it is a coordination record the
    fulfilling store answers, not a movement.

    The inbox hangs off the *fulfilling* store, not the store asking: that
    location's stock is what is being committed, so its own person is the one
    who says yes or no (mirroring ``StoreTransfer``, which hangs off its
    *source* for the same reason — see ``outbound.maker_checker``).
    """

    requesting_store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="stock_requests_out"
    )
    fulfilling_store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="stock_requests_in"
    )
    notes = models.CharField(max_length=240, blank=True, default="")
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_requests_approved",
        help_text="Stamped from the approvals inbox once fulfilment starts — never typed (#74).",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_requests_created",
    )
    approvals = GenericRelation("approvals.Approval")

    class Meta(Document.Meta):
        db_table = "outbound_stock_request"
        ordering = ["-created_at"]

    @property
    def approval_subject(self) -> str:
        """What the approvals inbox leads the row with — the fulfilling store is
        being asked to send stock *to* somewhere, so that somewhere is the fact
        that cannot wait for the line below it (mirrors ``StoreTransfer``'s own
        "To <destination>", read from the other end of the same move)."""
        return f"For {self.requesting_store.code}"

    def series_lookup(self) -> tuple[str, str, str]:
        dt = self.created_at or timezone.now()
        return (
            financial_year(dt.date() if hasattr(dt, "date") else dt),
            self.requesting_store.code,
            "SRQ",
        )

    @property
    def status(self) -> StockRequestStatus:
        """The honest status a store sees, derived fresh every read.

        Ordered like the story actually unfolds: an undecided or rejected
        approval settles it outright. Past that, the fulfilling transfers this
        request has spawned (never cancelled ones) say the rest — none in
        flight yet is merely *approved*; full coverage received is *closed*;
        anything less, once the fulfilling store has said no more is coming
        (``closure``), is *partly fulfilled* rather than stuck "being
        fulfilled" forever.
        """
        approval = approval_for(self)
        if approval is None or approval.status == ApprovalStatus.PENDING:
            return StockRequestStatus.PENDING_APPROVAL
        if approval.status == ApprovalStatus.REJECTED:
            return StockRequestStatus.DECLINED

        requested_total = sum(line.qty for line in self.lines.all())
        transfers = [
            t for t in self.fulfilling_transfers.all() if t.docstatus != DocStatus.CANCELLED
        ]
        received_total = sum(
            tl.qty_received
            for t in transfers
            for tl in t.lines.all()
            if tl.request_line_id is not None
        )
        if requested_total and received_total >= requested_total:
            return StockRequestStatus.CLOSED
        if hasattr(self, "closure"):
            return StockRequestStatus.PARTLY_FULFILLED
        if transfers:
            return StockRequestStatus.BEING_FULFILLED
        return StockRequestStatus.APPROVED

    def __str__(self) -> str:
        return self.doc_number or f"StockRequest(draft #{self.pk})"


class StockRequestLine(TimeStampedModel):
    """One SKU × qty a store is asking for.

    No cost field, deliberately: the requesting store is asking for stock it
    does not hold, and the one place this feature shows another location's
    stock at all (the cross-location search that builds this line) is exactly
    the place cost stays hidden (#74). What the ask is worth still sizes the
    approval — ``outbound.maker_checker._line_totals`` prices an unpriced line
    from the *fulfilling* store's own books, same as a scan-to-build transfer
    plan prices from the source.
    """

    request = models.ForeignKey(StockRequest, on_delete=models.CASCADE, related_name="lines")
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField(help_text="Pieces asked for.")

    class Meta:
        db_table = "outbound_stock_request_line"
        ordering = ["id"]

    @property
    def qty_fulfilled(self) -> int:
        """Pieces actually received against this line so far — derived from
        every non-cancelled fulfilling transfer's receipt, never stored."""
        return sum(
            tl.qty_received
            for tl in self.transfer_lines.all()
            if tl.transfer.docstatus != DocStatus.CANCELLED
        )

    def __str__(self) -> str:
        return f"{self.sku_code} × {self.qty}"


class StockRequestClosure(TimeStampedModel):
    """The fulfilling store's "no more is coming" — the one signal a request's
    derived status cannot read off a transfer.

    Full coverage closes a request automatically; a partial one would
    otherwise sit "being fulfilled" forever, since another transfer could
    always follow. This is that decision, recorded once (one row, like a
    transfer's receipt) rather than a column rewritten on a document the
    kernel FSM may have already frozen.
    """

    request = models.OneToOneField(StockRequest, on_delete=models.CASCADE, related_name="closure")
    closed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_request_closures",
    )
    closed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=240, blank=True, default="")

    class Meta:
        db_table = "outbound_stock_request_closure"
        ordering = ["-closed_at"]

    def __str__(self) -> str:
        return f"Closure for {self.request}"


# ---------------------------------------------------------------------------
# 1c. Transfer gap closure (senior-gated, reason-coded)
# ---------------------------------------------------------------------------


class TransferGapClosure(Document):
    """Closes the in-transit gap a short receive left open (#71).

    A short receive is honest but unfinished: the missing pieces stay in the
    in-transit bucket, and somebody has to say what became of them. That
    somebody is never the store that received short — this document is raised
    and approved at HO/warehouse, and the reason it carries decides which
    resolving entries post (``outbound.posting.post_gap_closure``).

    It hangs off the *source* store, not the destination: the sender is
    answerable for the pieces until the receiver scans them in, so the gap is
    the sender's number, its voucher runs on the sender's series, and the
    approval lands in the sender's side of the inbox.
    """

    transfer = models.OneToOneField(
        StoreTransfer, on_delete=models.PROTECT, related_name="gap_closure"
    )
    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="gap_closures"
    )
    reason = models.CharField(max_length=20, choices=GapReason.choices)
    note = models.TextField(blank=True, default="")
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="gap_closures_approved",
        help_text="Stamped by the approvals inbox on approve — never typed (#70).",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="gap_closures_created",
    )
    approvals = GenericRelation("approvals.Approval")

    class Meta(Document.Meta):
        db_table = "outbound_transfer_gap_closure"
        ordering = ["-created_at"]

    @property
    def approval_subject(self) -> str:
        """What the approvals inbox leads the row with — a gap closure means
        nothing there without naming the transfer whose gap it closes.

        The reason rides along because it is the instruction to the ledger, not a
        note: "found later" and "lost in transit" ask the checker for opposite
        things. Frozen onto the request this way, the trail keeps saying which of
        them was put to them, even after the draft is corrected and asked again.
        """
        transfer = self.transfer.doc_number or f"Transfer #{self.transfer_id}"
        return f"{transfer} · {self.get_reason_display()}"

    def series_lookup(self) -> tuple[str, str, str]:
        dt = self.created_at or timezone.now()
        return financial_year(dt.date() if hasattr(dt, "date") else dt), self.store.code, "GAP"

    def __str__(self) -> str:
        return self.doc_number or f"GapClosure(draft #{self.pk})"


class TransferGapClosureLine(TimeStampedModel):
    """One barcode's worth of gap being closed.

    Built from the in-transit remainder at draft time, never typed — the whole
    point is that the closure resolves exactly what the ledger still holds.
    """

    closure = models.ForeignKey(TransferGapClosure, on_delete=models.CASCADE, related_name="lines")
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()
    unit_cost_paise = MoneyField(default=0)

    class Meta:
        db_table = "outbound_transfer_gap_closure_line"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.sku_code} × {self.qty}"


# ---------------------------------------------------------------------------
# 1b. Mark Damaged (global action → a flag, and on confirmation → quarantine)
# ---------------------------------------------------------------------------


class MarkDamaged(Document):
    """The global "mark damaged" action, as a document (Rule 1 — every event is
    a document, Rule 10 — every action has an actor).

    Damage is caught anywhere stock is visible — receiving, on the shelf, during
    counting, at billing — and it takes **two rungs** to move a piece out of
    sellable stock (#138, Anand's ruling of 26 July): a store person *reports*
    damage and the document stays a draft, so nothing moves and the piece is
    still on the shelf; a warehouse or HO person's *confirmation* is what posts
    it. Someone who holds the confirming rung does both in one action.

    Posting writes a ``damage_out`` leg (free-to-sell drops) + a ``quarantine_in``
    leg (into the quarantine bucket) at the same store; the piece stays owned,
    it is just no longer sellable. No GL: an internal reclassification, value
    unchanged on the books (the two legs net to zero, like the in-transit pair).
    """

    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="damage_marks"
    )
    note = models.CharField(max_length=240, blank=True, default="")
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="damage_marks_created",
        help_text="Who reported the damage — kept for good, on the piece (#138).",
    )
    confirmed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="damage_marks_confirmed",
        help_text="Stamped by the approvals inbox on confirm — never typed (#138).",
    )
    approvals = GenericRelation("approvals.Approval")

    class Meta(Document.Meta):
        db_table = "outbound_mark_damaged"
        ordering = ["-created_at"]

    @property
    def approval_subject(self) -> str:
        """What the approvals inbox leads the row with — which pieces the
        confirmer is being asked about.

        "1 line · 3 pcs" is not a damage report anyone can act on: confirming
        takes stock off the shop floor, and the person deciding has to see what
        it is. The first piece names the row and the rest are counted, so the
        line stays short whatever the report's size.
        """
        lines = list(self.lines.all())
        if not lines:
            return "Damage"
        first = lines[0]
        described = " ".join(filter(None, [first.sku_code, first.design, first.color, first.size]))
        more = f" +{len(lines) - 1} more" if len(lines) > 1 else ""
        return f"Damage · {described}{more}"

    def series_lookup(self) -> tuple[str, str, str]:
        dt = self.created_at or timezone.now()
        return financial_year(dt.date() if hasattr(dt, "date") else dt), self.store.code, "DMG"

    def __str__(self) -> str:
        return self.doc_number or f"MarkDamaged(draft #{self.pk})"


class MarkDamagedLine(TimeStampedModel):
    """One SKU line on a mark-damaged document — a (barcode × qty) reported
    damaged, and bound for quarantine once the report is confirmed (#138). Dims +
    unit cost are enriched from the source stock at post time, never typed
    (Rule 6)."""

    mark = models.ForeignKey(MarkDamaged, on_delete=models.CASCADE, related_name="lines")
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()
    unit_cost_paise = MoneyField(default=0)

    class Meta:
        db_table = "outbound_mark_damaged_line"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.sku_code} × {self.qty}"


# ---------------------------------------------------------------------------
# 2. Return to Vendor (defective + seasonal)
# ---------------------------------------------------------------------------


class ReturnToVendor(Document):
    """RTV — stock going back to the brand (defective or seasonal return)."""

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="rtvs")
    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.PROTECT, related_name="rtvs")
    brand = models.ForeignKey(
        "masters.Brand",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rtvs",
    )
    return_type = models.CharField(max_length=12, choices=ReturnType.choices)
    logistics_route = models.CharField(
        max_length=16, choices=LogisticsRoute.choices, blank=True, default=""
    )
    season = models.CharField(max_length=120, blank=True, default="")
    return_window_date = models.DateField(
        null=True,
        blank=True,
        help_text="Deadline for seasonal return (alerts at 30/15/7 days).",
    )

    # Credit note tracking (full recon in Sprint 5)
    credit_note_received = models.BooleanField(default=False)
    credit_note_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rtvs_created",
    )

    class Meta(Document.Meta):
        db_table = "outbound_return_to_vendor"
        ordering = ["-created_at"]

    def series_lookup(self) -> tuple[str, str, str]:
        dt = self.created_at or timezone.now()
        return financial_year(dt.date() if hasattr(dt, "date") else dt), self.store.code, "RTV"

    def __str__(self) -> str:
        return self.doc_number or f"RTV(draft #{self.pk})"


class ReturnToVendorLine(TimeStampedModel):
    """One line on an RTV document."""

    rtv = models.ForeignKey(ReturnToVendor, on_delete=models.CASCADE, related_name="lines")
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()
    unit_cost_paise = MoneyField(default=0)

    class Meta:
        db_table = "outbound_return_to_vendor_line"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.sku_code} × {self.qty}"


# ---------------------------------------------------------------------------
# 3. Stock Adjustment (stocktake variance)
# ---------------------------------------------------------------------------


class StockAdjustment(Document):
    """Corrects the ledger to match a physical count."""

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="adjustments")
    reason = models.CharField(max_length=16, choices=AdjustmentReason.choices)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="adjustments_approved",
        help_text="Stamped by the approvals inbox on approve — never typed (#70).",
    )
    approvals = GenericRelation("approvals.Approval")
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="adjustments_created",
    )

    class Meta(Document.Meta):
        db_table = "outbound_stock_adjustment"
        ordering = ["-created_at"]

    def series_lookup(self) -> tuple[str, str, str]:
        dt = self.created_at or timezone.now()
        return financial_year(dt.date() if hasattr(dt, "date") else dt), self.store.code, "ADJ"

    def __str__(self) -> str:
        return self.doc_number or f"Adjustment(draft #{self.pk})"


class StockAdjustmentLine(TimeStampedModel):
    """One SKU line on a stock adjustment."""

    adjustment = models.ForeignKey(StockAdjustment, on_delete=models.CASCADE, related_name="lines")
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    book_qty = models.IntegerField()
    counted_qty = models.IntegerField()
    adj_qty = models.IntegerField(help_text="counted − book; + surplus, − shrinkage")
    unit_cost_paise = MoneyField(default=0)

    class Meta:
        db_table = "outbound_stock_adjustment_line"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.sku_code} book={self.book_qty} counted={self.counted_qty}"


# ---------------------------------------------------------------------------
# 4. Write-off (dead stock exit)
# ---------------------------------------------------------------------------


class WriteOff(Document):
    """Owner-approved stock exit from the books (dead stock, refused defectives)."""

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="writeoffs")
    reason = models.TextField(blank=True, default="")
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="writeoffs_approved",
        help_text="Stamped by the approvals inbox on approve — never typed (#70).",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="writeoffs_created",
    )
    approvals = GenericRelation("approvals.Approval")

    class Meta(Document.Meta):
        db_table = "outbound_write_off"
        ordering = ["-created_at"]

    def series_lookup(self) -> tuple[str, str, str]:
        dt = self.created_at or timezone.now()
        return financial_year(dt.date() if hasattr(dt, "date") else dt), self.store.code, "WRO"

    def __str__(self) -> str:
        return self.doc_number or f"WriteOff(draft #{self.pk})"


class WriteOffLine(TimeStampedModel):
    """One SKU line on a write-off."""

    writeoff = models.ForeignKey(WriteOff, on_delete=models.CASCADE, related_name="lines")
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()
    unit_cost_paise = MoneyField(default=0)

    class Meta:
        db_table = "outbound_write_off_line"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.sku_code} × {self.qty}"


# ---------------------------------------------------------------------------
# 5. V-flip (brand-owned → KDPS-owned, partial — no settlement claim)
# ---------------------------------------------------------------------------


class VFlip(Document):
    """Ownership flip: brand-owned SOR/Consignment stock → KDPS-owned.

    Physical stock stays on shelf. Brand display prefixed with "V ".
    Settlement claim tracking is Sprint 8 (Payments).
    """

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="vflips")
    original_brand = models.ForeignKey(
        "masters.Brand",
        on_delete=models.PROTECT,
        related_name="vflips",
    )
    season = models.CharField(max_length=120, blank=True, default="")
    authorized_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vflips_authorized",
        help_text="Stamped by the approvals inbox on approve — never typed (#70).",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vflips_created",
    )
    approvals = GenericRelation("approvals.Approval")

    class Meta(Document.Meta):
        db_table = "outbound_vflip"
        ordering = ["-created_at"]

    def series_lookup(self) -> tuple[str, str, str]:
        dt = self.created_at or timezone.now()
        return financial_year(dt.date() if hasattr(dt, "date") else dt), self.store.code, "VFL"

    def __str__(self) -> str:
        return self.doc_number or f"VFlip(draft #{self.pk})"


class VFlipLine(TimeStampedModel):
    """One SKU line on a V-flip."""

    vflip = models.ForeignKey(VFlip, on_delete=models.CASCADE, related_name="lines")
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    qty = models.IntegerField()
    unit_cost_paise = MoneyField(default=0)

    class Meta:
        db_table = "outbound_vflip_line"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.sku_code} × {self.qty}"


# ---------------------------------------------------------------------------
# 6. Stock counting — the blind count session and the stocktake it feeds (#76)
# ---------------------------------------------------------------------------


class CountScope(models.TextChoices):
    """How much of the location one counter took on.

    Scope decides the **book set** — which pieces the count is entitled to
    speak about, and therefore which unscanned pieces come out as shrinkage:

    - ``store``   every piece the books hold here; anything unscanned is missing.
    - ``brand``   every piece of that brand; other brands are untouched.
    - ``section`` only the pieces scanned. The books hold no floor plan, so a
      section count cannot claim a piece is missing from a shelf the system
      cannot see — it can only report on what was found.
    """

    STORE = "store", "Whole store"
    BRAND = "brand", "One brand"
    SECTION = "section", "One section"


class CountStatus(models.TextChoices):
    OPEN = "open", "Open — counting"
    SUBMITTED = "submitted", "Submitted"
    CLOSED = "closed", "Closed — variance applied"


class Stocktake(models.Model):
    """One counting exercise at one location — the thing sessions merge into.

    Counting a 20,000-SKU store is not one person's job, so the unit of work is
    the *session* (one counter, one scope) and the unit of truth is the
    stocktake: several sessions running in parallel over different sections
    merge into a single variance report, because the book number they are all
    being measured against is one number per piece, not one per counter.

    Not a ``Document``: a stocktake moves no stock and posts nothing. It is a
    working record that *produces* a document — the stock adjustment its
    variance is applied through.
    """

    store = models.ForeignKey("masters.Store", on_delete=models.PROTECT, related_name="stocktakes")
    status = models.CharField(max_length=12, choices=CountStatus.choices, default=CountStatus.OPEN)
    note = models.CharField(max_length=240, blank=True, default="")
    opened_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocktakes_opened",
    )
    adjustment = models.ForeignKey(
        StockAdjustment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocktakes",
        help_text="The correction this count produced, once its variance was applied.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "outbound_stocktake"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Stocktake #{self.pk} @ {self.store_id}"


class CountSession(models.Model):
    """One counter's scoped, blind pass over part of a location.

    Blind is the whole design: while the session is open nothing on it answers
    "how many should there be" — the book number is withheld until submit, so a
    counter cannot count to the answer. That is enforced at the seam rather than
    in the screen: an open session simply has no book quantity to serve, because
    the snapshot is not taken until it is submitted.
    """

    stocktake = models.ForeignKey(Stocktake, on_delete=models.CASCADE, related_name="sessions")
    scope = models.CharField(max_length=8, choices=CountScope.choices)
    #: Which brand or which section — the scope's argument. Empty for a store count.
    scope_value = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=12, choices=CountStatus.choices, default=CountStatus.OPEN)
    counted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="count_sessions",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "outbound_count_session"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"CountSession #{self.pk} ({self.scope_label})"

    @property
    def scope_label(self) -> str:
        return f"{self.get_scope_display()}{f' · {self.scope_value}' if self.scope_value else ''}"


class CountSessionLine(models.Model):
    """One barcode on one session — what was counted, and what the books said.

    ``book_qty`` is the snapshot taken **at submit**, not at scan time and not
    at report time. It is what makes mid-count movement detectable: if the live
    book has moved away from this number by the time the variance is applied,
    something happened to the piece between the count and the correction, and
    that line is held back for a human to confirm rather than overwritten.
    """

    session = models.ForeignKey(CountSession, on_delete=models.CASCADE, related_name="lines")
    sku_code = models.CharField(max_length=64)
    design = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=60, blank=True, default="")
    size = models.CharField(max_length=24, blank=True, default="")
    brand = models.CharField(max_length=120, blank=True, default="")
    season = models.CharField(max_length=120, blank=True, default="")
    item = models.CharField(max_length=120, blank=True, default="")
    hsn = models.CharField(max_length=24, blank=True, default="")
    counted_qty = models.IntegerField(default=0)
    book_qty = models.IntegerField(
        null=True,
        blank=True,
        help_text="The book at submit. Null while the session is open — blind (#76).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "outbound_count_session_line"
        ordering = ["sku_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "sku_code"], name="uq_count_session_line_sku"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sku_code} counted={self.counted_qty}"
