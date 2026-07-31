// The counter's GSTIN checker (#187) - the mirror of `sell/gstin.py`.
//
// The strings below are the same ones the Python suite drives, and that is the
// suite's whole reason for existing: the bill's tax split is printed here,
// offline, and re-derived on the server days later. Two implementations that
// could disagree would put one tax on the customer's copy and another in the
// books, on every B2B bill, silently.

import { describe, expect, it } from "vitest";

import {
  checkDigit,
  describeGstin,
  normaliseGstin,
  splitTax,
  taxKindFor,
  WELL_FORMED,
} from "./gstin";

/** Registrations that exist. Two different check digits and a letter one, so a
 *  checksum off by a constant could not pass all three. */
const REAL = ["27AAPFU0939F1ZV", "27AAACR5055K1Z7", "09AAACH7409R1ZZ"];

describe("is this a GSTIN", () => {
  it.each(REAL)("accepts the real registration %s", (gstin) => {
    expect(describeGstin(gstin)).toBe(WELL_FORMED);
  });

  it.each(REAL)("computes the check digit the GSTN issued for %s", (gstin) => {
    expect(checkDigit(gstin.slice(0, 14))).toBe(gstin[14]);
  });

  it("does not complain about a B2C bill", () => {
    expect(describeGstin("")).toBe(WELL_FORMED);
    expect(describeGstin("   ")).toBe(WELL_FORMED);
  });

  it("says how short a short one is", () => {
    expect(describeGstin("27AAPFU0939F")).toContain("15 characters");
  });

  it("says when it is not shaped like one at all", () => {
    expect(describeGstin("HELLO WORLD 123")).toContain("Not shaped like a GSTIN");
  });

  it("names a state code the GSTN does not issue", () => {
    expect(describeGstin("45AAPFU0939F1ZV")).toContain("not a state code");
  });

  it("catches a transposed pair, which is the commonest mistype", () => {
    expect(describeGstin("27AAPFU0993F1ZV")).toContain("check digit");
  });

  it("treats case and stray spaces as the counter typing, not a mistake", () => {
    expect(describeGstin("  27aapfu0939f1zv  ")).toBe(WELL_FORMED);
    expect(normaliseGstin("  27aapfu0939f1zv  ")).toBe("27AAPFU0939F1ZV");
  });
});

describe("which split the customer's copy carries", () => {
  it("is nothing at all without a GSTIN", () => {
    expect(taxKindFor("", "10")).toBe("none");
  });

  it("is CGST + SGST when the buyer is registered in this state", () => {
    expect(taxKindFor("10AABCU9603R1Z2", "10")).toBe("cgst_sgst");
  });

  it("is IGST across the Bihar/Jharkhand line", () => {
    // The everyday case at KDPS: two states, two registrations, one chain.
    expect(taxKindFor("20AABCU9603R1Z1", "10")).toBe("igst");
  });

  it("is derived from the characters as typed, even on a mistyped GSTIN", () => {
    // Because the server does exactly the same (`_b2b_tax_kind`), and the paper
    // and the books must say one thing. The bill is flagged, never re-taxed.
    expect(taxKindFor("20AABCU9603R1ZM", "10")).toBe("igst");
  });

  it("reads a counter that has not synced its identity as out of state", () => {
    // The answer that at least does not claim the buyer is local; the server
    // flags the disagreement either way, and nothing refuses to print.
    expect(taxKindFor("10AABCU9603R1Z2", "")).toBe("igst");
  });
});

describe("splitting the tax for the paper", () => {
  it("shows IGST as one line", () => {
    expect(splitTax(999, "igst")).toEqual([{ label: "IGST", paise: 999 }]);
  });

  it("halves an even total exactly", () => {
    expect(splitTax(1000, "cgst_sgst")).toEqual([
      { label: "CGST", paise: 500 },
      { label: "SGST", paise: 500 },
    ]);
  });

  it("never loses the odd paise", () => {
    // The only property that matters: a single OUTPUT_GST account is what
    // actually posts, so the two halves are a presentation of one liability and
    // must add back to exactly what the bill charged.
    const parts = splitTax(999, "cgst_sgst");
    expect(parts.map((p) => p.paise)).toEqual([499, 500]);
    expect(parts.reduce((n, p) => n + p.paise, 0)).toBe(999);
  });

  it("shows nothing on a B2C bill", () => {
    expect(splitTax(1000, "none")).toEqual([]);
  });
});
