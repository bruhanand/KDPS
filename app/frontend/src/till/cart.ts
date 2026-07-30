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
// Two things this file deliberately does not do. It applies no offer - the
// rulebook is #183, and a discount here is a *manual* one the cashier keyed in,
// which is why it is the thing the cap measures. And it never invents a price:
// a piece the books have no MRP for arrives as `null` (contract, step 3) and
// stops the bill until a human types the price off the tag, because a nought
// would post no revenue and no tax against a garment that left the shop.

import { rateHundredths, slabFor, splitLine } from "./pricing";
import type { BillDraft, BillLine, TillGstSlab, TillItem, TillSeason } from "./types";

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
}

export interface Cart {
  lines: CartLine[];
  /** Cash the customer held out. Presentation only: what is *tendered* on the
   *  bill is the bill, and the difference is change out of the drawer. */
  tenderedPaise: number;
}

export interface PricedLine extends CartLine {
  line_no: number;
  gross_paise: number;
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
  /** What the lines come to before the bill is rounded. */
  subtotal_paise: number;
  round_paise: number;
  net_paise: number;
  gst_paise: number;
  /** The figure staff quote to the customer. */
  saved_paise: number;
  tenderedPaise: number;
  changePaise: number;
}

export interface PricingWorld {
  seasons: TillSeason[];
  slabs: TillGstSlab[];
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

/** Price the whole cart: every line, then the bill, then the change. */
export function priceCart(
  cart: Cart,
  world: PricingWorld,
  day: string,
  options: PricingOptions = {},
): PricedBill {
  const capPercent = options.capPercent ?? "0.00";
  const lines = cart.lines.map((line, index) => priceLine(line, index + 1, world, day, capPercent));

  const gross = lines.reduce((n, l) => n + l.gross_paise, 0);
  const discount = lines.reduce((n, l) => n + l.disc_paise, 0);
  const subtotal = lines.reduce((n, l) => n + l.net_paise, 0);
  const round = roundingOf(subtotal);
  const net = subtotal + round;

  return {
    lines,
    pieces: lines.reduce((n, l) => n + l.qty, 0),
    gross_paise: gross,
    discount_paise: discount,
    subtotal_paise: subtotal,
    round_paise: round,
    net_paise: net,
    // Rounding is not a discount and moves no tax: the GST total is the lines'
    // and nothing else, which is what the accept pipeline re-derives.
    gst_paise: lines.reduce((n, l) => n + l.gst_paise, 0),
    saved_paise: discount,
    tenderedPaise: cart.tenderedPaise,
    changePaise: changeFor(cart.tenderedPaise, net),
  };
}

function priceLine(
  line: CartLine,
  line_no: number,
  world: PricingWorld,
  day: string,
  capPercent: string,
): PricedLine {
  const gross = line.mrp_paise * line.qty;
  const net = gross - line.disc_paise;
  // A line that cannot be priced still has to render: the screen shows why and
  // refuses to close, rather than throwing on the way to telling anybody.
  const split =
    net > 0 && line.qty > 0
      ? splitLine(net, line.qty, slabFor(world.slabs, line.hsn, day))
      : { rate: "0.00", base_paise: 0, gst_paise: 0 };
  const cap = capFor(line.mrp_paise, line.qty, capPercent);
  return {
    ...line,
    line_no,
    gross_paise: gross,
    net_paise: net,
    gst_rate: split.rate,
    gst_paise: split.gst_paise,
    cap_paise: cap,
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

/** Change out of the drawer. Never negative: cash short of the bill is a bill
 *  that does not close, not a negative change. */
export function changeFor(tenderedPaise: number, netPaise: number): number {
  return Math.max(0, tenderedPaise - netPaise);
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
  const negative = bill.lines.find((line) => line.net_paise < 0);
  if (negative) {
    return `Line ${negative.line_no} is discounted by more than it costs.`;
  }
  const overCap = bill.lines.find((line) => line.over_cap);
  if (overCap) {
    return (
      `Line ${overCap.line_no} discounts more than a cashier may on their own. ` +
      "A manager of this store has to approve it."
    );
  }
  if (bill.tenderedPaise < bill.net_paise) {
    return "The cash taken is less than the bill.";
  }
  return "";
}

export interface BillIdentity {
  billedAt: string;
  customer?: { name?: string; mobile?: string; gstin?: string };
}

/**
 * The bill as the till layer takes it: everything but its number.
 *
 * The tender is the **bill**, not the cash the customer held out. What goes into
 * the drawer and what the customer is owed back are the counter's business; what
 * posts to CASH is what the sale was worth, and a bill that tendered ₹2,000 for
 * a ₹1,499 sale would refuse to balance and would be ₹501 out if it did.
 */
export function toDraft(bill: PricedBill, identity: BillIdentity): BillDraft {
  const lines: BillLine[] = bill.lines.map((line) => ({
    line_no: line.line_no,
    direction: "sale",
    barcode: line.barcode,
    season: line.season,
    qty: line.qty,
    mrp_paise: line.mrp_paise,
    disc_paise: line.disc_paise,
    net_paise: line.net_paise,
    gst_rate: line.gst_rate,
    gst_paise: line.gst_paise,
    salesman: line.salesman,
    // No offer claimed, deliberately: the rulebook is #183, and a discount on
    // this bill is one a person keyed in. Evidence the till cannot stand behind
    // would be evidence the cap has to ignore anyway (`_rulebook_saving`).
    offer_evidence: {},
  }));
  return {
    billed_at: identity.billedAt,
    customer: {
      name: identity.customer?.name ?? "",
      mobile: identity.customer?.mobile ?? "",
      gstin: identity.customer?.gstin ?? "",
    },
    lines,
    tenders: [{ mode: "cash", amount_paise: bill.net_paise }],
    totals: {
      gross_paise: bill.gross_paise,
      discount_paise: bill.discount_paise,
      net_paise: bill.net_paise,
      gst_paise: bill.gst_paise,
      round_paise: bill.round_paise,
    },
  };
}
