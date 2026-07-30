"""What a bill looks like on the wire, in and out.

The inbound serializers do **shape** only — is this integer paise, is that one of
the four tender modes, is there at least one line. Everything that needs to know
about the business (does this barcode resolve, does the till's number belong to
this store, is that credit note real) is the accept pipeline's, because those
questions have their own contract error codes and the till routes on the code.
So a serializer failure here is always `VALIDATION` / 400, and never anything else.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from sell.models import ContinuityFlag, Sale, SaleLine, SaleTender


class _CustomerInSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, allow_blank=True, required=False, default="")
    mobile = serializers.CharField(max_length=15, allow_blank=True, required=False, default="")
    gstin = serializers.CharField(max_length=15, allow_blank=True, required=False, default="")


class _LineInSerializer(serializers.Serializer):
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
    #: back. Both land in `SaleLine.net_paise` — `direction` carries the sign.
    net_paise = serializers.IntegerField(min_value=0, required=False)
    refund_paise = serializers.IntegerField(min_value=0, required=False)
    gst_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, required=False, default=0
    )
    gst_paise = serializers.IntegerField(min_value=0, required=False, default=0)
    salesman = serializers.IntegerField(required=False, allow_null=True, default=None)
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
        # two are the same field on the row — what the line is worth, with
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


class _ExchangeInSerializer(serializers.Serializer):
    original = _OriginalRefSerializer()
    lines = serializers.ListField(child=_LineInSerializer(), allow_empty=False)


class _TenderInSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=SaleTender.Mode.values)
    amount_paise = serializers.IntegerField(min_value=0)
    credit_note = serializers.CharField(
        max_length=128, allow_blank=True, required=False, default=""
    )


class _TotalsInSerializer(serializers.Serializer):
    gross_paise = serializers.IntegerField(min_value=0)
    discount_paise = serializers.IntegerField(min_value=0)
    #: Deliberately unbounded below: an exchange whose returns outweigh its sales
    #: nets negative and issues a credit note for the difference.
    net_paise = serializers.IntegerField()
    gst_paise = serializers.IntegerField()
    round_paise = serializers.IntegerField(required=False, default=0)


class _OverrideInSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    kind = serializers.CharField(max_length=40, allow_blank=True, required=False, default="")


class SaleInSerializer(serializers.Serializer):
    """One bill, as the till's queue replays it."""

    idempotency_uuid = serializers.UUIDField()
    store = serializers.CharField(max_length=16)
    fy = serializers.CharField(max_length=7)
    till_seq = serializers.IntegerField(min_value=1)
    origin = serializers.ChoiceField(
        choices=Sale.Origin.values, required=False, default=Sale.Origin.OFFLINE
    )
    billed_at = serializers.DateTimeField()
    customer = _CustomerInSerializer(required=False)
    lines = serializers.ListField(child=_LineInSerializer(), required=False, default=list)
    exchange = _ExchangeInSerializer(required=False, allow_null=True)
    tenders = serializers.ListField(child=_TenderInSerializer(), required=False, default=list)
    totals = _TotalsInSerializer()
    b2b_tax_kind = serializers.ChoiceField(
        choices=Sale.B2bTaxKind.values, required=False, allow_blank=True, default=""
    )
    override = _OverrideInSerializer(required=False, allow_null=True)

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
        attrs["tenders"] = [t for t in attrs.get("tenders") or [] if t["amount_paise"] > 0]
        return attrs


# --- outbound (read) shapes -------------------------------------------------


class SaleLineOutSerializer(serializers.ModelSerializer[SaleLine]):
    salesman_code = serializers.CharField(source="salesman.code", read_only=True, default="")
    salesman_name = serializers.CharField(source="salesman.name", read_only=True, default="")

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
        ]


class SaleTenderOutSerializer(serializers.ModelSerializer[SaleTender]):
    credit_note_number = serializers.CharField(
        source="credit_note.doc_number", read_only=True, default=""
    )

    class Meta:
        model = SaleTender
        fields = ["mode", "amount_paise", "credit_note_number"]


class FlagOutSerializer(serializers.ModelSerializer[ContinuityFlag]):
    class Meta:
        model = ContinuityFlag
        fields = ["kind", "status", "details", "created_at"]


class SaleDetailSerializer(serializers.ModelSerializer[Sale]):
    """The whole bill, read-only. There is no write counterpart, by design (A7)."""

    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    lines = SaleLineOutSerializer(many=True, read_only=True)
    tenders = SaleTenderOutSerializer(many=True, read_only=True)
    flags = FlagOutSerializer(many=True, read_only=True)
    credit_notes_issued = serializers.SerializerMethodField()
    billed_by = serializers.CharField(source="created_by.username", read_only=True, default="")

    class Meta:
        model = Sale
        fields = [
            "id",
            "doc_number",
            "docstatus",
            "store_code",
            "store_name",
            "fy",
            "till_seq",
            "origin",
            "billed_at",
            "customer_name",
            "customer_mobile",
            "buyer_gstin",
            "b2b_tax_kind",
            "gross_paise",
            "discount_paise",
            "net_paise",
            "gst_paise",
            "round_paise",
            "billed_by",
            "lines",
            "tenders",
            "flags",
            "credit_notes_issued",
        ]

    def get_credit_notes_issued(self, obj: Sale) -> list[dict[str, Any]]:
        return [
            {"doc_number": note.doc_number, "value_paise": note.value_paise}
            for note in obj.credit_notes_issued.all()
        ]


class SaleListItemSerializer(serializers.ModelSerializer[Sale]):
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
