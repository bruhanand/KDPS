// The money on the screen (#181, D10 §4).
//
// Everything the Billing page computes lives here, as plain functions over plain
// data, for one reason: the numbers this file produces are checked again by the
// accept pipeline days later, on a bill that has already been printed and paid
// for. A disagreement of one paise is not a rendering bug - it is a queue that
// halts with `TENDER_MISMATCH` and a customer's receipt nobody can post.
//
// So the arithmetic is written against `sell/services/accept.py` step 3, line by
// line:
//
//   gross    = Σ mrp × qty                     (sale lines)
//   discount = Σ disc
//   net      = Σ line net + round
//   GST      = Σ line GST
//   line     : mrp × qty − disc == net, and GST == net − base(net, rate)
//   tenders  : Σ amounts == net
//
// The offer engine (#183) sits inside `priceCart`, and its output is kept in a
// field of its own rather than folded into `disc_paise`. That separation is the
// whole point: `disc_paise` is what a *cashier* keyed in, and it is the thing
// the cap measures. Adding a rulebook discount into it would trip
// `OVERRIDE_REQUIRED` on every offer in the shop; keeping the rulebook's saving
// out of it would understate the bill. So the line carries both, adds them for
// the customer, and sends the sum as the line's discount with the evidence to
// say where it came from.
//
// One thing this file still deliberately does not do: invent a price. A piece
// the books have no MRP for arrives as `null` (contract, step 3) and stops the
// bill until a human types the price off the tag, because a nought would post no
// revenue and no tax against a garment that left the shop.

import { normaliseGstin, taxKindFor } from "./gstin";
import { resolveOffers } from "./offers";
import type { Entitlement, LineOutcome, OfferCart } from "./offers";
import { covers, kindsOf, OVER_CAP_DISCOUNT, UNVERIFIED_NOTE } from "./pin";
import type { Ask, Authorisation } from "./pin";
import { rateHundredths, slabFor, splitLine } from "./pricing";
import { emptyPayment, splitOf, toTenders, whyPaymentCannotClose } from "./tender";
import type { Payment, TenderSplit } from "./tender";
import type {
  BillDraft,
  BillLine,
  NoOffer,
  OfferEvidence,
  StackedCredit,
  TillCreditNote,
  TillGstSlab,
  TillCustomer,
  TillItem,
  TillOffer,
  TillSeason,
} from "./types";

/** One row of the line grid, as the cashier has it so far. */
export interface CartLine {
  /** Stable across re-prices and re-sorts, so React and the season swap have
   *  something to hold that is not the barcode (the same piece can be scanned
   *  twice onto two lines). */
  key: string;
  barcode: string;
  season: string;
  design: string;
  brand: string;
  item: string;
  size: string;
  color: string;
  hsn: string;
  no_discount: boolean;
  /** The ticket price of one piece, GST inclusive. Nought means nobody has
   *  recorded one and the counter must ask. */
  mrp_paise: number;
  /** The books had no price for this piece, so a human is typing one off the
   *  tag. It stays true once the price is typed, because it is a fact about how
   *  the line arrived rather than about what it currently says - and the price
   *  box has to survive the first keystroke that makes the price non-nought. */
  needs_price: boolean;
  qty: number;
  /** Keyed in by the cashier, over the whole line. */
  disc_paise: number;
  salesman: number | null;
  /** The other seasons this barcode is known in - the one-tap "which season?". */
  alternatives: TillItem[];
  /** What the counter's copy said was on the shelf when this was scanned. */
  stock: number;
  /** What the cashier typed for a piece the counter has never heard of (#186).
   *  Empty on every ordinary line: this is the description *instead of* a
   *  cohort, not a note about one. */
  manual_desc: string;
  /** The scan found nothing at all, so this line is being billed off the physical
   *  tag. Kept apart from `needs_price`, which is the milder case of a piece the
   *  books *do* know and simply never priced: this one has no cost of record
   *  either, and the server parks its cost event until the paperwork lands. */
  sold_before_inward: boolean;
}

export interface Cart {
  lines: CartLine[];
  /** How the customer is paying - see `tender.ts`. */
  payment: Payment;
  /** The manager who authorised whatever on this bill needed authorising, as
   *  established by their PIN at this counter (#182). */
  authorisation: Authorisation | null;
}

/** A bill with nothing on it yet. */
export function emptyCart(): Cart {
  return { lines: [], payment: emptyPayment(), authorisation: null };
}

export interface PricedLine extends CartLine {
  line_no: number;
  gross_paise: number;
  /** What the rulebook took off this line, kept apart from `disc_paise` so the
   *  cap measures the cashier and only the cashier. */
  offer_paise: number;
  /** The brand-layer rule that won - the sale line's FK. */
  offer_id: number | null;
  /** One entry per rule that reduced this line, each with its own share: what
   *  the chips on the screen say, and the only honest way to say it. */
  offer_credits: StackedCredit[];
  offer_evidence: OfferEvidence | NoOffer;
  net_paise: number;
  gst_rate: string;
  gst_paise: number;
  /** The most of this line a cashier may knock off on their own (B2). */
  cap_paise: number;
  over_cap: boolean;
}

export interface PricedBill {
  lines: PricedLine[];
  pieces: number;
  gross_paise: number;
  discount_paise: number;
  /** Gifts this bill has earned - a trolley at a token price, and the like. The
   *  counter scans them as ordinary lines; this is the prompt to do so. */
  entitlements: Entitlement[];
  /** What the lines come to before the bill is rounded. */
  subtotal_paise: number;
  round_paise: number;
  net_paise: number;
  gst_paise: number;
  /** The figure staff quote to the customer. */
  saved_paise: number;
  /** How the money is being put up, resolved against this counter's own notes. */
  split: TenderSplit;
  /** Who authorised the exceptions on this bill, if anybody has. */
  authorisation: Authorisation | null;
  /** Everything on this bill a manager has to agree to - empty on an ordinary
   *  bill, and still listed here when a manager has already agreed to it. */
  asks: Ask[];
  /** The asks nobody has agreed to yet. Empty means the bill can close. */
  needsAuthorising: Ask[];
}

export interface PricingWorld {
  seasons: TillSeason[];
  slabs: TillGstSlab[];
  offers: TillOffer[];
  /** The open notes this store issued, as the last sync left them. Offline
   *  redemption is only ever against one of these (grill Q4). */
  creditNotes: TillCreditNote[];
}

export interface PricingOptions {
  /** `SellPolicy.manual_discount_cap_percent`, as it came down in the dataset.
   *  Nought - no keyed-in discount without a manager - is the shipped default
   *  and the safe end of the dial, so it is also the default here. */
  capPercent?: string;
}

/** A scanned piece as a fresh line: one of it, no discount, no salesman yet. */
export function addPiece(
  piece: TillItem,
  found: { stock: number; alternatives: TillItem[] },
  key = newKey(),
): CartLine {
  return {
    key,
    barcode: piece.barcode,
    season: piece.season,
    design: piece.design,
    brand: piece.brand,
    item: piece.item,
    size: piece.size,
    color: piece.color,
    hsn: piece.hsn,
    no_discount: piece.no_discount,
    // `null` means nobody has recorded a price. It becomes a nought here and a
    // refusal to close in `whyItCannotClose` - never a free garment.
    mrp_paise: piece.mrp_paise ?? 0,
    needs_price: piece.mrp_paise == null,
    qty: 1,
    disc_paise: 0,
    salesman: null,
    alternatives: found.alternatives,
    stock: found.stock,
    manual_desc: "",
    sold_before_inward: false,
  };
}

/**
 * A piece the counter has never heard of, billed off the tag in its hand (#186).
 *
 * The whole of grill Q5 in one function: a scan that finds nothing is not a
 * refused customer. The garment is real, the price is printed on it, and the
 * books will catch up when the PT lands - so the line goes on the bill with a
 * description somebody types and a price somebody reads, and the server parks its
 * *cost* event rather than inventing one (Rule 5) or stopping the sale (Rule 8).
 *
 * Everything the books would normally supply is blank on purpose. No brand means
 * no offer can reach it, which is right: a rulebook rule is written about a brand,
 * an item or a design, and this line is none of them yet. No HSN means the tax
 * falls to the general apparel slab, which is what an apparel shop's unknown
 * garment is. And the barcode is kept exactly as scanned even though nothing
 * matches it - it is how the sweep finds this line when the cohort is priced.
 */
export function addManualPiece(barcode: string, key = newKey()): CartLine {
  return {
    key,
    barcode: barcode.trim(),
    season: "",
    design: "",
    brand: "",
    item: "",
    size: "",
    color: "",
    hsn: "",
    no_discount: false,
    mrp_paise: 0,
    // The price box is the point of this line, and it stays open: there is no
    // recorded MRP to fall back on and never will be until the paperwork lands.
    needs_price: true,
    qty: 1,
    disc_paise: 0,
    salesman: null,
    alternatives: [],
    stock: 0,
    manual_desc: "",
    sold_before_inward: true,
  };
}

let keys = 0;

function newKey(): string {
  return `l${(keys += 1)}`;
}

/**
 * A quantity as the counter may type it: whole pieces, never fewer than one.
 *
 * `<input type="number" step="1">` does not stop anybody typing "1.5" - `step`
 * is a validation hint, not a filter, and `e.target.value` hands the string over
 * regardless. A fraction here is not a display nuisance: `mrp × 1.5` puts a
 * float on the write path (ADR-0004), and the server's `IntegerField(min_value=1)`
 * then refuses the bill - after it has printed, with the whole queue behind it.
 */
export function qtyFrom(typed: string | number): number {
  const whole = Math.trunc(Number(typed));
  return Number.isFinite(whole) && whole >= 1 ? whole : 1;
}

/**
 * The most of a line a cashier may discount on their own.
 *
 * `int(Decimal(mrp × qty) × cap / 100)` is what `_check_discount_policy` works
 * out, and `int()` truncates. In hundredths of a percent so nothing here touches
 * a float: a cap that arrived as 7.499999 would put the counter and the server
 * on opposite sides of a refusal.
 */
export function capFor(mrpPaise: number, qty: number, capPercent: string): number {
  return Math.floor((mrpPaise * qty * rateHundredths(capPercent)) / 10_000);
}

/**
 * Price the whole cart: the rulebook, then every line, then the bill.
 *
 * The rulebook runs over the **whole cart at once** and cannot be folded into
 * `priceLine`. A "spend ₹11,000 and take ₹1,000 off" measures across a brand's
 * lines and shares its reward back over them, and a "buy 2 get 1" gives away the
 * cheapest of three pieces that may be on three different rows - neither
 * question can be answered one line at a time.
 */
export function priceCart(
  cart: Cart,
  world: PricingWorld,
  day: string,
  options: PricingOptions = {},
): PricedBill {
  const capPercent = options.capPercent ?? "0.00";
  const rulebook = resolveOffers(offerCart(cart, day), world.offers ?? []);
  const byLine = new Map(rulebook.lines.map((outcome) => [outcome.line_no, outcome]));
  const lines = cart.lines.map((line, index) =>
    priceLine(line, index + 1, world, day, capPercent, byLine.get(index + 1)),
  );

  const gross = lines.reduce((n, l) => n + l.gross_paise, 0);
  const discount = lines.reduce((n, l) => n + l.disc_paise + l.offer_paise, 0);
  const subtotal = lines.reduce((n, l) => n + l.net_paise, 0);
  const round = roundingOf(subtotal);
  const net = subtotal + round;
  const split = splitOf(cart.payment, net, world.creditNotes, day);
  const asks = asksOn(lines, split);

  return {
    lines,
    pieces: lines.reduce((n, l) => n + l.qty, 0),
    gross_paise: gross,
    discount_paise: discount,
    entitlements: rulebook.entitlements,
    subtotal_paise: subtotal,
    round_paise: round,
    net_paise: net,
    // Rounding is not a discount and moves no tax: the GST total is the lines'
    // and nothing else, which is what the accept pipeline re-derives.
    gst_paise: lines.reduce((n, l) => n + l.gst_paise, 0),
    // What staff quote across the counter is everything off the ticket price -
    // the rulebook's part and the cashier's - because that is the number the
    // customer is comparing with the tags in their hand.
    saved_paise: discount,
    split,
    authorisation: cart.authorisation,
    asks,
    needsAuthorising: asks.filter((ask) => !covers(cart.authorisation, [ask])),
  };
}

/** The cart in the rulebook's own terms; line numbers are positions, as ever. */
function offerCart(cart: Cart, day: string): OfferCart {
  return {
    day,
    lines: cart.lines.map((line, index) => ({
      line_no: index + 1,
      brand: line.brand,
      item: line.item,
      design: line.design,
      size: line.size,
      color: line.color,
      barcode: line.barcode,
      season: line.season,
      qty: line.qty,
      mrp_paise: line.mrp_paise,
      no_discount: line.no_discount,
    })),
  };
}

/**
 * Every rule that reduced this line, each with the part *it* took off.
 *
 * The evidence records the winning brand rule by name and the total saving in
 * one field, with the add-ons that stacked on top listed separately. That is the
 * right shape to store - it is what the daily applied-versus-rulebook check
 * reads - and the wrong shape to show a cashier: browser QA found one chip
 * reading "Louis Philippe flat 30% · ₹1,172.17" where ₹1,172.17 was the 30%
 * *and* a storewide 5%, so the counter would have quoted the brand's offer as
 * half again as generous as it is.
 *
 * So the brand rule's own share is what is left after the add-ons, which is
 * arithmetic that cannot be ambiguous: the parts are recorded, and the whole is
 * recorded, so the remainder is the first part.
 */
export function creditsOn(evidence: OfferEvidence | NoOffer): StackedCredit[] {
  if (!("saved_paise" in evidence)) return [];
  const stacked = evidence.stack ?? [];
  const brandShare = evidence.saved_paise - stacked.reduce((n, s) => n + s.saved_paise, 0);
  const credits: StackedCredit[] = [];
  if (evidence.offer_id !== null && brandShare > 0) {
    credits.push({
      offer_id: evidence.offer_id,
      offer_name: evidence.offer_name,
      layer: evidence.layer,
      saved_paise: brandShare,
    });
  }
  return [...credits, ...stacked];
}

/**
 * Everything on this bill a manager has to agree to, one entry per thing.
 *
 * Per line and per note rather than per kind, because that is the granularity a
 * manager actually agrees at: they look at a discount on line 3, or at a note
 * the counter cannot check, and say yes to that. `pin.covers` then holds the
 * cashier to it - a bigger discount on the same line, or a discount on another
 * line, is a thing nobody has looked at and asks again.
 */
function asksOn(lines: PricedLine[], split: TenderSplit): Ask[] {
  const asks: Ask[] = lines
    .filter((line) => line.over_cap)
    .map((line) => ({
      kind: OVER_CAP_DISCOUNT,
      // The line's own key, not its number: a line removed from the middle of a
      // bill renumbers every line under it, and an authorisation that followed
      // the *number* would slide onto a piece nobody approved.
      ref: line.key,
      paise: line.disc_paise,
      label: `Line ${line.line_no}`,
    }));
  for (const standing of split.notes) {
    if (!standing.doubt) continue;
    asks.push({
      kind: UNVERIFIED_NOTE,
      ref: standing.note.number,
      paise: standing.note.amount_paise,
      label: standing.note.number,
    });
  }
  return asks;
}

function priceLine(
  line: CartLine,
  line_no: number,
  world: PricingWorld,
  day: string,
  capPercent: string,
  offer: LineOutcome | undefined,
): PricedLine {
  const gross = line.mrp_paise * line.qty;
  const offerPaise = offer?.discount_paise ?? 0;
  const net = gross - offerPaise - line.disc_paise;
  // A line that cannot be priced still has to render: the screen shows why and
  // refuses to close, rather than throwing on the way to telling anybody.
  const split =
    net > 0 && line.qty > 0
      ? splitLine(net, line.qty, slabFor(world.slabs, line.hsn, day))
      : { rate: "0.00", base_paise: 0, gst_paise: 0 };
  const cap = capFor(line.mrp_paise, line.qty, capPercent);
  const evidence = offer?.evidence ?? {};
  return {
    ...line,
    line_no,
    gross_paise: gross,
    offer_paise: offerPaise,
    offer_id: offer?.offer_id ?? null,
    offer_credits: creditsOn(evidence),
    offer_evidence: evidence,
    net_paise: net,
    gst_rate: split.rate,
    gst_paise: split.gst_paise,
    cap_paise: cap,
    // The cap measures the cashier, so it measures `disc_paise` alone. An offer
    // is head office's decision and was never the counter's to authorise.
    over_cap: line.disc_paise > cap,
  };
}

/**
 * What the bill moves to reach a whole rupee.
 *
 * Integer arithmetic and half-up, matching the shop: 50 paise goes up. The
 * result is always within the ±50 the accept pipeline's serializer allows,
 * which matters because that bound is what stops a rounding line being used to
 * take ₹500 less than the lines say.
 */
export function roundingOf(subtotalPaise: number): number {
  const remainder = ((subtotalPaise % 100) + 100) % 100;
  return remainder >= 50 ? 100 - remainder : -remainder;
}

/** Change out of the drawer. Never negative: cash short of the cash tender is a
 *  bill that does not close, not a negative change. */
export function changeFor(receivedPaise: number, cashPaise: number): number {
  return Math.max(0, receivedPaise - cashPaise);
}

/**
 * Why Save & Print is not available, in a sentence for the counter - or "".
 *
 * Every one of these is a bill the server would refuse. Stopping here is not the
 * screen being fussy: a refused bill halts the whole queue behind it, on a
 * receipt the customer is already holding, so the honest place to catch it is
 * before the number is spent.
 *
 * Note what is *not* here. A count that says nought is not a reason (grill Q6) -
 * the piece is in the customer's hand, so the count was wrong, and the stocktake
 * settles it. Being offline is not a reason either; that is the designed state.
 */
export function whyItCannotClose(bill: PricedBill): string {
  if (!bill.lines.length) return "Nothing on this bill yet. Scan a piece to start.";

  const unpriced = bill.lines.find((line) => line.mrp_paise <= 0);
  if (unpriced) {
    return `Line ${unpriced.line_no} has no price. Type the price from the tag before saving.`;
  }
  // `LINE_UNRESOLVED` (422) on the server, and a terminal one: a barcode the
  // books cannot place and no words to say what it was is a bill the queue would
  // halt on, taking every bill behind it - after the customer had paid and walked
  // out with the receipt. The counter has to say what it sold (#186).
  const undescribed = bill.lines.find((line) => line.sold_before_inward && !line.manual_desc.trim());
  if (undescribed) {
    return (
      `Line ${undescribed.line_no} is not in the system. ` +
      "Type what the garment is before saving."
    );
  }
  const negative = bill.lines.find((line) => line.net_paise < 0);
  if (negative) {
    return `Line ${negative.line_no} is discounted by more than it costs.`;
  }
  const discount = bill.needsAuthorising.find((ask) => ask.kind === OVER_CAP_DISCOUNT);
  if (discount) {
    return (
      `${discount.label} discounts more than a cashier may on their own. ` +
      "A manager of this store has to approve it."
    );
  }
  // Found in browser QA of #185, and it is #181's rule rather than that ticket's:
  // `_resolve_line` refuses a line with no salesman on it, and the counter was
  // letting one through. The bill printed, the customer paid, and the queue then
  // halted on a `VALIDATION` that no amount of retrying could clear - taking
  // every bill behind it with it, because the queue does not reorder itself to
  // get past a bill the server refuses. A per-line salesman is locked in D10, so
  // this is a question the screen has to ask before the number is spent.
  const unattributed = bill.lines.find((line) => line.salesman == null);
  if (unattributed) {
    return `Line ${unattributed.line_no} has no salesman. Pick who sold the piece.`;
  }
  const notesCovered = !bill.needsAuthorising.some((ask) => ask.kind === UNVERIFIED_NOTE);
  return whyPaymentCannotClose(bill.split, notesCovered, bill.net_paise);
}

export interface BillIdentity {
  billedAt: string;
  /** Partial rather than a whole `TillCustomer`: the screen hands over whatever
   *  the strip has, and `toDraft` is what fills the three fields in. */
  customer?: Partial<TillCustomer>;
  /** The shop's own state (`storeStateCodeOf(world.store)`), or null when the
   *  counter has no identity yet.
   *
   *  Null is not "some other state" and must not be read as one - see `toDraft`,
   *  which refuses to raise a tax invoice it cannot put a tax on. */
  storeStateCode?: string | null;
}

/**
 * The bill as the till layer takes it: everything but its number.
 *
 * The tenders are what each mode **took**, not what the customer held out. What
 * goes into the drawer and what they are owed back are the counter's business;
 * what posts to CASH is what the sale was worth, and a bill that tendered ₹2,000
 * for a ₹1,499 sale would refuse to balance and would be ₹501 out if it did.
 *
 * The manager's authorisation rides along as the contract's `override`, naming
 * who and when. Only an authorisation that actually covers what the bill needs
 * is sent: one obtained for a credit note, on a bill that has since grown an
 * over-cap discount, is a manager's name on something they never saw - and
 * `whyItCannotClose` has already stopped that bill from getting here.
 */
export function toDraft(bill: PricedBill, identity: BillIdentity): BillDraft {
  const lines: BillLine[] = bill.lines.map((line) => ({
    line_no: line.line_no,
    direction: "sale",
    barcode: line.barcode,
    season: line.season,
    qty: line.qty,
    mrp_paise: line.mrp_paise,
    // The wire carries one discount per line, because that is what the bill
    // says and what the customer paid. Which part of it the rulebook is
    // answerable for is a separate question, and the server answers it by
    // re-resolving the cart itself - the evidence below is what the daily check
    // audits, never what the cap believes.
    disc_paise: line.offer_paise + line.disc_paise,
    net_paise: line.net_paise,
    gst_rate: line.gst_rate,
    gst_paise: line.gst_paise,
    salesman: line.salesman,
    offer_id: line.offer_id,
    offer_evidence: line.offer_evidence,
    // What the cashier typed for a piece nothing could place. Sent on every line
    // for one field's worth of noise and one fewer branch: the server reads it
    // only when the barcode resolves to nothing, which is exactly when it is set.
    manual_desc: line.manual_desc,
  }));
  // Normalised here rather than at the field, so what prints on the paper, what
  // the split was derived from, and what the server stores are one string.
  //
  // **A counter that does not know its own state does not raise a tax invoice.**
  // The split is derived from the buyer's state against the shop's, so with no
  // shop state there is no honest answer - and the two dishonest ones are both
  // worse than dropping the registration: printing IGST because the comparison
  // failed would put one tax on the customer's copy and another in the books,
  // and printing CGST + SGST would do the same the other way round. Without it
  // the bill is an ordinary retail sale, which is recoverable; a tax invoice
  // charging the wrong tax is not. The screen keeps the field disabled in this
  // state, so this is the backstop for a hold parked before the counter lost its
  // identity rather than something a cashier can walk into.
  const storeState = identity.storeStateCode || null;
  const gstin = storeState ? normaliseGstin(identity.customer?.gstin ?? "") : "";
  return {
    billed_at: identity.billedAt,
    customer: {
      name: identity.customer?.name ?? "",
      mobile: identity.customer?.mobile ?? "",
      gstin,
    },
    // What the *customer's copy* says the tax split is. The server derives its
    // own from the same GSTIN and flags a disagreement rather than silently
    // preferring one (contract step 11) - which only works if the till says what
    // it printed, so this rides on every bill including the B2C ones, where it
    // is "none".
    b2b_tax_kind: taxKindFor(gstin, storeState ?? ""),
    lines,
    tenders: toTenders(bill.split),
    totals: {
      gross_paise: bill.gross_paise,
      discount_paise: bill.discount_paise,
      net_paise: bill.net_paise,
      gst_paise: bill.gst_paise,
      round_paise: bill.round_paise,
    },
    ...(bill.authorisation && bill.asks.length
      ? {
          override: {
            user_id: bill.authorisation.user_id,
            // A bill can need two things authorised at once, and the contract
            // has one `kind` for them. They are joined with `+` in one fixed
            // order - "over_cap_discount+credit_note" - so what is stored is
            // always the same word for the same pair, and a check grouping on it
            // never sees two spellings. The server takes those four values and
            // no others.
            kind: kindsOf(bill.asks).join("+"),
            at: bill.authorisation.at,
          },
        }
      : {}),
  };
}
