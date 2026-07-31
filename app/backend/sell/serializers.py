"""What a bill looks like on the wire, in and out.

The inbound serializers do **shape** only - is this integer paise, is that one of
the four tender modes, is there at least one line. Everything that needs to know
about the business (does this barcode resolve, does the till's number belong to
this store, is that credit note real) is the accept pipeline's, because those
questions have their own contract error codes and the till routes on the code.
So a serializer failure here is always `VALIDATION` / 400, and never anything else.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from approvals.names import display_name
from sell.models import (
    ContinuityFlag,
    HeldBill,
    IrnQueueItem,
    Return,
    ReturnLine,
    Sale,
    SaleLine,
    SaleTender,
)


class _CustomerWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, allow_blank=True, required=False, default="")
    mobile = serializers.CharField(max_length=15, allow_blank=True, required=False, default="")
    gstin = serializers.CharField(max_length=15, allow_blank=True, required=False, default="")


class _LineWriteSerializer(serializers.Serializer):
    """One line, whether it is being sold or given back inside an exchange."""

    line_no = serializers.IntegerField(min_value=1)
    direction = serializers.ChoiceField(
        choices=SaleLine.Direction.values, required=False, default=SaleLine.Direction.SALE
    )
    barcode = serializers.CharField(max_length=64, allow_blank=True, required=False, default="")
    season = serializers.CharField(max_length=120, allow_blank=True, required=False, default="")
    qty = serializers.IntegerField(min_value=1)
    mrp_paise = serializers.IntegerField(min_value=0, required=False, default=0)
    disc_paise = serializers.IntegerField(min_value=0, required=False, default=0)
    #: A sale line names what the customer paid; a return leg names what is given
    #: back. Both land in `SaleLine.net_paise` - `direction` carries the sign.
    net_paise = serializers.IntegerField(min_value=0, required=False)
    refund_paise = serializers.IntegerField(min_value=0, required=False)
    gst_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, required=False, default=0
    )
    gst_paise = serializers.IntegerField(min_value=0, required=False, default=0)
    salesman = serializers.IntegerField(required=False, allow_null=True, default=None)
    offer_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    offer_evidence = serializers.JSONField(required=False, default=dict)
    manual_desc = serializers.CharField(
        max_length=200, allow_blank=True, required=False, default=""
    )
    condition = serializers.ChoiceField(
        choices=SaleLine.Condition.values, required=False, allow_blank=True, default=""
    )
    reason = serializers.CharField(max_length=40, allow_blank=True, required=False, default="")
    original_line = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="The line number on the original bill this return leg gives back.",
    )
    override_by = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # A sale names `net_paise` and a return leg names `refund_paise`, but the
        # two are the same field on the row - what the line is worth, with
        # `direction` carrying the sign. Either spelling is taken here, because a
        # line arriving under `exchange` is only stamped as a return by the parent
        # serializer, which has not run yet.
        net = attrs.get("net_paise")
        refund = attrs.get("refund_paise")
        preferred = refund if attrs["direction"] == SaleLine.Direction.RETURN else net
        value = preferred if preferred is not None else (net if net is not None else refund)
        if value is None:
            raise serializers.ValidationError(
                f"line {attrs['line_no']}: needs net_paise (a sale) or refund_paise (a return)."
            )
        attrs["value_paise"] = value
        if not attrs["offer_evidence"]:
            attrs["offer_evidence"] = {}
        if not isinstance(attrs["offer_evidence"], dict):
            raise serializers.ValidationError(
                f"line {attrs['line_no']}: offer evidence must be an object."
            )
        return attrs


class _OriginalRefSerializer(serializers.Serializer):
    store = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    fy = serializers.CharField(max_length=7)
    till_seq = serializers.IntegerField(min_value=1)


class _ExchangeWriteSerializer(serializers.Serializer):
    original = _OriginalRefSerializer()
    lines = serializers.ListField(child=_LineWriteSerializer(), allow_empty=False)


class _TenderWriteSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=SaleTender.Mode.values)
    amount_paise = serializers.IntegerField(min_value=0)
    credit_note = serializers.CharField(
        max_length=128, allow_blank=True, required=False, default=""
    )


class _TotalsWriteSerializer(serializers.Serializer):
    gross_paise = serializers.IntegerField(min_value=0)
    discount_paise = serializers.IntegerField(min_value=0)
    #: Deliberately unbounded below: an exchange whose returns outweigh its sales
    #: nets negative and issues a credit note for the difference.
    net_paise = serializers.IntegerField()
    gst_paise = serializers.IntegerField()
    #: Rounding to the nearest rupee can never move a bill by more than 50 paise,
    #: and the bound matters because this line is the one number on the bill that
    #: nothing else derives: it sits inside the net-vs-tenders check, so an
    #: unbounded `round_paise: -50000` would let a bill take ₹500 less than its
    #: lines say and still add up.
    round_paise = serializers.IntegerField(required=False, default=0, min_value=-50, max_value=50)


#: What a manager can be asked to authorise at a till, and the one word a bill
#: uses when they were asked both at once. A closed set, because the daily check
#: groups bills by this value: a spelling nothing recognises is an exception
#: nobody counts. The till builds the pair in this order (`till/cart.ts`).
#:
#: What is *stored* is derived from what the pipeline itself found
#: (`accept._authorised_kind`), never from what arrives here - this validation
#: only keeps the wire honest about what the till believes it is asking for.
OVERRIDE_KINDS = (
    "over_cap_discount",
    "credit_note",
    "over_cap_discount+credit_note",
)


class _OverrideWriteSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    kind = serializers.ChoiceField(
        choices=OVERRIDE_KINDS, allow_blank=True, required=False, default=""
    )
    #: When the manager's PIN was accepted at the counter. A separate moment from
    #: `billed_at` - a manager authorises a discount and the cashier goes on
    #: scanning - and the whole point of the evidence is the gap between the two.
    #: Optional, because a till that predates this field is still a till.
    at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class SaleWriteSerializer(serializers.Serializer):
    """One bill, as the till's queue replays it."""

    idempotency_uuid = serializers.UUIDField()
    store = serializers.CharField(max_length=16)
    fy = serializers.CharField(max_length=7)
    till_seq = serializers.IntegerField(min_value=1)
    origin = serializers.ChoiceField(
        choices=Sale.Origin.values, required=False, default=Sale.Origin.OFFLINE
    )
    billed_at = serializers.DateTimeField()
    customer = _CustomerWriteSerializer(required=False)
    lines = serializers.ListField(child=_LineWriteSerializer(), required=False, default=list)
    exchange = _ExchangeWriteSerializer(required=False, allow_null=True)
    tenders = serializers.ListField(child=_TenderWriteSerializer(), required=False, default=list)
    totals = _TotalsWriteSerializer()
    b2b_tax_kind = serializers.ChoiceField(
        choices=Sale.B2bTaxKind.values, required=False, allow_blank=True, default=""
    )
    override = _OverrideWriteSerializer(required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        exchange = attrs.get("exchange") or None
        exchange_lines = list(exchange["lines"]) if exchange else []
        for line in exchange_lines:
            # Anything under `exchange` is a return leg by construction; the till
            # need not say so twice and cannot say otherwise.
            line["direction"] = SaleLine.Direction.RETURN
        lines = list(attrs.get("lines") or []) + exchange_lines
        if not lines:
            raise serializers.ValidationError("A bill needs at least one line.")
        seen: set[int] = set()
        for line in lines:
            if line["line_no"] in seen:
                raise serializers.ValidationError(f"line {line['line_no']} appears twice.")
            seen.add(line["line_no"])
        attrs["all_lines"] = lines
        # A tender of nothing is not a tender; the till sends an empty credit-note
        # row whenever the panel has one open.
        tenders = [t for t in attrs.get("tenders") or [] if t["amount_paise"] > 0]
        # One note may only appear once on a bill. Two rows naming it would each
        # be checked against the same untouched balance, pass, and then collide on
        # the redemption's unique key - a 500 where the honest answer is "say how
        # much of that note you are spending, once".
        notes = [(t.get("credit_note") or "").strip() for t in tenders]
        named = [n for n in notes if n]
        if len(named) != len(set(named)):
            raise serializers.ValidationError(
                "A credit note may only be tendered once on a bill; add its amounts together."
            )
        attrs["tenders"] = tenders
        return attrs


class _HeldBillWriteSerializer(serializers.Serializer):
    """One parked cart, as the till mirrors it up (contract, step 3).

    `payload` is checked for being an object and for nothing else. It is the
    counter's cart, the counter reprices it on retrieval, and a server that
    validated its shape would be promising to understand a structure it has no
    business reading (see `HeldBill`).
    """

    held_uuid = serializers.UUIDField()
    label = serializers.CharField(
        max_length=120, allow_blank=True, required=False, default="", trim_whitespace=False
    )
    held_at = serializers.DateTimeField()
    expires_policy = serializers.ChoiceField(
        choices=HeldBill.ExpiresPolicy.values,
        required=False,
        default=HeldBill.ExpiresPolicy.TODAY,
    )
    payload = serializers.DictField(required=False, default=dict)


class HeldBillsWriteSerializer(serializers.Serializer):
    """The counter's whole list, which is the only thing it ever sends.

    `held` is required rather than defaulted to empty: "I have nothing parked" is
    a real and destructive statement - it clears the store's Dashboard row - and a
    body that forgot to say it should not be able to make it by accident.
    """

    held = serializers.ListField(child=_HeldBillWriteSerializer(), allow_empty=True)

    def validate_held(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys = [row["held_uuid"] for row in rows]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("The same hold appears twice in one push.")
        return rows


class _ReturnLineWriteSerializer(serializers.Serializer):
    """One line of the original bill, coming back (#184).

    Nothing about money is on the wire, and that is the point: what the customer
    gets back is what they actually paid (D2), which only the server can say. A
    payload that carried a refund figure would be a counter naming its own price
    for a piece it is giving money away on.
    """

    original_line = serializers.IntegerField(min_value=1)
    qty = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=40, allow_blank=True, required=False, default="")
    #: Where the piece goes: back on the shelf, or into quarantine until somebody
    #: looks at it (D3). Defaulted to `good` rather than required, because that is
    #: the ordinary case and the screen makes damaged an explicit choice.
    condition = serializers.ChoiceField(
        choices=SaleLine.Condition.values, required=False, default=SaleLine.Condition.GOOD
    )


class _ReturnOverrideWriteSerializer(serializers.Serializer):
    """The manager behind the return. `user_id` only - who they are is the
    server's question (`manager_for_override`), and a `kind` would be inventing a
    vocabulary for a document that has exactly one thing to authorise."""

    user_id = serializers.IntegerField()


class ReturnWriteSerializer(serializers.Serializer):
    """One plain return, as the Return & Exchange screen raises it."""

    idempotency_uuid = serializers.UUIDField()
    store = serializers.CharField(max_length=16)
    original = _OriginalRefSerializer()
    lines = serializers.ListField(child=_ReturnLineWriteSerializer(), allow_empty=False)
    override = _ReturnOverrideWriteSerializer(required=False, allow_null=True)
    #: The manager's *second* answer, for a bill older than the window in
    #: `SellPolicy`. Separate from `override` on purpose: taking a return is one
    #: decision and taking a late one is another, and a single tick that covered
    #: both would make the window a thing nobody ever actually chose to set aside.
    window_override = serializers.BooleanField(required=False, default=False)

    def validate_lines(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Two rows against one sold line would each be checked against the same
        # untouched returnable quantity and both pass. The quantities belong
        # together on one row, which is also how the screen builds them.
        seen = [row["original_line"] for row in rows]
        if len(seen) != len(set(seen)):
            raise serializers.ValidationError(
                "A line of the bill may only appear once; add the quantities together."
            )
        return rows


class RegisterHandoverWriteSerializer(serializers.Serializer):
    """The one thing a handover asks for: why (#189).

    Required, non-blank, and that is the whole of the validation. The reason is
    the only part of the row a person writes, and it is what makes a handful of
    unexplained holes in a store's bill series into "the counter machine died on
    Tuesday" - so a handover with an empty one would leave exactly the audit
    trail the row exists to prevent.
    """

    reason = serializers.CharField(max_length=240)

    def validate_reason(self, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise serializers.ValidationError(
                "Say why the counter is moving to a different machine."
            )
        return reason


# --- read shapes -------------------------------------------------


class SaleLineReadSerializer(serializers.ModelSerializer[SaleLine]):
    salesman_code = serializers.CharField(source="salesman.code", read_only=True, default="")
    salesman_name = serializers.CharField(source="salesman.name", read_only=True, default="")
    #: How much of this line has already been given back, by either route - an
    #: exchange leg inside a later bill, or a plain return (#184). Annotated by
    #: `refunds.with_returned_qty` on the queryset, so it is one query for the
    #: bill rather than two per line; `0` where nothing annotated it, which is
    #: honest for a caller that did not ask.
    returned_qty = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = SaleLine
        fields = [
            "line_no",
            "direction",
            "barcode",
            "season",
            "design",
            "color",
            "size",
            "brand",
            "item",
            "hsn",
            "qty",
            "mrp_paise",
            "disc_paise",
            "net_paise",
            "gst_rate",
            "gst_paise",
            "salesman_code",
            "salesman_name",
            "offer_evidence",
            "manual_desc",
            "sold_before_inward",
            "costing_status",
            "return_reason",
            "condition",
            "returned_qty",
        ]


class SaleTenderReadSerializer(serializers.ModelSerializer[SaleTender]):
    credit_note_number = serializers.CharField(
        source="credit_note.doc_number", read_only=True, default=""
    )

    class Meta:
        model = SaleTender
        fields = ["mode", "amount_paise", "credit_note_number"]


class FlagReadSerializer(serializers.ModelSerializer[ContinuityFlag]):
    class Meta:
        model = ContinuityFlag
        fields = ["kind", "status", "details", "created_at"]


class SaleReadSerializer(serializers.ModelSerializer[Sale]):
    """The whole bill, read-only. There is no write counterpart, by design (A7)."""

    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    #: The registration the reprint has to carry. A tax invoice without a GSTIN on
    #: it is not one, and a reprint reached from customer search has no till
    #: behind it to borrow the number from - the dataset is a *counter's* copy,
    #: and whoever is looking up an old bill may not be standing at one.
    store_gstin = serializers.CharField(source="store.gstin.gstin", read_only=True, default="")
    #: The e-invoice reference, once head office has raised one (#187). Blank on
    #: every B2C bill and on a B2B bill still in the queue - and the reprint
    #: prints "IRN to follow" for exactly that blank, because that is what the
    #: original said when it came off the counter's printer.
    #:
    #: A method field rather than `source="irn_queue_item.irn"`, which looks like
    #: it would do: DRF catches the `RelatedObjectDoesNotExist` a B2C bill raises
    #: and answers `None` *before* it ever reaches `default`, so the API would
    #: send `null` where the contract and the TypeScript type both say a string.
    irn = serializers.SerializerMethodField()
    lines = SaleLineReadSerializer(many=True, read_only=True)
    tenders = SaleTenderReadSerializer(many=True, read_only=True)
    flags = FlagReadSerializer(many=True, read_only=True)
    credit_notes_issued = serializers.SerializerMethodField()
    billed_by = serializers.CharField(source="created_by.username", read_only=True, default="")
    authorised_by = serializers.CharField(source="override_by.username", read_only=True, default="")

    class Meta:
        model = Sale
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "store_code",
            "store_name",
            "store_gstin",
            "fy",
            "till_seq",
            "origin",
            "billed_at",
            "customer_name",
            "customer_mobile",
            "buyer_gstin",
            "b2b_tax_kind",
            "irn",
            "gross_paise",
            "discount_paise",
            "net_paise",
            "gst_paise",
            "round_paise",
            "billed_by",
            "authorised_by",
            "override_kind",
            "override_at",
            "lines",
            "tenders",
            "flags",
            "credit_notes_issued",
        ]

    def get_irn(self, obj: Sale) -> str:
        queued = getattr(obj, "irn_queue_item", None)
        return queued.irn if queued else ""

    def get_credit_notes_issued(self, obj: Sale) -> list[dict[str, Any]]:
        return [
            {"doc_number": note.doc_number, "value_paise": note.value_paise}
            for note in obj.credit_notes_issued.all()
        ]


class SaleRowSerializer(serializers.ModelSerializer[Sale]):
    """One row of the customer-search / reprint list."""

    store_code = serializers.CharField(source="store.code", read_only=True)
    lines_summary = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = [
            "id",
            "doc_number",
            "store_code",
            "billed_at",
            "customer_name",
            "customer_mobile",
            "net_paise",
            "lines_summary",
        ]

    def get_lines_summary(self, obj: Sale) -> str:
        lines = list(obj.lines.all())
        pieces = sum(line.qty for line in lines if line.direction == SaleLine.Direction.SALE)
        brands = sorted({line.brand for line in lines if line.brand})
        shown = ", ".join(brands[:2])
        if len(brands) > 2:
            shown = f"{shown} +{len(brands) - 2}"
        piece_word = "piece" if pieces == 1 else "pieces"
        return f"{pieces} {piece_word} · {shown}" if shown else f"{pieces} {piece_word}"


class ReturnLineReadSerializer(serializers.ModelSerializer[ReturnLine]):
    class Meta:
        model = ReturnLine
        fields = [
            "line_no",
            "barcode",
            "season",
            "design",
            "color",
            "size",
            "brand",
            "item",
            "hsn",
            "qty",
            "refund_paise",
            "gst_rate",
            "gst_paise",
            "reason",
            "condition",
        ]


class ReturnReadSerializer(serializers.ModelSerializer[Return]):
    """One plain return, read back (#184).

    `credit_note` is the whole point of the answer: it is what the customer walks
    out with, and the counter reads its number off the screen onto the printed
    slip. `value_paise` is the note's face value, which is also the sum of the
    refunds - said once here rather than left for the screen to add up.
    """

    store_code = serializers.CharField(source="store.code", read_only=True)
    original_doc_number = serializers.CharField(
        source="original_sale.doc_number", read_only=True, default=""
    )
    taken_by = serializers.CharField(source="created_by.username", read_only=True, default="")
    approved_by = serializers.CharField(source="override_by.username", read_only=True, default="")
    lines = ReturnLineReadSerializer(many=True, read_only=True)
    credit_note = serializers.SerializerMethodField()
    value_paise = serializers.SerializerMethodField()

    class Meta:
        model = Return
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "store_code",
            "fy",
            "original_doc_number",
            "returned_at",
            "customer_name",
            "customer_mobile",
            "window_override",
            "taken_by",
            "approved_by",
            "credit_note",
            "value_paise",
            "lines",
        ]

    def get_credit_note(self, obj: Return) -> str:
        note = obj.credit_notes_issued.first()
        return note.doc_number or "" if note else ""

    def get_value_paise(self, obj: Return) -> int:
        return sum(int(line.refund_paise or 0) for line in obj.lines.all())


class IrnQueueRowSerializer(serializers.ModelSerializer[IrnQueueItem]):
    """One B2B bill on head office's clock (#187, grill Q8).

    Everything a clerk needs to raise the invoice on the government portal
    without opening the bill: whose registration it is, what it was worth, which
    split it carries, and how long is left. `days_left` is annotated by the view
    from one `today` rather than computed per row - thirty rows must not disagree
    about what day it is because the clock ticked over mid-response.
    """

    doc_number = serializers.CharField(source="sale.doc_number", read_only=True)
    store_code = serializers.CharField(source="sale.store.code", read_only=True)
    store_name = serializers.CharField(source="sale.store.name", read_only=True)
    billed_at = serializers.DateTimeField(source="sale.billed_at", read_only=True)
    buyer_gstin = serializers.CharField(source="sale.buyer_gstin", read_only=True)
    customer_name = serializers.CharField(source="sale.customer_name", read_only=True)
    b2b_tax_kind = serializers.CharField(source="sale.b2b_tax_kind", read_only=True)
    net_paise = serializers.IntegerField(source="sale.net_paise", read_only=True)
    gst_paise = serializers.IntegerField(source="sale.gst_paise", read_only=True)
    #: Who worked the row, as a person reads a person - `approvals.names` is the
    #: one spelling of that in the project, and it falls back to the username on
    #: an account nobody has given a full name.
    handled_by_name = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()

    class Meta:
        model = IrnQueueItem
        fields = [
            "id",
            "doc_number",
            "store_code",
            "store_name",
            "billed_at",
            "buyer_gstin",
            "customer_name",
            "b2b_tax_kind",
            "net_paise",
            "gst_paise",
            "due_on",
            "days_left",
            "status",
            "irn",
            "handled_by_name",
            "handled_at",
        ]

    def get_handled_by_name(self, obj: IrnQueueItem) -> str:
        return display_name(obj.handled_by)

    def get_days_left(self, obj: IrnQueueItem) -> int:
        """Days to the deadline; negative once it has gone by.

        `today` comes in on the serializer's context because it is the view's
        single reading of the clock (Rule 11 - the deadline is data, and so is the
        day it is measured against).
        """
        return (obj.due_on - self.context["today"]).days


class IrnQueueWriteSerializer(serializers.Serializer):
    """What head office writes back after a run on the portal.

    Only the two terminal answers: a row goes to `generated` with the reference
    the portal gave, or to `failed` so the clerk can see what still has to be
    chased. It never goes back to `pending` - "we tried and it did not work" is a
    fact worth keeping, and a row that could be reset would lose it.
    """

    status = serializers.ChoiceField(
        choices=[IrnQueueItem.Status.GENERATED, IrnQueueItem.Status.FAILED]
    )
    irn = serializers.CharField(max_length=64, allow_blank=True, required=False, default="")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # A generated row with no reference on it is the one shape that would
        # make the queue lie: it would leave the list, and the bill would still
        # have no IRN on it anywhere.
        if attrs["status"] == IrnQueueItem.Status.GENERATED and not attrs["irn"].strip():
            raise serializers.ValidationError("Give the IRN the portal returned.")
        attrs["irn"] = attrs["irn"].strip()
        return attrs
