// The footer's tax breakup (#247, grill Q7).
//
// One property carries this file: **the rows add up to the figure they opened
// from.** A cashier clicks "Tax included ₹1,240" and gets a panel; if the panel's
// own rows came to anything else, the screen would be arguing with itself in
// front of a customer, and the cashier would have no way to know which half was
// right. So every case here asserts the sum as well as the shape.
//
// Bills are priced through `priceCart` rather than hand-built, so the fixtures
// carry the real slab arithmetic - a breakup that agreed with a made-up bill and
// disagreed with a real one would pass a test and fail a counter.

import { describe, expect, it } from "vitest";

import { addManualPiece, addPiece, emptyCart, priceCart } from "./cart";
import type { Cart } from "./cart";
import { legFor } from "./exchange";
import type { Exchange, OriginalLine } from "./exchange";
import { ratePercent, taxBreakup, taxLabel } from "./tax";
import { item, season } from "./testSupport";
import type { TillGstSlab } from "./types";

/** 5% at or under ₹2,500 a piece, 18% above - CONTEXT.md's apparel slab. */
const SLAB: TillGstSlab = {
  hsn_prefix: "",
  threshold_paise: 250000,
  rate_below: "5.00",
  rate_above: "18.00",
  effective_from: "2020-01-01",
};

const WORLD = { seasons: [season("FW25", 2)], slabs: [SLAB], offers: [] };

function scanned(barcode: string, mrp: number | null, over: Partial<Cart["lines"][number]> = {}) {
  return {
    ...addPiece(item(barcode, "FW25", mrp), { stock: 3, alternatives: [] }),
    salesman: 1,
    ...over,
  };
}

function priced(lines: Cart["lines"], exchange: Exchange | null = null) {
  return priceCart({ ...emptyCart(), lines, exchange }, WORLD, "2026-07-30");
}

/** One line of an old bill, as the Return & Exchange screen read it back. */
function sold(over: Partial<OriginalLine> = {}): OriginalLine {
  return {
    line_no: 1,
    barcode: "8901000000011",
    season: "FW25",
    design: "SHIRT-01",
    color: "NAVY",
    size: "M",
    brand: "MUFTI",
    item: "Shirt",
    hsn: "6205",
    qty: 1,
    net_paise: 120000,
    gst_rate: "5.00",
    gst_paise: 5714,
    manual_desc: "",
    direction: "sale",
    returned_qty: 0,
    returned_paise: 0,
    ...over,
  };
}

function exchangeOf(...lines: OriginalLine[]): Exchange {
  return {
    original: { fy: "26-27", till_seq: 40, doc_number: "26-27/DEO/SAL/40" },
    lines: lines.map((line, index) => legFor(line, 1, `x${index + 1}`)),
  };
}

const summed = (rows: { gst_paise: number }[]) => rows.reduce((n, r) => n + r.gst_paise, 0);

describe("the per-rate rows", () => {
  it("gathers the lines that share a slab into one row", () => {
    // Two ₹1,499 shirts and a ₹4,999 jacket: 5%, 5%, 18%.
    const bill = priced([scanned("8901", 149900), scanned("8902", 149900), scanned("8903", 499900)]);
    const { rows } = taxBreakup(bill, "none");

    expect(rows.map((r) => r.rate)).toEqual(["5.00", "18.00"]);
    expect(rows[0].taxable_paise + rows[0].gst_paise).toBe(299800);
    expect(rows[1].taxable_paise + rows[1].gst_paise).toBe(499900);
  });

  it("adds up to the figure in the footer", () => {
    const bill = priced([scanned("8901", 149900), scanned("8903", 499900)]);
    const breakup = taxBreakup(bill, "none");

    expect(summed(breakup.rows)).toBe(breakup.shown_paise);
    expect(breakup.shown_paise).toBe(bill.gst_paise);
  });

  it("puts the lowest rate first, whatever order the pieces were scanned in", () => {
    const bill = priced([scanned("8903", 499900), scanned("8901", 149900)]);

    expect(taxBreakup(bill, "none").rows.map((r) => r.rate)).toEqual(["5.00", "18.00"]);
  });

  it("leaves out a line nothing has priced yet, rather than calling it exempt", () => {
    // An off-the-tag piece (#186) before anybody keys the price in: rate "0.00"
    // and no tax, because there is nothing yet to tax - not because a garment is
    // zero-rated.
    const bill = priced([{ ...addManualPiece("9999"), salesman: 1 }]);
    const { rows, shown_paise } = taxBreakup(bill, "none");

    expect(rows).toEqual([]);
    expect(shown_paise).toBe(0);
  });

  it("leaves out a line discounted past its own price, for the same reason", () => {
    // `priceLine` gives any line with a net of nought or less rate "0.00" - so a
    // piece given away, or discounted below zero, would otherwise show a "0%"
    // row with a negative base under it. It has no slab; it has a mistake.
    const bill = priced([scanned("8901", 100000, { disc_paise: 150000 })]);

    expect(taxBreakup(bill, "none").rows).toEqual([]);
  });
});

describe("a piece coming back on the same bill", () => {
  it("nets the returned tax off its own slab's row", () => {
    const bill = priced([scanned("8901", 149900)], exchangeOf(sold()));
    const breakup = taxBreakup(bill, "none");

    expect(breakup.rows.map((r) => r.rate)).toEqual(["5.00"]);
    expect(summed(breakup.rows)).toBe(breakup.shown_paise);
    // The sold piece's tax less the returned piece's, which is what the footer
    // shows and what `accept._check_totals` re-derives.
    expect(breakup.rows[0].gst_paise).toBe(bill.lines[0].gst_paise - 5714);
  });

  it("still adds up when what came back was taxed at the other slab", () => {
    const bill = priced(
      [scanned("8901", 149900)],
      exchangeOf(sold({ net_paise: 499900, gst_rate: "18.00", gst_paise: 76256 })),
    );
    const breakup = taxBreakup(bill, "none");

    expect(breakup.rows.map((r) => r.rate)).toEqual(["5.00", "18.00"]);
    expect(summed(breakup.rows)).toBe(breakup.shown_paise);
  });

  it("states the direction in words and the figures as amounts, like the paper", () => {
    // A return worth more than what replaced it: the whole bill is giving tax
    // back. `receipt.ts` prints "Tax given back ₹712", never "Tax included
    // −₹712", and this panel has to read the same way or the counter and the
    // customer's copy are two stories.
    const bill = priced(
      [scanned("8901", 100000)],
      exchangeOf(sold({ net_paise: 499900, gst_rate: "18.00", gst_paise: 76256 })),
    );
    const breakup = taxBreakup(bill, "igst");

    expect(bill.gst_paise).toBeLessThan(0);
    expect(breakup.given_back).toBe(true);
    expect(breakup.shown_paise).toBe(Math.abs(bill.gst_paise));
    expect(breakup.split).toEqual([{ label: "IGST", paise: breakup.shown_paise }]);
    // And the rows turn with it, so the panel still adds up to its own heading:
    // the 18% slab is what is going back, the 5% slab is still being charged and
    // shows as the negative it is against that direction.
    expect(summed(breakup.rows)).toBe(breakup.shown_paise);
    expect(breakup.rows.find((r) => r.rate === "18.00")?.gst_paise).toBeGreaterThan(0);
    expect(breakup.rows.find((r) => r.rate === "5.00")?.gst_paise).toBeLessThan(0);
  });
});

describe("the two words on the figure", () => {
  it("reads the way the customer's copy does", () => {
    expect(taxLabel(7138)).toBe("Tax included");
    expect(taxLabel(0)).toBe("Tax included");
    expect(taxLabel(-7138)).toBe("Tax given back");
  });
});

describe("the split the customer's copy carries", () => {
  const bill = priced([scanned("8901", 149900)]);

  it("halves an in-state bill into CGST and SGST, to the paise", () => {
    const { split } = taxBreakup(bill, "cgst_sgst");

    expect(split.map((s) => s.label)).toEqual(["CGST", "SGST"]);
    expect(split[0].paise + split[1].paise).toBe(bill.gst_paise);
  });

  it("shows one IGST head when the buyer is out of state", () => {
    expect(taxBreakup(bill, "igst").split).toEqual([{ label: "IGST", paise: bill.gst_paise }]);
  });

  it("shows no split at all on a retail bill, exactly as the receipt prints it", () => {
    const breakup = taxBreakup(bill, "none");

    expect(breakup.split).toEqual([]);
    expect(summed(breakup.rows)).toBe(breakup.shown_paise);
  });
});

describe("the badge on the line", () => {
  it("drops the two-decimal form the wire uses", () => {
    expect(ratePercent("5.00")).toBe("5%");
    expect(ratePercent("18.00")).toBe("18%");
  });

  it("keeps a rate that really has a fraction", () => {
    // A slab shown as "12%" when the bill charged 12.5% is worse than a wide
    // badge - the badge exists to catch a wrong slab at a glance.
    expect(ratePercent("12.50")).toBe("12.5%");
  });
});
