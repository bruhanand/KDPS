// MRP-inclusive tax at the counter (#180).
//
// The property under test is not "does it compute a tax" - it is "does it compute
// the same tax the server does". The server recomputes every bill it accepts and
// raises a `gst_mismatch` flag on a disagreement, so a till that is a paise out
// flags every single sale and the daily check becomes noise.
//
// The expectations below are the arithmetic in `sell/pricing.py`, worked by hand:
// base = round-half-up(inclusive x 100 / (100 + rate)), tax = the remainder.

import { describe, expect, it } from "vitest";

import { baseFromInclusive, rateHundredths, slabFor, splitInclusive, splitLine } from "./pricing";
import type { TillGstSlab } from "./types";

const APPAREL: TillGstSlab = {
  hsn_prefix: "",
  threshold_paise: 250000,
  rate_below: "5.00",
  rate_above: "18.00",
  effective_from: "2025-09-22",
};

describe("taking the tax out of a price tag", () => {
  it("reads a two-decimal rate without a float", () => {
    expect([rateHundredths("5.00"), rateHundredths("18.00"), rateHundredths("2.5")]).toEqual([
      500, 1800, 250,
    ]);
  });

  it("rounds the base half-up and leaves the remainder as tax", () => {
    // ₹1,499 at 5%: base 142762 (142761.9047… rounds up), tax the rest.
    const split = splitInclusive(149900, "5.00");

    expect(split).toEqual({ rate: "5.00", base_paise: 142762, gst_paise: 7138 });
    expect(split.base_paise + split.gst_paise).toBe(149900);
  });

  it("always gives back exactly what the customer paid", () => {
    for (const paise of [1, 99, 100, 12345, 249900, 250000, 250100, 999999]) {
      for (const rate of ["5.00", "12.00", "18.00"]) {
        const split = splitInclusive(paise, rate);
        expect(split.base_paise + split.gst_paise, `${paise} @ ${rate}`).toBe(paise);
      }
    }
  });

  it("rounds half-up, not half-even and not down", () => {
    // 3 paise at 100% is exactly 1.5 - the only place the rule is visible.
    expect(baseFromInclusive(3, "100.00")).toBe(2);
  });
});

describe("which slab a line falls in", () => {
  it("uses the per-piece price, not the line total", () => {
    // Two ₹2,000 shirts on one line are two 5% pieces, not one 18% line.
    expect(splitLine(400000, 2, APPAREL).rate).toBe("5.00");
    expect(splitLine(400000, 1, APPAREL).rate).toBe("18.00");
  });

  it("decides on the exclusive price, so a tag just over the threshold stays low", () => {
    // ₹2,600 inclusive is ₹2,476.19 exclusive - inside the ₹2,500 threshold, so
    // the low rate is the right one and there is no tie to break.
    expect(splitLine(260000, 1, APPAREL).rate).toBe("5.00");
    expect(splitLine(270000, 1, APPAREL).rate).toBe("18.00");
  });

  it("divides once, on a price that does not divide evenly", () => {
    // Three pieces at ₹2,625.00-ish each, either side of the ₹2,500 exclusive
    // threshold. The server divides exactly and rounds once; rounding per piece
    // first and taking the tax out of that rounds twice, and the second rounding
    // is what can put a piece in a slab the server did not.
    expect(splitLine(787501, 3, APPAREL).rate).toBe("5.00");
    expect(splitLine(787504, 3, APPAREL).rate).toBe("18.00");
  });
});

describe("choosing the slab", () => {
  const old = { ...APPAREL, effective_from: "2024-01-01", rate_below: "12.00" };
  const shirts = { ...APPAREL, hsn_prefix: "6205", rate_below: "0.00" };
  const october = { ...APPAREL, effective_from: "2026-10-01", rate_below: "8.00" };

  it("takes the rate that was live on the day of the bill", () => {
    expect(slabFor([old, APPAREL], "6205", "2025-01-01").rate_below).toBe("12.00");
    expect(slabFor([old, APPAREL], "6205", "2026-07-30").rate_below).toBe("5.00");
  });

  it("ignores a rate whose date has not arrived, but keeps it for when it does", () => {
    // The dataset ships future slabs deliberately: a change announced in July and
    // effective in October has to be on the device before an offline counter
    // reaches October.
    expect(slabFor([APPAREL, october], "6205", "2026-07-30").rate_below).toBe("5.00");
    expect(slabFor([APPAREL, october], "6205", "2026-10-02").rate_below).toBe("8.00");
  });

  it("prefers a rule written for this HSN over the general one", () => {
    expect(slabFor([APPAREL, shirts], "6205", "2026-07-30").rate_below).toBe("0.00");
    expect(slabFor([APPAREL, shirts], "6109", "2026-07-30").rate_below).toBe("5.00");
  });

  it("falls back to apparel's own slab when nothing has synced yet", () => {
    expect(slabFor([], "6205", "2026-07-30")).toMatchObject({
      threshold_paise: 250000,
      rate_below: "5.00",
    });
  });
});
