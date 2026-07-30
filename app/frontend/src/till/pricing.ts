// MRP-inclusive tax arithmetic at the counter (#180, D10 step 3).
//
// The TypeScript mirror of `sell/pricing.py`, and it exists because the till
// prices a scan with no network: the price tag is GST-inclusive, so the counter
// works backwards from what the customer pays to the tax already sitting inside
// it.
//
// Two rules, both from `CONTEXT.md`, both easy to get subtly wrong:
//
// **Which slab.** 5% at or under ₹2,500 per piece and 18% above, decided on the
// GST-*exclusive*, post-discount, per-piece price. That looks circular - the base
// depends on the rate and the rate on the base - and resolves because the mapping
// is monotone: price the piece at the lower rate first, and if the base that
// produces is still inside the threshold, the lower rate is the right one.
//
// **Where the half-paisa goes.** The base is rounded half-up and the tax is the
// remainder, never rounded on its own, so base + tax is exactly what the customer
// handed over on every line.
//
// All of it in integers. A rate arrives as a two-decimal string ("5.00") and is
// carried as hundredths of a percent, so nothing here ever touches a float - a
// bill that came out a paise different from the server's recomputation would
// raise a `gst_mismatch` flag every single time.

import type { TillGstSlab } from "./types";

/** ₹2,500 a piece, as the fallback when no slab has reached the device yet. */
const FALLBACK_SLAB: TillGstSlab = {
  hsn_prefix: "",
  threshold_paise: 250000,
  rate_below: "5.00",
  rate_above: "18.00",
  effective_from: "2025-09-22",
};

export interface TaxSplit {
  /** The rate applied, in the two-decimal form the bill and the server quote. */
  rate: string;
  base_paise: number;
  gst_paise: number;
}

/** A two-decimal percentage as hundredths of a percent: "5.00" → 500. */
export function rateHundredths(rate: string): number {
  const [whole, fraction = ""] = rate.trim().split(".");
  return Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
}

/** The GST-exclusive base inside a tax-inclusive amount, rounded half-up.
 *
 *  Integer arithmetic throughout: `x * 100 / (100 + rate)` in floating point is
 *  a paise adrift often enough to matter across a day's bills. */
export function baseFromInclusive(inclusivePaise: number, rate: string): number {
  const denominator = 10_000 + rateHundredths(rate);
  const numerator = inclusivePaise * 10_000;
  return Math.floor((2 * numerator + denominator) / (2 * denominator));
}

/** Split a tax-inclusive amount at a known rate. The tax is the remainder. */
export function splitInclusive(inclusivePaise: number, rate: string): TaxSplit {
  const base = baseFromInclusive(inclusivePaise, rate);
  return { rate, base_paise: base, gst_paise: inclusivePaise - base };
}

/**
 * Split a whole line, choosing the slab from its per-piece exclusive price.
 *
 * `qty` matters because the threshold is per piece: two ₹2,000 shirts on one line
 * are two 5% pieces, not one 18% line.
 */
export function splitLine(inclusivePaise: number, qty: number, slab: TillGstSlab): TaxSplit {
  if (qty <= 0) throw new Error("a line must carry a positive quantity to be priced");
  // The per-piece base in one step. Dividing by `qty` first and rounding, then
  // taking the tax out of that, rounds twice - and the second rounding can push a
  // piece across the ₹2,500 boundary the server would have left below it.
  const denominator = qty * (10_000 + rateHundredths(slab.rate_below));
  const baseAtLow = Math.floor((2 * inclusivePaise * 10_000 + denominator) / (2 * denominator));
  const rate = baseAtLow <= slab.threshold_paise ? slab.rate_below : slab.rate_above;
  return splitInclusive(inclusivePaise, rate);
}

/**
 * The slab in force on `when`, preferring the row written for this HSN.
 *
 * Date-effective by construction (Rule 11): a bill is taxed by the slab that was
 * live on the day it was billed, and the dataset deliberately ships slabs whose
 * date has not arrived so an offline counter reaches October's rate in October.
 *
 * Where this and the server could disagree: two slabs sharing an
 * `effective_from` and both matching the HSN. The server's ordering does not
 * break that tie, so this takes the longer prefix - the more specific rule - and
 * the daily applied-versus-rulebook check would catch it if head office ever
 * wrote such a pair.
 */
export function slabFor(slabs: TillGstSlab[], hsn: string, when: string): TillGstSlab {
  const live = slabs
    .filter((s) => s.effective_from <= when)
    .sort(
      (a, b) =>
        b.effective_from.localeCompare(a.effective_from) ||
        b.hsn_prefix.length - a.hsn_prefix.length,
    );
  return (
    live.find((s) => s.hsn_prefix && hsn && hsn.startsWith(s.hsn_prefix)) ??
    live.find((s) => !s.hsn_prefix) ??
    live[0] ??
    FALLBACK_SLAB
  );
}
