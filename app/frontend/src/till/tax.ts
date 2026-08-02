// The bill's tax, gathered the way a person asks about it (#247, grill Q7).
//
// The grid used to carry the rate and the rupees on every single line, which is
// twelve numbers nobody reads to answer the one question anybody ever asks -
// "why is the tax that much?" - and eight per cent of the width of a counter
// screen. Q7's ruling collapses that to a badge per line and puts the whole
// answer behind the figure in the footer.
//
// Nothing here computes tax. Every paise comes from `priceCart`, which is the
// same arithmetic the receipt prints and the server re-derives; this only groups
// what is already on the bill. That is the property the popover stands on: the
// rows add up to exactly the figure they opened from, so a breakup can never
// tell a cashier a different story from the total beside it.
//
// The returned pieces come out rather than being listed apart, for the same
// reason `priceCart` nets them off the total: what the customer is being taxed
// today is the difference, and a breakup that showed the sold side alone would
// not add up to the footer's figure on any exchange.

import type { PricedBill } from "./cart";
import { splitTax } from "./gstin";
import type { B2bTaxKind } from "./gstin";

/** One slab's share of the bill. `taxable_paise` is the GST-exclusive base -
 *  what the return itself calls taxable value - and is what makes a wrong slab
 *  obvious: the rate and the base are the two halves of the arithmetic. */
export interface TaxRateRow {
  /** As the bill and the server quote it: "5.00", "18.00". */
  rate: string;
  taxable_paise: number;
  gst_paise: number;
}

export interface TaxBreakup {
  rows: TaxRateRow[];
  /** CGST + SGST, or IGST, or nothing at all on a bill that is not a tax
   *  invoice - exactly the rows the customer's copy carries (`receipt.ts`). */
  split: { label: string; paise: number }[];
  /** The footer's own figure, and what the rows sum to. */
  gst_paise: number;
  /** The bill gives more tax back than it charges - an exchange worth more than
   *  what replaced it. The receipt calls that "Tax given back"; so does this. */
  given_back: boolean;
}

/**
 * The whole bill's tax, by slab and by head.
 *
 * Rates are strings on purpose (ADR-0004: nothing on the money path touches a
 * float), so they group by string equality - "5.00" and "5.0" would be two rows,
 * and cannot be: one slab row produces one spelling, and it is the spelling that
 * goes on the wire.
 */
export function taxBreakup(bill: PricedBill, kind: B2bTaxKind): TaxBreakup {
  const byRate = new Map<string, TaxRateRow>();
  const add = (rate: string, taxable: number, gst: number): void => {
    const row = byRate.get(rate) ?? { rate, taxable_paise: 0, gst_paise: 0 };
    row.taxable_paise += taxable;
    row.gst_paise += gst;
    byRate.set(rate, row);
  };

  for (const line of bill.lines) {
    add(line.gst_rate, line.net_paise - line.gst_paise, line.gst_paise);
  }
  for (const leg of bill.exchange?.lines ?? []) {
    add(leg.gst_rate, -(leg.refund_paise - leg.gst_paise), -leg.gst_paise);
  }

  const rows = [...byRate.values()]
    // A line nothing could price yet carries rate "0.00" and no tax at all
    // (`priceLine`). It is a real line and it is on the screen, but it has no
    // slab to report under, and a "0%" row would read as "this piece is exempt".
    .filter((row) => row.gst_paise !== 0 || row.taxable_paise !== 0)
    .sort((a, b) => Number(a.rate) - Number(b.rate));

  return {
    rows,
    // `Math.abs`, as `receipt.ts` does: the two heads of a refunded tax are still
    // CGST and SGST, and a negative half apiece is not how either paper or the
    // books say it.
    split: splitTax(Math.abs(bill.gst_paise), kind),
    gst_paise: bill.gst_paise,
    given_back: bill.gst_paise < 0,
  };
}

/**
 * A rate as a badge wears it: "5.00" → "5%", "18.00" → "18%".
 *
 * The two-decimal form is what the wire and the server speak, and it is the
 * wrong thing to print twelve times down a counter screen - Q7 asked for a
 * *quiet* badge, and "5.00%" is not quiet. Trailing zeroes only: a rate that
 * ever carried a real fraction would keep it, because a slab shown as "12%" when
 * the bill charged 12.5% is worse than a wide badge.
 */
export function ratePercent(rate: string): string {
  const trimmed = rate.includes(".") ? rate.replace(/0+$/, "").replace(/\.$/, "") : rate;
  return `${trimmed}%`;
}
