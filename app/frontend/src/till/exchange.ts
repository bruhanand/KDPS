// A piece coming back inside the bill in front of you (#184, D2).
//
// The counter's half of the exchange. The other flow on the Return & Exchange
// screen - a plain return, with nothing bought in its place - is a server call
// and has no arithmetic here at all; this one is a *bill*, so every figure on it
// has to be worked out offline and then survive the server checking it to the
// paisa (`accept._check_return_refund`).
//
// Two rules carry the whole file, and both are the server's rather than this
// screen's:
//
// **What comes back is what was paid** (D2), never today's price. A piece bought
// under a 30% offer comes back at what the customer actually handed over for it,
// which is the line's net divided by its pieces - and the *last* piece of a line
// settles the remainder of what has not yet been given back, so three pieces at
// ₹9.99 refund 333 + 333 + 334 rather than leaving a paisa in the books for ever.
// That is why an original line has to carry `returned_paise` as well as
// `returned_qty`: without the paise a second partial return is a paisa out, and
// the bill is refused after the receipt has printed.
//
// **The tax inside the refund is the tax the bill charged**, at the rate on the
// original line - not today's slab. A rate change between the sale and the
// exchange has nothing to do with what is being given back, and re-deriving it
// would leave the reversal a few paise away from the posting it unwinds.
//
// The parking pair at the bottom is the one piece of plumbing. Each Sell route
// mounts its own `TillProvider`, so handing picked lines from one screen to the
// other cannot go through React state - and a customer's exchange is a fact the
// counter is holding, not a component's business. It goes in `meta`, survives a
// reload, and is taken exactly once.

import { META, readMeta, writeMeta } from "./db";
import type { TillDb } from "./db";
import { splitInclusive } from "./pricing";

/** The bill an exchange gives back against, as the counter found it. */
export interface ExchangeOriginal {
  fy: string;
  till_seq: number;
  /** For the screen and the receipt. The server resolves the bill from the pair
   *  above, so this is what a person reads, never what anything looks up by. */
  doc_number: string;
}

/** One line of the original bill, as it stands now. The shape of
 *  `SaleLineReadSerializer`, narrowed to what an exchange actually needs. */
export interface OriginalLine {
  line_no: number;
  barcode: string;
  season: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  item: string;
  hsn: string;
  qty: number;
  net_paise: number;
  gst_rate: string;
  gst_paise: number;
  manual_desc: string;
  direction: string;
  returned_qty: number;
  returned_paise: number;
}

/** One piece being given back on the bill in front of the cashier. */
export interface ExchangeLeg {
  /** Stable across re-prices, like a cart line's. */
  key: string;
  original_line: number;
  barcode: string;
  season: string;
  brand: string;
  item: string;
  design: string;
  size: string;
  qty: number;
  refund_paise: number;
  gst_rate: string;
  gst_paise: number;
  reason: string;
  condition: "good" | "damaged";
  /** How the piece reads on the screen and on the receipt - the books' words for
   *  it, or the cashier's where the line was billed off a tag (#186). */
  description: string;
}

/** The whole exchange riding on a bill: which original, and which of its lines. */
export interface Exchange {
  original: ExchangeOriginal;
  lines: ExchangeLeg[];
}

let legKeys = 0;

/** How much of a line is still returnable. */
export function returnableQty(line: OriginalLine): number {
  return Math.max(0, line.qty - line.returned_qty);
}

/**
 * What `qty` pieces of a sold line are worth back, in whole paise (D2).
 *
 * The mirror of `sell.services.refunds.entitled_refund`, and it has to agree with
 * it exactly: the server recomputes this figure and refuses the bill outright
 * where the two differ, on a receipt that is already in a customer's hand.
 *
 * Two rules, and the second is the one that is easy to miss.
 *
 * A share is rounded **half-up**, in integers. `Math.round` happens to round
 * half-up for positive numbers, but it does it on a float - and the point of the
 * integer form is that it cannot be a paisa adrift on some bill nobody thought
 * about, which is what `pricing.ts` says about every other figure here.
 *
 * The **last** piece of a line settles the remainder of what has not been given
 * back, so the parts always sum to what the customer actually paid.
 */
export function refundFor(line: OriginalLine, qty: number): number {
  const paid = line.net_paise;
  if (line.returned_qty + qty >= line.qty) return paid - line.returned_paise;
  return Math.floor((2 * paid * qty + line.qty) / (2 * line.qty));
}

/** A line of the original bill as a leg on the bill being rung up now. */
export function legFor(line: OriginalLine, qty: number, key = newLegKey()): ExchangeLeg {
  const refund = refundFor(line, qty);
  return {
    key,
    original_line: line.line_no,
    barcode: line.barcode,
    season: line.season,
    brand: line.brand,
    item: line.item,
    design: line.design,
    size: line.size,
    qty,
    refund_paise: refund,
    gst_rate: line.gst_rate,
    // The rate the bill charged, out of the refund - see the module note. The
    // server checks exactly this identity (`_check_line_arithmetic`).
    gst_paise: splitInclusive(refund, line.gst_rate).gst_paise,
    reason: "",
    condition: "good",
    description: describeOriginal(line),
  };
}

/** How a returned piece reads: the books' words, or the cashier's off the tag. */
export function describeOriginal(line: OriginalLine): string {
  const words = [line.brand, line.item, line.design, line.size].filter(Boolean).join(" · ");
  return words || line.manual_desc.trim() || line.barcode;
}

function newLegKey(): string {
  return `x${(legKeys += 1)}`;
}

/** What the whole exchange gives back, and the tax inside it. */
export function refundTotals(legs: ExchangeLeg[]): { refund_paise: number; gst_paise: number } {
  return {
    refund_paise: legs.reduce((n, leg) => n + leg.refund_paise, 0),
    gst_paise: legs.reduce((n, leg) => n + leg.gst_paise, 0),
  };
}

/** Whether this bill can close with these legs on it - or why not.
 *
 *  Only the counter's own refusals; what the *bill* still needs is
 *  `cart.whyItCannotClose`, which calls this. */
export function whyExchangeCannotClose(exchange: Exchange | null): string {
  if (!exchange) return "";
  if (!exchange.lines.length) {
    return "No piece is being given back. Take the exchange off the bill, or pick a line.";
  }
  const unpriced = exchange.lines.find((leg) => leg.refund_paise <= 0);
  if (unpriced) {
    return `${unpriced.description} was billed at nothing, so there is nothing to give back for it.`;
  }
  return "";
}

// --- parking one between two screens ---------------------------------------

/**
 * Put a picked exchange down for the Billing screen to pick up.
 *
 * A hand-off through the database rather than through React, because there is no
 * shared React to hand it through: `TillProvider` mounts per Sell route, so
 * walking from Return & Exchange to Billing is a fresh provider and a fresh
 * component tree. It also means the customer's exchange survives a reload with
 * them standing there, which a router-state hand-off would not.
 */
export async function parkExchange(db: TillDb, exchange: Exchange): Promise<void> {
  await writeMeta(db, META.exchange, exchange);
}

/**
 * Take the parked exchange, exactly once.
 *
 * Cleared as it is read, and that is the whole of it: a hand-off left lying
 * around would put the same customer's returned shirt on the *next* customer's
 * bill, which is a refund nobody asked for and a piece back on the shelf twice.
 */
export async function takeParkedExchange(db: TillDb): Promise<Exchange | null> {
  const parked = await readMeta<Exchange | null>(db, META.exchange, null);
  if (parked) await writeMeta(db, META.exchange, null);
  return parked;
}
