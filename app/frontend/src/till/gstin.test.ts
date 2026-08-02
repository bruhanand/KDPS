// The parts of the counter's GSTIN module that are the counter's alone.
//
// Whether a string is a GSTIN, why it is not, which state it names and which
// split a bill carries are all shared with the server and asserted against one
// file in `gstin.vectors.test.ts`. What is left here is what has no Python
// counterpart:
//
//   · the check digit against three real registrations - the argument that the
//     mod-36 algorithm is the GSTN's rather than one that merely self-agrees;
//   · `storeStateCodeOf`, which is about the *shop's* identity as the till holds
//     it in IndexedDB;
//   · `splitTax`, which is presentation - a single OUTPUT_GST account posts, so
//     CGST and SGST on the paper are two halves of one liability.

import { describe, expect, it } from "vitest";

import { checkDigit, splitTax, storeStateCodeOf } from "./gstin";

/** Registrations that exist. Two different check digits and a letter one, so a
 *  checksum off by a constant could not pass all three. */
const REAL = ["27AAPFU0939F1ZV", "27AAACR5055K1Z7", "09AAACH7409R1ZZ"];

describe("the check digit", () => {
  it.each(REAL)("is the one the GSTN issued for %s", (gstin) => {
    expect(checkDigit(gstin.slice(0, 14))).toBe(gstin[14]);
  });
});

describe("which state this shop is in", () => {
  it("is the dataset's field when it has one", () => {
    expect(storeStateCodeOf({ gstin: "10AABCU9603R1Z2", state_code: "10" })).toBe("10");
  });

  it("falls back to the shop's own registration, which begins with it", () => {
    // Worth having: the alternative is a counter that knows its GSTIN, cannot
    // name its state, and therefore prints IGST on a local buyer's tax invoice
    // while the server posts CGST + SGST.
    expect(storeStateCodeOf({ gstin: "10AABCU9603R1Z2", state_code: "" })).toBe("10");
  });

  it("answers null - not a blank state - when the counter has no identity", () => {
    // "I do not know which state this shop is in" and "this shop is in state ''"
    // are different statements, and only one of them may price a bill.
    expect(storeStateCodeOf(null)).toBeNull();
    expect(storeStateCodeOf({ gstin: "", state_code: "" })).toBeNull();
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
    // The only property that matters: one OUTPUT_GST account is what actually
    // posts, so the two halves must add back to exactly what the bill charged.
    const parts = splitTax(999, "cgst_sgst");
    expect(parts.map((p) => p.paise)).toEqual([499, 500]);
    expect(parts.reduce((n, p) => n + p.paise, 0)).toBe(999);
  });

  it("shows nothing on a B2C bill", () => {
    expect(splitTax(1000, "none")).toEqual([]);
  });
});
