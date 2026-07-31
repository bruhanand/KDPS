"""The server accept pipeline - the one writer of a Sale (api-contract steps 1-13).

A bill reaches this function already printed and already in a customer's hand.
That single fact decides the shape of everything below:

* **Idempotent, always.** The till replays from a durable queue, so the same
  `idempotency_uuid` arriving twice must produce one bill and the same answer,
  with nothing written the second time. Two arriving *at once* is the same
  requirement with a lock in it: the loser blocks on the unique index, wakes to an
  `IntegrityError`, and reads back what the winner wrote (the Shopify pattern,
  grill Q5).
* **Flag, never block.** Six things can be wrong with a bill that has already
  happened - a gap in the numbering, a credit note nobody recognises, a return
  against a bill from the paper era, tax that disagrees with the dated slab - and
  none of them is a reason to refuse a sale the store already made. They become
  `ContinuityFlag` rows on the store's queue and the bill lands (Rule 8).
* **Refuse only what a human must actually resolve.** The six contract error
  codes are all of that shape: the payload contradicts itself, the number belongs
  to somebody else, a discount nobody authorised. The till halts its queue and
  shows an exception card; it never silently drops a bill.

The value side of a bill - the two balanced GL events, the vendor accrual and the
cash-ledger collections - lives in `sell.services.postings` (#178). This module
decides *what happened*; that one decides what it is worth and where it posts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from core.documents import DocStatus
from masters.models import Sku, Store
from masters.scoping import actionable_store_ids
from offers.models import Offer
from offers.resolution import Resolution
from sell.models import (
    ContinuityFlag,
    CreditNote,
    CreditNoteRedemption,
    DeferredCosting,
    IrnQueueItem,
    Sale,
    SaleLine,
    Salesman,
    SaleTender,
    SellPolicy,
)
from sell.pricing import base_from_inclusive, split_line
from sell.services.postings import (
    CostedLine,
    CostPlan,
    plan_from_original,
    post_sale_value,
    resolve_cost_plan,
)
from sell.services.recompute import (
    OFFER_TOLERANCE_PAISE,
    BillLine,
    credit_from_cited_rule,
    resolve_bill,
)
from sell.services.resolve import (
    ResolvedPiece,
    line_dims,
    manager_for_override,
    resolve_piece,
    slab_for,
)
from stockledger.models import StockLedgerEntry
from stockledger.projections import post_on_hand_movement, post_quarantine_movement

#: How far a bill's tax may sit from the dated slab before it is worth a human's
#: time - one rupee a line, per the daily applied-vs-rulebook check (B3, D5 Q10).
GST_TOLERANCE_PAISE = 100

#: The e-invoice clock: a B2B bill must carry an IRN within 30 days (grill Q8).
IRN_DUE_DAYS = 30

#: The two unique constraints that mean "this number is already somebody else's
#: bill" - the till's own key, and the rendered Tally join key the kernel mints
#: from it. Matched by name, so no other integrity failure can borrow the answer.
_BILL_NUMBER_CONSTRAINTS = frozenset({"uq_sale_store_fy_seq", "sell_sale_doc_number_key"})


class AcceptError(Exception):
    """A bill the server will not take, carrying the code the till routes on."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class AcceptResult:
    sale: Sale
    created: bool
    flags: list[str]


@dataclass
class _PreparedLine:
    """One payload line, resolved against the books and ready to be written."""

    payload: dict[str, Any]
    piece: ResolvedPiece
    original: SaleLine | None = None
    original_missing: bool = False
    salesman: Salesman | None = None
    override_needed: bool = False
    row: SaleLine | None = None
    #: How the piece describes itself on the bill (Rule 3), and the season it was
    #: placed in. Settled before the row is written, because the cost plan is
    #: decided from the brand snapshot and the row's `costing_status` from that.
    dims: dict[str, str] = field(default_factory=dict)
    season: str = ""
    cost: CostPlan = field(default_factory=CostPlan)

    @property
    def is_return(self) -> bool:
        return self.payload["direction"] == SaleLine.Direction.RETURN

    @property
    def value_paise(self) -> int:
        return int(self.payload["value_paise"])

    @property
    def qty(self) -> int:
        return int(self.payload["qty"])

    @property
    def unit_cost_paise(self) -> int:
        if self.original is not None:
            return self.original.unit_cost_paise
        return self.piece.unit_cost_paise

    @property
    def is_priced(self) -> bool:
        return self.unit_cost_paise > 0


# --- entry point -----------------------------------------------------------


def accept_sale(data: dict[str, Any], actor: Any) -> AcceptResult:
    """Take one bill, exactly once. See the module docstring for the shape."""
    uuid = data["idempotency_uuid"]
    existing = _find_by_uuid(uuid)
    if existing is not None:
        return _replay(existing)
    try:
        with transaction.atomic():
            return _accept_new(data, actor)
    except IntegrityError as exc:
        # Somebody got there first. If it was this same bill - a concurrent replay
        # from the till's queue - the honest answer is the answer they got, so we
        # read it back rather than reporting a clash. The re-read has to happen
        # out here: the transaction above is aborted and cannot be queried.
        existing = _find_by_uuid(uuid)
        if existing is not None:
            return _replay(existing)
        raise _translate_integrity(exc, data) from exc


def _find_by_uuid(uuid: Any) -> Sale | None:
    return Sale.objects.filter(idempotency_uuid=uuid).select_related("store").first()


def _replay(sale: Sale) -> AcceptResult:
    """The original answer, rebuilt from the bill itself.

    Rebuilt rather than remembered on purpose: a stored copy of the response is a
    second version of the truth that nothing keeps in step with the first. The
    bill and its flags *are* the answer, and reading them back cannot drift from
    what the row says.
    """
    return AcceptResult(sale=sale, created=False, flags=_flag_kinds(sale))


def _flag_kinds(sale: Sale) -> list[str]:
    return sorted({flag.kind for flag in sale.flags.all()})


def _translate_integrity(exc: IntegrityError, data: dict[str, Any]) -> AcceptError:
    """Name the constraint that fired, so the till knows whether to stop.

    Only the two that mean "this number is somebody else's" become a contract
    refusal; anything else is a defect and is re-raised as itself rather than
    dressed up as a business answer.
    """
    diagnostics = getattr(getattr(exc, "__cause__", None), "diag", None)
    # The constraint's own name, never the message text: an unrelated failure
    # that happens to mention a column would otherwise be dressed up as a
    # business answer, and the till would stop a queue over a server defect.
    name = getattr(diagnostics, "constraint_name", "") or ""
    if name in _BILL_NUMBER_CONSTRAINTS:
        return _bill_number_taken(data)
    raise exc


def _bill_number_taken(data: dict[str, Any]) -> AcceptError:
    return AcceptError(
        "BILL_NO_TAKEN",
        f"Bill {data['fy']}/{data['store']}/SAL/{data['till_seq']} already belongs to "
        "another sale. Two tills have been numbering the same series - a person has to "
        "sort this out before it can sync.",
        409,
    )


# --- the pipeline ----------------------------------------------------------


def _accept_new(data: dict[str, Any], actor: Any) -> AcceptResult:
    # Ask again, now that we are inside the transaction. The check in
    # `accept_sale` ran before it, and a concurrent copy of this same bill can
    # commit in between - at which point this is a replay that merely started
    # before the winner finished, and answering it as anything else would report
    # a bill's own twin as a second writer.
    replayed = _find_by_uuid(data["idempotency_uuid"])
    if replayed is not None:
        return _replay(replayed)
    store = _resolve_store(data["store"], actor)  # step 1
    original_bill = _resolve_original_bill(data, store)  # step 8
    lines = _prepare_lines(data, store, original_bill)  # steps 5, 8
    _check_line_arithmetic(lines)  # step 3
    _check_totals(data, lines)  # step 3
    rulebook = _server_resolution(data, store, lines)  # steps 6 and 12 share it
    override = manager_for_override((data.get("override") or {}).get("user_id"), store)
    _check_discount_policy(lines, rulebook, override)  # step 6
    tender_plan = _plan_tenders(data, store, override)  # step 7
    _guard_bill_number(data, store)  # step 4

    sale = _write_sale(data, store, actor, original_bill, lines, override, tender_plan)  # step 9
    minted = sale.post()

    flags: list[str] = []
    flags += _flag_number_hole(sale, store, minted)  # step 4
    flags += _flag_missing_originals(sale, store, lines)  # step 8
    _write_stock_legs(sale, store, lines, actor)  # step 10, the stock half
    _record_deferred(store, lines)  # step 5
    flags += _apply_tenders(sale, store, tender_plan)  # step 7
    _issue_change_note(sale, store, actor)  # step 8
    _post_value(sale, lines, actor)  # step 10, the two value events
    flags += _apply_b2b(sale, store, data)  # step 11
    flags += _advisory_gst_check(sale, store, lines)  # step 12
    flags += _advisory_offer_check(sale, store, lines, rulebook)  # step 12
    return AcceptResult(sale=sale, created=True, flags=sorted(set(flags)))


def _resolve_store(code: str, actor: Any) -> Store:
    """Step 1 - the bill's store, and the caller's right to bill at it."""
    store = Store.objects.select_related("gstin").filter(code__iexact=code.strip()).first()
    if store is None:
        raise AcceptError("VALIDATION", f"No store with code '{code}'.", 400)
    allowed = actionable_store_ids(actor)
    if allowed is not None and store.id not in allowed:
        raise AcceptError(
            "SCOPE_DENIED",
            f"You cannot bill at {store.code}; a till bills for its own store only.",
            403,
        )
    return store


def _resolve_original_bill(data: dict[str, Any], store: Store) -> Sale | None:
    """Step 8 - the bill an exchange gives back against, if we still hold it.

    Pinned to the billing store, and the pin is the point. `till_seq` is a small
    counting number, so a payload naming another store's bill is a guess anybody
    can make - and a lookup that honoured it would let a cashier read back what a
    different shop's customer paid (the refund check quotes it), take that shop's
    cost of record into this shop's ledger, and spend the returnable quantity of a
    line they have never seen. v1 exchanges are same-store anyway (grill Q4), so
    the reference is read as evidence about *this* counter and nothing else.

    A cancelled bill is not returnable either: it has already been reversed, and
    giving back against it would refund what the books say was never sold.
    """
    exchange = data.get("exchange") or None
    if not exchange:
        return None
    ref = exchange["original"]
    return (
        Sale.objects.filter(
            store=store,
            fy=ref["fy"],
            till_seq=ref["till_seq"],
            docstatus=DocStatus.SUBMITTED,
        )
        .prefetch_related("lines")
        .first()
    )


def _prepare_lines(
    data: dict[str, Any], store: Store, original_bill: Sale | None
) -> list[_PreparedLine]:
    """Steps 5 and 8 - every line placed against a cohort or against an original."""
    salesmen = {s.id: s for s in Salesman.objects.filter(store=store)}
    prepared: list[_PreparedLine] = []
    for payload in data["all_lines"]:
        if payload["direction"] == SaleLine.Direction.RETURN:
            line = _prepare_return_line(payload, store, original_bill)
        else:
            line = _prepare_sale_line(payload, store, salesmen)
        line.dims, line.season = _line_description(line)
        # A piece coming back unwinds the posting its own sale made, so its plan is
        # read off that line rather than derived again from masters that may have
        # moved since (Rule 3). Only a paper-era return, whose original bill we do
        # not hold, has nothing to read and falls back to a fresh resolution.
        line.cost = (
            plan_from_original(line.original)
            if line.original is not None
            else resolve_cost_plan(
                brand=line.dims.get("brand", ""),
                barcode=payload["barcode"].strip(),
                season=line.season,
                unit_cost_paise=line.unit_cost_paise,
            )
        )
        prepared.append(line)
    _check_return_quantities(prepared)
    return prepared


def _prepare_sale_line(
    payload: dict[str, Any], store: Store, salesmen: dict[int, Salesman]
) -> _PreparedLine:
    piece = resolve_piece(store, payload["barcode"].strip(), payload["season"].strip())
    if not piece.is_known and not payload["manual_desc"].strip():
        raise AcceptError(
            "LINE_UNRESOLVED",
            f"Line {payload['line_no']}: barcode '{payload['barcode']}' is not in the books "
            "and the line carries no description, so there is nothing to sell.",
            422,
        )
    salesman = salesmen.get(payload["salesman"] or 0)
    if salesman is None:
        raise AcceptError(
            "VALIDATION",
            f"Line {payload['line_no']}: no salesman of this store was named. "
            "Every sold piece carries the name of who sold it.",
            400,
        )
    return _PreparedLine(payload=payload, piece=piece, salesman=salesman)


def _prepare_return_line(
    payload: dict[str, Any], store: Store, original_bill: Sale | None
) -> _PreparedLine:
    original = None
    if original_bill is not None:
        wanted = payload["original_line"]
        original = next(
            (
                line
                for line in original_bill.lines.all()
                if line.direction == SaleLine.Direction.SALE
                and (
                    line.line_no == wanted if wanted else line.barcode == payload["barcode"].strip()
                )
            ),
            None,
        )
    piece = resolve_piece(store, payload["barcode"].strip(), payload["season"].strip())
    return _PreparedLine(
        payload=payload,
        piece=piece,
        original=original,
        # The paper era: a piece bought before the system existed still comes
        # back, and the counter still takes it (flagged, never refused).
        original_missing=original is None,
    )


def _check_return_quantities(lines: list[_PreparedLine]) -> None:
    """A line can only be given back as many times as it was sold.

    `ALREADY_RETURNED` is the contract's own code for this on the plain-return
    endpoint; the exchange leg is the same act inside a bill and answers the same
    way, because the alternative is a refund path with no ceiling on it.
    """
    wanted: dict[int, int] = {}
    for line in lines:
        if line.is_return and line.original is not None:
            wanted[line.original.id] = wanted.get(line.original.id, 0) + line.qty
    for line in lines:
        if not line.is_return or line.original is None:
            continue
        already = _returned_so_far(line.original)[0]
        if already + wanted[line.original.id] > line.original.qty:
            raise AcceptError(
                "ALREADY_RETURNED",
                f"Line {line.payload['line_no']}: only "
                f"{line.original.qty - already} of that piece is still returnable.",
                422,
            )


def _returned_so_far(original: SaleLine) -> tuple[int, int]:
    """`(quantity, paise)` already given back against one sold line.

    The row is **locked** first, and that lock is the ceiling. Without it two
    bills returning the last of a line run the aggregate concurrently, both read
    the same "none returned yet", and both refund - a double refund that no
    database constraint downstream would catch, because each bill is individually
    valid. The credit-note path locks for the same reason.

    A cancelled bill's returns are not counted: the books say that exchange never
    happened, and the customer is still holding the piece and the receipt.
    Counting them would close the refund path over a bill the books themselves
    disown - the next legitimate return would be refused ALREADY_RETURNED, and
    the remainder arithmetic below would under-pay the one after that.
    """
    SaleLine.objects.select_for_update().filter(pk=original.pk).first()
    totals = (
        SaleLine.objects.filter(original_line=original, direction=SaleLine.Direction.RETURN)
        .exclude(sale__docstatus=DocStatus.CANCELLED)
        .aggregate(qty=Sum("qty"), paise=Sum("net_paise"))
    )
    return int(totals["qty"] or 0), int(totals["paise"] or 0)


def _check_line_arithmetic(lines: list[_PreparedLine]) -> None:
    """Step 3 - does each line add up on its own terms?

    Internal consistency only: MRP less discount is the line, and the tax quoted
    is the tax inside it at the rate quoted. Whether that rate is the *right* rate
    is a different question with a different answer (step 12 flags it), because
    the printed bill is a fact and a slab disagreement is not the customer's
    problem.
    """
    for line in lines:
        payload = line.payload
        value = line.value_paise
        if line.is_return:
            _check_return_refund(line)
        else:
            expected = payload["mrp_paise"] * line.qty - payload["disc_paise"]
            if expected != value:
                raise AcceptError(
                    "TENDER_MISMATCH",
                    f"Line {payload['line_no']}: {payload['mrp_paise']} x {line.qty} less "
                    f"{payload['disc_paise']} is {expected}, but the line says {value}.",
                    422,
                )
        rate = Decimal(payload["gst_rate"])
        expected_gst = value - base_from_inclusive(value, rate)
        if expected_gst != payload["gst_paise"]:
            raise AcceptError(
                "TENDER_MISMATCH",
                f"Line {payload['line_no']}: {value} paise at {rate}% carries "
                f"{expected_gst} paise of tax, but the line says {payload['gst_paise']}.",
                422,
            )


def _entitled_refund(original: SaleLine, qty: int) -> int:
    """What `qty` of a sold line is worth back, in whole paise (D2).

    Two rules, and the second is the one that is easy to miss. A share of a line
    is rounded half-up, never by Python's `round()` - that is banker's rounding
    on a float, so a ₹10.05 pair refunds ₹5.02 instead of ₹5.03 and the till's
    correct figure is refused. And the *last* piece of a line is settled as the
    remainder of what has not been given back yet, so the parts always sum to
    exactly what the customer paid: three pieces at ₹10.00 refund 333 + 333 +
    334, not 333 three times with a paisa left in the books forever.
    """
    returned_qty, returned_paise = _returned_so_far(original)
    paid = int(original.net_paise or 0)
    if returned_qty + qty >= original.qty:  # the last of it - settle the remainder
        return paid - returned_paise
    share = Decimal(paid) * qty / original.qty
    return int(share.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _check_return_refund(line: _PreparedLine) -> None:
    """What comes back is what was paid (D2), never today's price.

    When the original bill is ours we hold the number and check it. When it is not
    - a paper-era purchase - there is nothing to check it against, so the till's
    figure stands and the bill carries a flag saying why.
    """
    if line.original is None:
        return
    original = line.original
    entitled = _entitled_refund(original, line.qty)
    if entitled != line.value_paise:
        raise AcceptError(
            "TENDER_MISMATCH",
            f"Line {line.payload['line_no']}: line {original.line_no} of "
            f"{original.sale.doc_number} was paid {entitled} paise for that quantity, "
            f"but the refund says {line.value_paise}.",
            422,
        )


def _check_totals(data: dict[str, Any], lines: list[_PreparedLine]) -> None:
    """Step 3 - do the lines, the totals and the money taken all agree?"""
    totals = data["totals"]
    sales = [line for line in lines if not line.is_return]
    returns = [line for line in lines if line.is_return]
    checks = [
        (
            "gross",
            sum(line.payload["mrp_paise"] * line.qty for line in sales),
            totals["gross_paise"],
        ),
        (
            "discount",
            sum(line.payload["disc_paise"] for line in sales),
            totals["discount_paise"],
        ),
        (
            "net",
            sum(line.value_paise for line in sales)
            - sum(line.value_paise for line in returns)
            + totals["round_paise"],
            totals["net_paise"],
        ),
        (
            "GST",
            sum(line.payload["gst_paise"] for line in sales)
            - sum(line.payload["gst_paise"] for line in returns),
            totals["gst_paise"],
        ),
    ]
    for label, computed, declared in checks:
        if computed != declared:
            raise AcceptError(
                "TENDER_MISMATCH",
                f"The bill's lines come to {computed} paise of {label}, but its total "
                f"says {declared}.",
                422,
            )
    tendered = sum(t["amount_paise"] for t in data["tenders"])
    # A bill that nets negative takes no money at all: the difference leaves as a
    # credit note, never as cash out of the drawer (grill Q7).
    expected = max(totals["net_paise"], 0)
    if tendered != expected:
        raise AcceptError(
            "TENDER_MISMATCH",
            f"The bill is {expected} paise but the tenders come to {tendered}.",
            422,
        )


@dataclass
class _Rulebook:
    """What the rulebook says this bill should have cost - the server's own answer.

    Computed once and used twice: the cap (step 6) subtracts it to find what a
    cashier gave on their own, and the advisory check (step 12) compares it with
    what was actually charged. Both need the *same* number, or a bill could be
    refused for a discount the daily check would then call correct.

    The store, the day and the lines ride along because the cap needs to ask the
    rulebook a second, narrower question - "was the rule this line cites really
    running over this piece?" - and asking it needs all three.
    """

    store: Store
    day: date
    resolution: Resolution
    lines: dict[int, BillLine]
    #: Lines whose discount was credited to the rule they cite rather than to
    #: today's rulebook. Every one is flagged at step 12, whatever the figures
    #: come to - see `_check_discount_policy`.
    drift: set[int] = field(default_factory=set)

    def saving_for(self, line_no: int) -> int:
        outcome = self.resolution.by_line().get(line_no)
        return outcome.discount_paise if outcome else 0

    def credit_for(self, line: _PreparedLine) -> tuple[int, bool]:
        """What this line's discount may be credited to the rulebook, and whether
        that credit came from the rule the line *cites* rather than from today's
        reading of the book.

        The second half is the important one: a credit the current rulebook does
        not produce is a disagreement, and a disagreement is always put in front
        of a human, whatever the amounts happen to be.
        """
        line_no = line.payload["line_no"]
        today = self.saving_for(line_no)
        cited = credit_from_cited_rule(
            line.payload.get("offer_id"),
            self.store.code,
            self.day,
            list(self.lines.values()),
            line_no,
        )
        return max(today, cited), cited > today


def _server_resolution(data: dict[str, Any], store: Store, lines: list[_PreparedLine]) -> _Rulebook:
    """Price this bill's sold lines against the rulebook, server-side.

    The `no_discount` flag is fetched here rather than taken off the payload: it
    is the one input to the rulebook that lives on the SKU master and not on the
    bill, and a till that mis-stated it could discount a piece the AMM sheet says
    is never discounted (D5 Q3).
    """
    day = _billed_on(data)
    sold = [line for line in lines if not line.is_return]
    barcodes = [line.payload["barcode"].strip() for line in sold]
    never_discounted = set(
        Sku.objects.filter(barcode__in=barcodes, no_discount=True).values_list("barcode", flat=True)
    )
    bill_lines = {
        line.payload["line_no"]: BillLine(
            line_no=line.payload["line_no"],
            barcode=line.payload["barcode"].strip(),
            season=line.season,
            qty=line.qty,
            mrp_paise=int(line.payload["mrp_paise"]),
            dims=line.dims,
            no_discount=line.payload["barcode"].strip() in never_discounted,
        )
        for line in sold
    }
    resolution = (
        resolve_bill(store.code, day, list(bill_lines.values()))
        if bill_lines
        else Resolution(lines=(), entitlements=())
    )
    return _Rulebook(store=store, day=day, resolution=resolution, lines=bill_lines)


def _billed_on(data: dict[str, Any]) -> date:
    """The day the counter printed this bill, in the store's own reckoning."""
    return timezone.localdate(data["billed_at"])


def _check_discount_policy(lines: list[_PreparedLine], rulebook: _Rulebook, override: Any) -> None:
    """Step 6 - a discount the rulebook did not produce needs a manager past the cap.

    Whatever the rulebook is answerable for is the rulebook's; the remainder is a
    manual discount, and B2 caps that. Below the cap it is the cashier's to give;
    above it the bill does not close without a manager's OK recorded on it, which
    is the whole of H3.

    The rulebook's share is the server's own resolution, never the till's
    `offer_evidence.saved_paise`: that number arrives from the till, and the till
    is the party the cap exists to constrain. A cap the capped party can lift by
    describing its own discount as an offer is not a cap.

    With one door open, and only one. A line may also be credited with what the
    rule it *cites* works out - re-run server-side, so it is an amount rather
    than a claim (`recompute.credit_from_cited_rule` says why at length). Any
    line credited that way is recorded on `rulebook_drift`, and every one of them
    is flagged at step 12 whatever the figures come to: the door exists so a
    store's queue is not stopped by head office editing master data, not so a
    discount can pass unseen.
    """
    cap_percent = SellPolicy.current().manual_discount_cap_percent
    over: list[_PreparedLine] = []
    for line in lines:
        if line.is_return:
            continue
        credit, drifted = rulebook.credit_for(line)
        given = int(line.payload["disc_paise"])
        # Never more than was actually given, so a rulebook more generous than the
        # counter cannot manufacture headroom for a manual discount on top.
        manual = given - min(credit, given)
        allowance = int(Decimal(line.payload["mrp_paise"] * line.qty) * cap_percent / 100)
        if drifted and manual <= allowance:
            rulebook.drift.add(line.payload["line_no"])
        if manual <= allowance:
            continue
        line.override_needed = True
        over.append(line)
    if over and override is None:
        first = over[0].payload["line_no"]
        raise AcceptError(
            "OVERRIDE_REQUIRED",
            f"Line {first} discounts more than a cashier may on their own "
            f"({cap_percent}% of MRP). A manager of this store has to approve it.",
            422,
        )


@dataclass
class _TenderPlan:
    payload: dict[str, Any]
    note: CreditNote | None = None
    unverified: bool = False


def _plan_tenders(data: dict[str, Any], store: Store, override: Any) -> list[_TenderPlan]:
    """Step 7 - recognise every credit note offered, before anything is written.

    Same-store only in v1 (grill Q4). A note this store does not recognise is not
    automatically a refusal: with a manager's OK the bill is taken and the note is
    flagged into the daily check, because the customer is standing there and the
    note may well be genuine and simply unsynced. Without that OK it is refused.
    """
    plans: list[_TenderPlan] = []
    for payload in data["tenders"]:
        if payload["mode"] != SaleTender.Mode.CREDIT_NOTE:
            plans.append(_TenderPlan(payload=payload))
            continue
        note = _recognised_note(payload, store)
        if note is not None:
            plans.append(_TenderPlan(payload=payload, note=note))
            continue
        if override is None:
            raise AcceptError(
                "CREDIT_NOTE_INVALID",
                f"Credit note '{payload['credit_note']}' is not one this store issued, "
                "is spent or expired, or does not hold that much. A manager of this "
                "store has to approve taking it.",
                422,
            )
        plans.append(_TenderPlan(payload=payload, unverified=True))
    return plans


def _recognised_note(payload: dict[str, Any], store: Store) -> CreditNote | None:
    number = (payload.get("credit_note") or "").strip()
    if not number:
        return None
    note = CreditNote.objects.select_for_update().filter(doc_number=number, store=store).first()
    if note is None or note.status != CreditNote.Status.OPEN:
        return None
    if note.remaining_paise < payload["amount_paise"]:
        return None
    return note


def _guard_bill_number(data: dict[str, Any], store: Store) -> None:
    """Step 4 - is this number already somebody else's bill?

    The database says so too (`uq_sale_store_fy_seq`, and the kernel's unique
    `doc_number`), and that is what makes acceptance exactly-once under a race.
    This check exists so the ordinary case answers with the contract's own code
    instead of an integrity error, and it is the check that would fail first if
    a handover went wrong.
    """
    clash = (
        Sale.objects.filter(store=store, fy=data["fy"], till_seq=data["till_seq"])
        # A row carrying our own key is *this bill*, arriving twice. Without this
        # a replay that overlapped its original would be told its own number
        # belonged to somebody else, and the till would halt a queue over a bill
        # that had in fact synced perfectly.
        .exclude(idempotency_uuid=data["idempotency_uuid"])
        .exists()
    )
    if clash:
        raise _bill_number_taken(data)


def _authorised_kind(lines: list[_PreparedLine], tenders: list[_TenderPlan]) -> str:
    """What the manager's tap on this bill was actually for.

    Derived from what the pipeline itself found, never taken from the payload's
    `override.kind`. The till is the party the override constrains, so a bill
    could otherwise file an over-cap discount under "credit_note" - and the daily
    check, which groups on exactly this field, would count neither honestly.

    The two are joined in one fixed order when a manager was asked both at once,
    so the value a check groups on has one spelling
    (`sell.serializers.OVERRIDE_KINDS`).
    """
    kinds = []
    if any(line.override_needed for line in lines):
        kinds.append("over_cap_discount")
    if any(plan.unverified for plan in tenders):
        kinds.append("credit_note")
    return "+".join(kinds)


def _write_sale(
    data: dict[str, Any],
    store: Store,
    actor: Any,
    original_bill: Sale | None,
    lines: list[_PreparedLine],
    override: Any,
    tenders: list[_TenderPlan],
) -> Sale:
    """Step 9 - the draft and its lines, before a number exists."""
    customer = data.get("customer") or {}
    totals = data["totals"]
    buyer_gstin = (customer.get("gstin") or "").strip().upper()
    # What the till said about the manager's tap. Only the *time* is taken from
    # it - a clock this server does not have - and only when the pipeline
    # recognised the person it named.
    authorisation = (data.get("override") or {}) if override else {}
    sale = Sale.objects.create(
        idempotency_uuid=data["idempotency_uuid"],
        store=store,
        fy=data["fy"],
        till_seq=data["till_seq"],
        origin=data["origin"],
        billed_at=data["billed_at"],
        customer_name=(customer.get("name") or "").strip(),
        customer_mobile=(customer.get("mobile") or "").strip(),
        buyer_gstin=buyer_gstin,
        # Derived here rather than after the number is minted, because a posted
        # document is immutable in the database: the FSM trigger lets a submitted
        # row move to cancelled and change nothing else. Anything a bill is going
        # to say about itself has to be said before it is posted.
        b2b_tax_kind=_b2b_tax_kind(buyer_gstin, store),
        gross_paise=totals["gross_paise"],
        discount_paise=totals["discount_paise"],
        net_paise=totals["net_paise"],
        gst_paise=totals["gst_paise"],
        round_paise=totals["round_paise"],
        exchange_of=original_bill,
        salesman_default=next((line.salesman for line in lines if line.salesman), None),
        # Only a manager the pipeline actually recognised is written here. An
        # override naming somebody who is not a manager of this store has already
        # been discarded by `manager_for_override`, and recording the id anyway
        # would put a name on a bill that person never authorised.
        override_by=override,
        override_kind=_authorised_kind(lines, tenders) if override else "",
        override_at=authorisation.get("at"),
        created_by=actor,
    )
    for line in lines:
        line.row = _write_line(sale, line, override)
    return sale


def _write_line(sale: Sale, line: _PreparedLine, override: Any) -> SaleLine:
    payload = line.payload
    return SaleLine.objects.create(
        sale=sale,
        line_no=payload["line_no"],
        direction=payload["direction"],
        barcode=payload["barcode"].strip(),
        season=line.season,
        **line.dims,
        qty=line.qty,
        mrp_paise=payload["mrp_paise"],
        disc_paise=payload["disc_paise"],
        net_paise=line.value_paise,
        gst_rate=payload["gst_rate"],
        gst_paise=payload["gst_paise"],
        unit_cost_paise=line.unit_cost_paise,
        salesman=line.salesman,
        offer=_offer_cited(payload),
        offer_evidence=payload["offer_evidence"],
        manual_desc=payload["manual_desc"].strip(),
        sold_before_inward=not line.is_return and not line.piece.is_known,
        costing_status=(
            SaleLine.CostingStatus.POSTED if line.cost.postable else SaleLine.CostingStatus.DEFERRED
        ),
        # Frozen here and read back by any exchange against this line: which book
        # the cost came out of, and who a brand-owned piece is settled with. The
        # brand's terms are editable master data; what this bill posted is not.
        cost_book=line.cost.book,
        cost_vendor=line.cost.vendor,
        return_reason=payload["reason"].strip() if line.is_return else "",
        condition=(payload["condition"] or SaleLine.Condition.GOOD) if line.is_return else "",
        original_line=line.original,
        override_by=override if line.override_needed else None,
    )


def _offer_cited(payload: dict[str, Any]) -> Offer | None:
    """The rule the till says won this line, if it names one that exists.

    Recorded, not trusted. What the bill was *worth* is settled by the server's
    own resolution (`_server_resolution`); this field only answers "which rule
    did the counter believe it was selling under", which is the question the
    daily check starts from and which nobody else can answer afterwards. An id
    naming no rule is dropped rather than refused - the bill is printed, and a
    bad reference is a finding for step 12, not a reason to stop a queue.
    """
    offer_id = payload.get("offer_id")
    if not offer_id:
        return None
    return Offer.objects.filter(pk=offer_id).first()


def _line_description(line: _PreparedLine) -> tuple[dict[str, str], str]:
    """How a line describes the piece it is about, snapshotted at billing (Rule 3).

    Three sources, in order of who knows best. A return leg is described by the
    line it gives back - the piece is that piece, whatever the shelf says today. A
    resolved scan is described by its cohort. A scan that resolved to nothing at
    all falls back to the SKU registry, which may still know the barcode even when
    no cohort prices it, and to blanks when even that draws a blank.
    """
    if line.original is not None:
        return line_dims(line.original), line.original.season
    dims = dict(line.piece.dims)
    season = dims.pop("season", "")
    if not dims:
        dims = _dims_from_registry(line.payload["barcode"].strip())
    return dims, season or line.payload["season"].strip()


def _dims_from_registry(barcode: str) -> dict[str, str]:
    """What the SKU master knows about a barcode with no cohort behind it."""
    return line_dims(Sku.objects.filter(barcode=barcode).first())


# --- what happens once the bill has a number -------------------------------


def _flag(sale: Sale, store: Store, kind: str, details: dict[str, Any]) -> str:
    ContinuityFlag.objects.create(kind=kind, store=store, sale=sale, details=details)
    return kind


def _flag_number_hole(sale: Sale, store: Store, minted: Any) -> list[str]:
    """Step 4 - bills the store minted before this one that have not arrived.

    A hole is normal for a few minutes and a problem by end of day, so it is
    reported rather than refused: refusing would stop a store selling because an
    *older* bill is stuck, which is exactly backwards.
    """
    accepted = getattr(minted, "accepted", None)
    if accepted is None or not accepted.hole_count:
        return []
    return [
        _flag(
            sale,
            store,
            ContinuityFlag.Kind.NUMBER_HOLE,
            {
                "from_seq": accepted.hole_from,
                "count": accepted.hole_count,
                "counter_advanced": accepted.counter_advanced,
            },
        )
    ]


def _flag_missing_originals(sale: Sale, store: Store, lines: list[_PreparedLine]) -> list[str]:
    missing = [
        line.payload["line_no"] for line in lines if line.is_return and line.original_missing
    ]
    if not missing:
        return []
    return [
        _flag(
            sale,
            store,
            ContinuityFlag.Kind.RETURN_ORIG_MISSING,
            {"lines": missing},
        )
    ]


def _write_stock_legs(sale: Sale, store: Store, lines: list[_PreparedLine], actor: Any) -> None:
    """Step 10 - the stock half of the bill.

    A sold piece leaves the shelf; a returned one comes back to it, unless it
    comes back damaged, in which case it goes straight into quarantine and never
    becomes sellable again without somebody looking at it (D3).

    A line the books cannot price writes nothing. That is not a gap: the piece was
    never inwarded, so there is no stock to take off a shelf it was never on, and
    the movement posts with the cost event when the paperwork lands (#186).
    """
    for row in _priced_rows(lines):
        mover, kind, sign = _MOVEMENTS[_movement_of(row)]
        mover(
            store=store,
            gstin=store.gstin,
            sku_code=row.barcode,
            source=row,
            qty=sign * row.qty,
            unit_cost_paise=row.unit_cost_paise,
            kind=kind,
            doc_number=sale.doc_number or "",
            line_no=row.line_no,
            posted_by=actor,
        )


def _movement_of(row: SaleLine) -> str:
    """Which of the three things a bill line does to stock."""
    if row.direction != SaleLine.Direction.RETURN:
        return "sold"
    return "returned_damaged" if row.condition == SaleLine.Condition.DAMAGED else "returned_good"


#: The three movements a bill can make, each as `(writer, ledger kind, sign)`.
#: One table rather than a pair of branches, so the bucket a piece lands in and
#: the kind that names it can never be chosen by two different conditions and
#: disagree - which is the failure that would put a damaged return on the shelf.
_MOVEMENTS = {
    "sold": (post_on_hand_movement, StockLedgerEntry.Kind.SALE_OUT, -1),
    "returned_good": (post_on_hand_movement, StockLedgerEntry.Kind.SALE_RETURN_IN, 1),
    "returned_damaged": (post_quarantine_movement, StockLedgerEntry.Kind.QUARANTINE_IN, 1),
}


def _priced_rows(lines: list[_PreparedLine]) -> list[SaleLine]:
    """The `SaleLine` rows the books can price, in payload order.

    The stock half of a bill turns on *pricing* alone, not on the fuller question
    the cost event asks: a piece whose brand the masters cannot place is still a
    piece that left a shelf, and its movement posts now even though its value has
    to wait.
    """
    return [line.row for line in lines if line.row is not None and line.is_priced]


def _record_deferred(store: Store, lines: list[_PreparedLine]) -> None:
    """Step 5 - park every line whose cost the books cannot post yet.

    Three ways a line lands here, and the row says which (`DeferredCosting.Reason`).
    The commonest is a piece sold before its paperwork arrived, so nothing prices
    it; an exchange leg from the paper era, whose original bill we do not hold and
    whose barcode has no cohort, has no cost of record either. The other two are
    priced but unplaceable: the masters have never heard of the brand on the bill,
    or the brand is one whose stock is not ours and nobody can say which supplier
    is owed for it. Booking either of those into INVENTORY on the assumption that
    it is ours is exactly the defect this queue exists to avoid.

    This is the row the Dashboard counts and the daily check ages; the sweep posts
    the cost event when what is missing arrives (#186). Nothing posts at zero in
    the meantime (Rule 5).
    """
    for line in lines:
        if line.row is None or line.cost.postable:
            continue
        DeferredCosting.objects.create(
            sale_line=line.row,
            store=store,
            barcode=line.row.barcode,
            season=line.row.season,
            qty=line.row.qty,
            reason=line.cost.deferral,
        )


def _post_value(sale: Sale, lines: list[_PreparedLine], actor: Any) -> None:
    """Step 10 - the money event and the cost event (see `sell.services.postings`)."""
    post_sale_value(
        sale,
        [CostedLine(row=line.row, plan=line.cost) for line in lines if line.row is not None],
        list(sale.tenders.all()),
        actor,
    )


def _apply_tenders(sale: Sale, store: Store, plans: list[_TenderPlan]) -> list[str]:
    """Step 7 - write the tenders, and spend the notes among them."""
    flags: list[str] = []
    unverified: list[str] = []
    for plan in plans:
        SaleTender.objects.create(
            sale=sale,
            mode=plan.payload["mode"],
            amount_paise=plan.payload["amount_paise"],
            credit_note=plan.note,
        )
        if plan.note is not None:
            CreditNoteRedemption.objects.create(
                credit_note=plan.note, sale=sale, amount_paise=plan.payload["amount_paise"]
            )
        elif plan.unverified:
            unverified.append((plan.payload.get("credit_note") or "").strip())
    if unverified:
        flags.append(_flag(sale, store, ContinuityFlag.Kind.CN_UNVERIFIED, {"notes": unverified}))
    return flags


def _issue_change_note(sale: Sale, store: Store, actor: Any) -> CreditNote | None:
    """Step 8 - an exchange that owes the customer money owes it as a note.

    Cash never leaves the drawer on a return (grill Q7): the difference becomes a
    credit note against this bill, spendable at this store until it expires.
    """
    if sale.net_paise >= 0:
        return None
    policy = SellPolicy.current()
    note = CreditNote.objects.create(
        store=store,
        fy=sale.fy,
        customer_name=sale.customer_name,
        customer_mobile=sale.customer_mobile,
        value_paise=-sale.net_paise,
        expires_on=timezone.localdate(sale.billed_at)
        + timedelta(days=policy.credit_note_validity_days),
        source_sale=sale,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    note.post()
    return note


def _b2b_tax_kind(buyer_gstin: str, store: Store) -> str:
    """Which tax split a bill carries, from the GSTIN's own state code.

    The buyer's state is the first two digits of their GSTIN. Same state as the
    store's registration means CGST + SGST; a different one means IGST. Bihar and
    Jharkhand are separate registrations, so this is an everyday branch here and
    not a corner case.
    """
    if not buyer_gstin:
        return Sale.B2bTaxKind.NONE
    if buyer_gstin[:2] == store.gstin.state_code:
        return Sale.B2bTaxKind.CGST_SGST
    return Sale.B2bTaxKind.IGST


def _apply_b2b(sale: Sale, store: Store, data: dict[str, Any]) -> list[str]:
    """Step 11 - a GSTIN on the bill puts a 30-day clock on head office.

    Above the e-invoice threshold every GSTIN-bearing counter sale is legally a
    B2B invoice that must receive an IRN inside 30 days or the customer loses
    their input credit. The store cannot do that and should not be asked to: the
    deadline rides as data into a head-office queue (Rule 11).

    The split itself was derived before the bill was posted. What is checked here
    is whether the till printed the same thing on the customer's copy - where it
    did not, the bill still lands and the disagreement is flagged.
    """
    if not sale.buyer_gstin:
        return []
    IrnQueueItem.objects.create(
        sale=sale, due_on=timezone.localdate(sale.billed_at) + timedelta(days=IRN_DUE_DAYS)
    )
    declared = data.get("b2b_tax_kind") or ""
    if declared and declared != sale.b2b_tax_kind:
        return [
            _flag(
                sale,
                store,
                ContinuityFlag.Kind.GST_MISMATCH,
                {"printed_split": declared, "derived_split": sale.b2b_tax_kind},
            )
        ]
    return []


def _advisory_gst_check(sale: Sale, store: Store, lines: list[_PreparedLine]) -> list[str]:
    """Step 12 - does the tax charged match the slab that was live that day?

    Advisory by design. The bill is printed and the customer has gone; what this
    buys is the daily check knowing which bills to look at, not a refusal nobody
    could act on. A rupee a line is the threshold (B3).

    Only the sold lines are checked. A return leg is priced at what the customer
    actually paid on the original bill (D2), tax and all, so it deliberately
    carries the *old* rate - measuring it against today's slab would raise a flag
    on every return taken after a rate change, which is the daily check crying
    wolf about the one thing the design asked for.

    The offer half of the same step is `_advisory_offer_check`, below.
    """
    when = timezone.localdate(sale.billed_at)
    offenders = []
    for row in [line.row for line in lines if line.row is not None and not line.is_return]:
        expected = split_line(row.net_paise, row.qty, slab_for(row.hsn, when))
        if abs(expected.gst_paise - row.gst_paise) > GST_TOLERANCE_PAISE:
            offenders.append(
                {
                    "line_no": row.line_no,
                    "charged_paise": row.gst_paise,
                    "slab_paise": expected.gst_paise,
                    "slab_rate": str(expected.rate),
                }
            )
    if not offenders:
        return []
    return [_flag(sale, store, ContinuityFlag.Kind.GST_MISMATCH, {"lines": offenders})]


def _advisory_offer_check(
    sale: Sale, store: Store, lines: list[_PreparedLine], rulebook: _Rulebook
) -> list[str]:
    """Step 12, the offer half - did the counter charge what the rulebook says?

    The daily applied-vs-rulebook check (D5 Q10) is the thing this feeds, and it
    is advisory for the same reason its GST twin is: the bill is printed and the
    customer has gone. What it buys is a store's morning queue knowing which bills
    to look at.

    The comparison is the *whole* discount against the rulebook's, not the till's
    `offer_evidence` against the rulebook's, and that is deliberate. A line where
    the counter gave nothing and the rulebook says the customer was owed ₹600 is
    exactly the finding this check exists for, and comparing evidence with
    evidence would miss it - a till that applied no offer also writes no evidence,
    so the two would agree about nothing and report nothing.

    A cashier's own discount on top is the one thing that would make this cry
    wolf, so it is subtracted out. Note the asymmetry with step 6, which is the
    point rather than an inconsistency: the *cap* refuses to credit the till's own
    `saved_paise`, because a cap the capped party can lift is not a cap; this
    check does credit it, because it is only deciding whether a human should read
    the bill, and the till's account of itself is evidence towards that.
    """
    offenders = []
    for line in lines:
        row = line.row
        if row is None or line.is_return:
            continue
        expected = rulebook.saving_for(row.line_no)
        claimed = int((row.offer_evidence or {}).get("saved_paise") or 0)
        given = int(row.disc_paise or 0)
        keyed_in = max(given - max(claimed, expected), 0)
        charged = given - keyed_in
        if abs(charged - expected) > OFFER_TOLERANCE_PAISE or row.line_no in rulebook.drift:
            offenders.append(
                {
                    "line_no": row.line_no,
                    "charged_paise": charged,
                    "rulebook_paise": expected,
                    "offer_id": row.offer_id,
                }
            )
    if not offenders:
        return []
    return [_flag(sale, store, ContinuityFlag.Kind.OFFER_MISMATCH, {"lines": offenders})]
