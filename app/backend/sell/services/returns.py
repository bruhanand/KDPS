"""The plain return - a piece back, a credit note out, and no cash (#184, Q7).

The sibling of the in-bill exchange, and everything that differs between the two
follows from one sentence: an exchange is a *bill*, and this is not.

An exchange has a customer buying something, so the return leg nets against the
sale and the money that changes hands is the difference. A plain return has no
sale to net against - the counter is only giving value back - which makes it the
best-documented theft channel at any POS. So three things are true here and
nowhere else in this app:

* **No cash leaves the drawer, ever.** The customer takes a credit note for what
  they actually paid, spendable at this store until it expires. `post_return_value`
  cannot write a cash leg because a `Return` has no tenders to write one from;
  it is a property of the document's shape, not a check that could be deleted.
* **Every single one takes a manager.** Not past a value and not past a rung: the
  contract's step 5 asks for the manager on *every* plain return, and the
  pipeline refuses without one. The window in `SellPolicy` is a second, separate
  answer - past it the same manager has to say so explicitly, and the return
  lands flagged.
* **It needs the network.** Returns are rare and risky, so the till disables the
  whole flow while it is offline (the in-bill exchange still works, because that
  is a bill). There is therefore nothing offline to number, no queue to replay,
  and the `SRT` number is allocated server-side like every other document's.

What the customer is owed and what the books unwind are both read off the
*original* line rather than derived again (D2, Rule 3): the refund is what they
paid, and the cost reversal is out of the book the sale actually posted to, even
if the brand's terms have changed since.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.documents import DocStatus
from masters.models import Store
from masters.scoping import actionable_store_ids
from sell.models import (
    ContinuityFlag,
    CreditNote,
    DeferredCosting,
    Return,
    ReturnLine,
    Sale,
    SaleLine,
    SellPolicy,
)
from sell.pricing import base_from_inclusive
from sell.services.movements import post_stock_move
from sell.services.postings import CostedLine, CostPlan, plan_from_original, post_return_value
from sell.services.refunds import entitled_refund, returned_so_far
from sell.services.resolve import line_dims, manager_for_override


class ReturnError(Exception):
    """A return the server will not take, carrying the contract's own code."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class ReturnResult:
    ret: Return
    created: bool
    credit_note: CreditNote | None
    flags: list[str]


@dataclass
class _PreparedLine:
    """One asked-for line, placed against the sold line it gives back."""

    payload: dict[str, Any]
    original: SaleLine
    refund_paise: int = 0
    gst_paise: int = 0
    cost: CostPlan = field(default_factory=CostPlan)
    row: ReturnLine | None = None

    @property
    def qty(self) -> int:
        return int(self.payload["qty"])


# --- entry point -----------------------------------------------------------


def accept_return(data: dict[str, Any], actor: Any) -> ReturnResult:
    """Take one plain return, exactly once (api-contract step 5, steps 1-9).

    Idempotent for the same reason a sale is: this is a money document raised
    over a network somebody's browser may drop halfway through, and the honest
    answer to "did that go through?" is the original answer, not a second credit
    note.
    """
    existing = _find_by_uuid(data["idempotency_uuid"])
    if existing is not None:
        return _replay(existing)
    try:
        with transaction.atomic():
            return _accept_new(data, actor)
    except IntegrityError:
        # Somebody got there first. The only key that can collide here is this
        # request's own `idempotency_uuid` - two copies of one click - so if the
        # document is there, the honest answer is the answer the winner got. The
        # re-read has to happen out here: the transaction above is aborted and
        # cannot be queried. Anything else is a defect and is re-raised as itself.
        existing = _find_by_uuid(data["idempotency_uuid"])
        if existing is None:
            raise
        return _replay(existing)


def _find_by_uuid(uuid: Any) -> Return | None:
    return (
        Return.objects.filter(idempotency_uuid=uuid)
        .select_related("store", "original_sale")
        .prefetch_related("credit_notes_issued", "lines")
        .first()
    )


def _replay(ret: Return) -> ReturnResult:
    """The original answer, rebuilt from the document itself - never remembered.

    The flags are the ones *this* return raised, picked out of the bill's queue
    by the return's own number: a flag hangs off the original sale (see `_flag`),
    and a bill somebody has returned against twice would otherwise report the
    first return's exceptions as the second one's.
    """
    return ReturnResult(
        ret=ret,
        created=False,
        credit_note=ret.credit_notes_issued.first(),
        flags=sorted(
            {
                flag.kind
                for flag in ret.original_sale.flags.all()
                if (flag.details or {}).get(FLAG_RETURN_KEY) == ret.doc_number
            }
        ),
    )


def _accept_new(data: dict[str, Any], actor: Any) -> ReturnResult:
    # Asked again inside the transaction, exactly as the sale pipeline does: a
    # concurrent copy of this same request can commit between the check above and
    # this one, and answering it as anything but a replay would hand the customer
    # a second credit note for one piece.
    replayed = _find_by_uuid(data["idempotency_uuid"])
    if replayed is not None:
        return _replay(replayed)

    store = _resolve_store(data["store"], actor)  # step 1
    original = _resolve_original(data, store)  # step 3
    manager = manager_for_override((data.get("override") or {}).get("user_id"), store)
    _require_manager(manager, actor)  # step 5
    lines = _prepare_lines(data, original)  # step 3
    late, days_old = _check_window(original)  # step 4
    _check_window_override(late, days_old, bool(data.get("window_override")))

    # The document, then its lines, then the number. Posting an empty document
    # and filling it afterwards would leave a moment - inside this transaction,
    # so nobody could ever see it, but a moment all the same - where the books
    # held a numbered return of nothing. Everything that needs the number (the
    # stock legs, the credit note, the value events) comes after it.
    ret = _write_return(data, store, original, manager, actor, late)  # step 6
    _write_lines(ret, lines)
    ret.post()
    _write_stock_legs(ret, store, lines, actor)  # step 8, the stock half
    _settle_uncosted(lines)
    note = _issue_credit_note(ret, store, original, lines, actor)  # step 7
    _post_value(ret, lines, actor)  # step 8, the value half

    flags = _flag_late(ret, store, original, late, days_old)
    flags += _flag_uncosted(ret, store, original, lines)
    return ReturnResult(ret=ret, created=True, credit_note=note, flags=sorted(set(flags)))


# --- the pipeline ----------------------------------------------------------


def _resolve_store(code: str, actor: Any) -> Store:
    """Step 1 - the store taking the piece back, and this caller's right to.

    The same sentence the sale pipeline uses, and the same refusal: a counter
    takes back its own store's pieces. Same-store redemption is v1's rule for the
    note that comes out of this (grill Q4), so a return raised at another shop
    would hand the customer a note they could not spend where they are standing.
    """
    store = Store.objects.select_related("gstin").filter(code__iexact=code.strip()).first()
    if store is None:
        raise ReturnError("VALIDATION", f"No store with code '{code}'.", 400)
    allowed = actionable_store_ids(actor)
    if allowed is not None and store.id not in allowed:
        raise ReturnError(
            "SCOPE_DENIED",
            f"You cannot take a return at {store.code}; a counter takes back its own "
            "store's pieces.",
            403,
        )
    return store


def _resolve_original(data: dict[str, Any], store: Store) -> Sale:
    """Step 3 - the bill this piece was bought on, at this store.

    Pinned to the store for the reason the exchange path is pinned: `till_seq` is
    a small counting number, so a payload naming another shop's bill is a guess
    anybody could make, and honouring it would read back what a different store's
    customer paid and spend that line's returnable quantity.

    A cancelled bill is not returnable either - it has already been reversed, and
    giving back against it would refund what the books say was never sold.
    """
    ref = data["original"]
    sale = (
        Sale.objects.filter(
            store=store,
            fy=ref["fy"],
            till_seq=ref["till_seq"],
            docstatus=DocStatus.SUBMITTED,
        )
        .prefetch_related("lines")
        .first()
    )
    if sale is None:
        raise ReturnError(
            "ORIGINAL_NOT_FOUND",
            f"No bill {ref['fy']}/{store.code}/SAL/{ref['till_seq']} at this store. "
            "A plain return gives back against a bill we hold - a piece bought before "
            "the system, or at another shop, is an exchange the manager takes in person.",
            404,
        )
    return sale


def _require_manager(manager: Any, actor: Any) -> None:
    """Step 5 - the manager's tap, on every plain return without exception.

    Not a value band and not a rung the cashier might happen to hold: grill Q7 is
    explicit that *every* plain return takes the manager's tap, because a refund
    with no second pair of eyes is the shape internal refund fraud takes
    everywhere it has been studied.

    **And the manager may not be the person taking the return.** That is floor
    rule 1 - "nobody approves their own document" (`accounts.floors`) - and it is
    the whole of what a second pair of eyes means: a store manager who could raise
    a return and authorise it in the same act has a second pair of eyes that are
    their own. It bites hardest at a shop where the manager *is* the counter, and
    that is the intended cost - the alternative is a rule that switches itself off
    for exactly the person best placed to abuse it. **Whether a lone-manager store
    should be able to take a return with nobody else on the floor is Anand's to
    rule on**; until then the ratified floor holds.
    """
    if manager is None:
        raise ReturnError(
            "OVERRIDE_REQUIRED",
            "Every return takes a manager of this store. Ask them to approve it at the counter.",
            422,
        )
    if getattr(manager, "pk", None) == getattr(actor, "pk", object()):
        raise ReturnError(
            "OVERRIDE_REQUIRED",
            "A return needs a second person. Somebody else who may approve returns at "
            "this store has to put their PIN in.",
            422,
        )


def _prepare_lines(data: dict[str, Any], original: Sale) -> list[_PreparedLine]:
    """Step 3 - each asked-for line, priced at what the customer actually paid."""
    by_line_no = {line.line_no: line for line in original.lines.all()}
    prepared: list[_PreparedLine] = []
    wanted: dict[int, int] = {}
    for payload in data["lines"]:
        sold = by_line_no.get(payload["original_line"])
        if sold is None or sold.direction != SaleLine.Direction.SALE:
            raise ReturnError(
                "VALIDATION",
                f"Bill {original.doc_number} has no sold line {payload['original_line']}.",
                400,
            )
        wanted[sold.id] = wanted.get(sold.id, 0) + int(payload["qty"])
        prepared.append(_PreparedLine(payload=payload, original=sold))
    # **Locked in one fixed order, not in the order the payload happened to
    # list them.** `returned_so_far` takes a row lock on each original line, and
    # two returns against one bill naming the same two lines the opposite way
    # round would each hold what the other waits for - a deadlock, which Postgres
    # resolves by killing one of them with a 500 on a counter with a customer at
    # it. Sorting by the line's own key makes every caller take the same locks in
    # the same sequence, which is the whole of the cure.
    prepared.sort(key=lambda line: line.original.pk)
    _check_quantities(prepared, wanted)
    for line in prepared:
        line.refund_paise = entitled_refund(line.original, line.qty)
        line.gst_paise = _tax_inside(line.refund_paise, line.original.gst_rate)
        # The book the *sale* posted to, read off its own line rather than derived
        # again from masters that may have moved since (Rule 3).
        line.cost = plan_from_original(line.original)
    return prepared


def _check_quantities(lines: list[_PreparedLine], wanted: dict[int, int]) -> None:
    """A line can only be given back as many times as it was sold.

    Counted across *both* return paths (`sell.services.refunds`), so a piece
    already exchanged inside a later bill cannot be given back a second time here.
    """
    for line in lines:
        already = returned_so_far(line.original)[0]
        if already + wanted[line.original.id] > line.original.qty:
            raise ReturnError(
                "ALREADY_RETURNED",
                f"Line {line.original.line_no}: only "
                f"{line.original.qty - already} of that piece is still returnable.",
                422,
            )


def _tax_inside(refund_paise: int, rate: Decimal) -> int:
    """The tax inside a refund, at the rate the *bill* charged.

    Never today's slab. What is being given back is what the customer paid, tax
    and all, so a rate change since the bill has nothing to do with it - and
    re-deriving the tax would leave the reversal a few paise away from the
    posting it is unwinding.
    """
    return refund_paise - base_from_inclusive(refund_paise, Decimal(rate))


def _check_window(original: Sale) -> tuple[bool, int]:
    """Step 4 - is this bill inside the return window, and how old is it?

    The window is data (grill Q7, `SellPolicy.return_window_days`), so head office
    moves it without a release.

    Both answers come back together because both are needed twice over and neither
    may be worked out a second time: the document records whether it was late, the
    refusal quotes the age, and the flag quotes both. Re-deriving the age is a
    second reading of the clock, and a return taken at one second to midnight
    would then be described by two different numbers.
    """
    window = SellPolicy.current().return_window_days
    days = (timezone.localdate() - timezone.localdate(original.billed_at)).days
    return days > window, days


def _check_window_override(late: bool, days_old: int, window_override: bool) -> None:
    """Past the window the return is not refused - the manager is already standing
    there - but their *second*, explicit answer is required, and the return lands
    flagged either way."""
    if not late or window_override:
        return
    raise ReturnError(
        "OVERRIDE_REQUIRED",
        f"That bill is {days_old} days old and this store takes returns back for "
        f"{SellPolicy.current().return_window_days}. A manager can still take it, but "
        "they have to say so.",
        422,
    )


def _write_return(
    data: dict[str, Any],
    store: Store,
    original: Sale,
    manager: Any,
    actor: Any,
    late: bool,
) -> Return:
    """Step 6 - the draft, before a number exists.

    The customer is copied off the original bill rather than asked for again: the
    credit note has to be findable by whoever comes back with it, and the person
    standing at the counter is the person on that bill.
    """
    return Return.objects.create(
        idempotency_uuid=data["idempotency_uuid"],
        store=store,
        fy=original.fy,
        original_sale=original,
        returned_at=timezone.now(),
        customer_name=original.customer_name,
        customer_mobile=original.customer_mobile,
        window_override=late,
        override_by=manager,
        created_by=actor,
    )


def _write_lines(ret: Return, lines: list[_PreparedLine]) -> None:
    """The lines, described as the piece was described when it was sold (Rule 3)."""
    for number, line in enumerate(lines, start=1):
        original = line.original
        line.row = ReturnLine.objects.create(
            return_doc=ret,
            line_no=number,
            original_line=original,
            barcode=original.barcode,
            season=original.season,
            **line_dims(original),
            qty=line.qty,
            refund_paise=line.refund_paise,
            gst_rate=original.gst_rate,
            gst_paise=line.gst_paise,
            unit_cost_paise=original.unit_cost_paise,
            cost_book=line.cost.book,
            cost_vendor=line.cost.vendor,
            reason=line.payload["reason"].strip(),
            condition=line.payload["condition"],
        )


def _write_stock_legs(ret: Return, store: Store, lines: list[_PreparedLine], actor: Any) -> None:
    """Step 8, the stock half - back to the shelf, or into quarantine (D3).

    A damaged piece never becomes sellable again without somebody looking at it,
    which is the whole reason the condition is asked for at the counter. Which
    bucket a line lands in is `sell.services.movements`, shared with the bill's
    own exchange leg so the two cannot answer it differently.

    A line the books never priced writes nothing: the ledger refuses a movement at
    nought value (Rule 5), and the piece was never inwarded, so there is no shelf
    it came off. It is flagged instead (`_flag_uncosted`).
    """
    for line in lines:
        if line.row is not None and line.row.unit_cost_paise > 0:
            post_stock_move(ret, store, line.row, actor)


def _settle_uncosted(lines: list[_PreparedLine]) -> None:
    """Close the sale's costing queue row for a piece the books never priced.

    A sold-before-inward line (#186) leaves a `DeferredCosting` row waiting for
    the PT that will price its cohort. If the *whole* line comes back before that
    PT arrives, the cost event the sweep is waiting to post and this return's
    reversal are the same figure in opposite directions - so the honest total of
    the pair is nothing, and the row is closed rather than left to fire.

    Without this the sweep would, days later, post COGS for a garment standing on
    the shelf and take it out of stock a second time. The trial balance would stay
    at nought and the subledger tie would still pass, which is exactly the class of
    error that has to be prevented rather than detected.

    **Only a line given back in full**, and the asymmetry is deliberate. The sweep
    posts a whole `SaleLine`'s cost, not a queue row's quantity, so a partly
    returned line cannot be settled by closing anything - it would need the sweep
    to post a part, which is a wider change than this slice. The remainder goes in
    front of a human instead (`_flag_uncosted`), with the quantity on it.
    """
    for line in lines:
        original = line.original
        if int(original.unit_cost_paise or 0) > 0:
            continue
        if returned_so_far(original)[0] < original.qty:  # part of it is still out there
            continue
        DeferredCosting.objects.filter(
            sale_line=original, status=DeferredCosting.Status.WAITING
        ).update(status=DeferredCosting.Status.RETURNED, updated_at=timezone.now())


def _issue_credit_note(
    ret: Return, store: Store, original: Sale, lines: list[_PreparedLine], actor: Any
) -> CreditNote | None:
    """Step 7 - what the customer walks out with instead of cash.

    Validity is data (grill Q7): the note expires `credit_note_validity_days`
    after it was issued, and the till reads that date off its own copy so a note
    dies on the counter's clock without anything being written anywhere (Rule 11).

    Redeemable at this store and no other in v1 (grill Q4) - which the note says
    by naming its issuing store, and which the accept pipeline enforces.
    """
    value = sum(line.refund_paise for line in lines)
    if value <= 0:
        return None
    policy = SellPolicy.current()
    note = CreditNote.objects.create(
        store=store,
        fy=ret.fy,
        customer_name=original.customer_name,
        customer_mobile=original.customer_mobile,
        value_paise=value,
        expires_on=timezone.localdate(ret.returned_at)
        + timedelta(days=policy.credit_note_validity_days),
        source_return=ret,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    note.post()
    return note


def _post_value(ret: Return, lines: list[_PreparedLine], actor: Any) -> None:
    """Step 8, the value half - see `sell.services.postings.post_return_value`."""
    post_return_value(
        ret,
        [CostedLine(row=line.row, plan=line.cost) for line in lines if line.row is not None],
        actor,
    )


# --- what a human is told about afterwards ---------------------------------


#: Where a flag raised by a return names the return itself. `ContinuityFlag` has
#: no column for one - it hangs off a `Sale` - so the number lives in the details,
#: and it is spelled here because `_replay` reads it back out to tell one return's
#: exceptions from another's on the same bill.
FLAG_RETURN_KEY = "return"


def _flag(ret: Return, store: Store, original: Sale, kind: str, details: dict[str, Any]) -> str:
    """One exception row, hung off the bill it is about.

    The flag names the *original sale* rather than the return, because
    `ContinuityFlag.sale` is what the store's action queue and the Dashboard read
    - and because the bill is what somebody opens when they go looking. The
    return's own number rides in the details so the trail is not lost.
    """
    ContinuityFlag.objects.create(
        kind=kind,
        store=store,
        sale=original,
        details={FLAG_RETURN_KEY: ret.doc_number, **details},
    )
    return kind


def _flag_late(ret: Return, store: Store, original: Sale, late: bool, days_old: int) -> list[str]:
    """A return taken past the window, on the store's morning queue.

    The `window_override` column already records that a manager answered for it.
    This is what makes somebody read it: the window is the one policy at this
    counter a manager sets aside on their own say-so, and grill Q7's whole
    argument is that returns are the thing to watch.

    The age comes in from `_check_window` rather than being worked out again, so
    the sentence the counter was shown and the number head office reads are the
    same number.
    """
    if not late:
        return []
    return [
        _flag(
            ret,
            store,
            original,
            ContinuityFlag.Kind.RETURN_LATE,
            {
                "days_since_billed": days_old,
                "window_days": SellPolicy.current().return_window_days,
            },
        )
    ]


def _flag_uncosted(
    ret: Return, store: Store, original: Sale, lines: list[_PreparedLine]
) -> list[str]:
    """A piece given back before the books could ever price it (#186 meeting #184).

    Sold before its paperwork arrived and returned before the PT landed. The
    money reverses and the stock never moved either way, so the document is
    honest - and `_settle_uncosted` has already closed the sale's costing queue
    row where the whole line came back, so the sweep will not post a cost for a
    garment standing on the shelf.

    This is raised anyway, because two things remain true and are visible nowhere
    else. **Nothing moved in the stock ledger**: it refuses a movement at nought
    value (Rule 5), so a piece returned *damaged* is physically in the back room
    and counted in no bucket at all - the store has to know. And where only part
    of a line came back, the sale's queue row could not be settled either, so the
    sweep will still post that line's whole cost when the PT lands.
    """
    unpriced = [
        {
            "line": line.row.line_no,
            "original_line": line.original.line_no,
            "qty": line.row.qty,
            "condition": line.row.condition,
            "sale_cost_settled": returned_so_far(line.original)[0] >= line.original.qty,
        }
        for line in lines
        if line.row is not None and line.row.unit_cost_paise <= 0
    ]
    if not unpriced:
        return []
    return [_flag(ret, store, original, ContinuityFlag.Kind.RETURN_UNCOSTED, {"lines": unpriced})]


# --- what the daily check reads --------------------------------------------


def returns_by_employee(store: Store, day: Any) -> list[dict[str, Any]]:
    """How many returns each person took at this store on one day, and for how much.

    Grill Q7 asks for returns to be "counted per employee in the daily check", and
    this is that count. It is a query rather than a stored tally because the
    documents are the truth and a counter beside them is a second one: a return
    cancelled by the kernel's reversing transition stops counting here the moment
    it is cancelled, which is what somebody reading the number would expect.

    Both names are reported, and both matter. `taken_by` is whoever was working
    the counter; `approved_by` is the manager who stood behind it. The pattern the
    loss-prevention literature describes is one name recurring in either column,
    so a check that only knew about one of them would be half a check.

    The daily check itself is #188; this is what it reads.
    """
    rows = (
        Return.objects.filter(
            store=store,
            returned_at__date=day,
            docstatus=DocStatus.SUBMITTED,
        )
        .select_related("created_by", "override_by")
        .prefetch_related("lines")
    )
    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for ret in rows:
        key = (
            getattr(ret.created_by, "username", "") or "",
            getattr(ret.override_by, "username", "") or "",
        )
        entry = counts.setdefault(
            key,
            {"taken_by": key[0], "approved_by": key[1], "returns": 0, "value_paise": 0},
        )
        entry["returns"] += 1
        entry["value_paise"] += sum(line.refund_paise for line in ret.lines.all())
    return sorted(counts.values(), key=lambda row: (-row["returns"], row["taken_by"]))
