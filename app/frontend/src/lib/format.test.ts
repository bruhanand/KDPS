// The rupee ⇄ paise boundary (#171).
//
// `formatINR` has been read from since K9; `rupeesToPaise` is its inverse, added
// with the store-target grid, and it is the only place in the PWA that turns
// something a person typed into a money value the server will store. So the one
// property worth holding it to is that it never invents precision: a float
// multiply would send `2551.0000000000005`, and the money column refuses that
// rather than rounding it (ADR-0004).
import { describe, expect, it } from "vitest";

import { formatDateTime, formatINR, formatRupeeAmount, paiseToRupees, rupeesToPaise } from "./format";

describe("formatINR", () => {
  it("groups in lakhs and crores, and drops empty paise", () => {
    expect(formatINR(28500000)).toBe("₹2,85,000");
    expect(formatINR(122250)).toBe("₹1,222.50");
  });

  it("puts the minus outside the rupee sign", () => {
    // An overpaid bill shows what it owes back, and "₹-1" is not how money is
    // written - `formatRupeeAmount` below has always agreed.
    expect(formatINR(-100)).toBe("-₹1");
    expect(formatINR(-122250)).toBe("-₹1,222.50");
    expect(formatINR(-250000000, { short: true })).toBe("-₹25.00 L");
    expect(formatINR(0)).toBe("₹0");
  });
});

describe("formatRupeeAmount", () => {
  // The read endpoints that project money as a rupee decimal string. The
  // counter was seeing "72450.00".
  it("renders a server rupee string in Indian format", () => {
    expect(formatRupeeAmount("72450.00")).toBe("₹72,450");
    expect(formatRupeeAmount("124950.00")).toBe("₹1,24,950");
    expect(formatRupeeAmount("0")).toBe("₹0");
    expect(formatRupeeAmount("-1234.5")).toBe("-₹1,234.50");
  });

  it("reads the string rather than multiplying it", () => {
    // 72450.29 * 100 is 7245028.999... in float; text parsing is exact.
    expect(formatRupeeAmount("72450.29")).toBe("₹72,450.29");
  });

  it("hands back anything it cannot read, rather than showing ₹0", () => {
    expect(formatRupeeAmount("")).toBe("");
    expect(formatRupeeAmount("n/a")).toBe("n/a");
  });
});

describe("rupeesToPaise", () => {
  it("reads whole rupees", () => {
    expect(rupeesToPaise("2500000")).toBe(250000000);
  });

  it("reads the paise a person typed", () => {
    expect(rupeesToPaise("25.51")).toBe(2551);
    expect(rupeesToPaise("25.5")).toBe(2550);
    expect(rupeesToPaise("0.01")).toBe(1);
  });

  it("never lands on a fraction of a paise", () => {
    // The float route (`Number(text) * 100`) fails on these; digit arithmetic
    // does not, and an exact integer is the whole point.
    for (const rupees of ["25.51", "1.13", "8.29", "104.15", "1234567.89"]) {
      const paise = rupeesToPaise(rupees);
      expect(Number.isInteger(paise)).toBe(true);
    }
    expect(rupeesToPaise("1234567.89")).toBe(123456789);
  });

  it("accepts the grouping it renders", () => {
    // ₹25,00,000 is what the grid shows, so it is what gets pasted back in.
    expect(rupeesToPaise("25,00,000")).toBe(250000000);
    expect(rupeesToPaise(" 2,500 ")).toBe(250000);
  });

  it("treats zero as an amount, because a shut store's target is nought", () => {
    expect(rupeesToPaise("0")).toBe(0);
  });

  it("refuses what is not an amount rather than guessing", () => {
    for (const text of ["", "  ", "-1", "25 lakh", "1e6", "abc", "25.", ".5", "25.123", "₹25"]) {
      expect(rupeesToPaise(text)).toBeNull();
    }
  });

  it("round-trips what formatINR renders", () => {
    for (const paise of [0, 1, 2550, 250000000, 123456789]) {
      const rendered = formatINR(paise).replace("₹", "");
      expect(rupeesToPaise(rendered)).toBe(paise);
    }
  });
});

describe("paiseToRupees", () => {
  it("drops the paise when there are none", () => {
    expect(paiseToRupees(250000000)).toBe("2500000");
    expect(paiseToRupees(0)).toBe("0");
  });

  it("keeps both digits when there are some", () => {
    expect(paiseToRupees(2551)).toBe("25.51");
    expect(paiseToRupees(2550)).toBe("25.50");
    expect(paiseToRupees(1)).toBe("0.01");
  });

  it("is the exact inverse of rupeesToPaise", () => {
    // The property that matters: this fills the edit box, and whatever is in the
    // box is what gets converted back and sent. A lossy pair here would let a
    // correction that changed nothing still move the number.
    for (const paise of [0, 1, 99, 100, 2550, 2551, 250000000, 123456789, 999999999999]) {
      expect(rupeesToPaise(paiseToRupees(paise))).toBe(paise);
    }
  });

  it("never renders a float artefact", () => {
    for (let paise = 0; paise < 2000; paise += 7) {
      expect(paiseToRupees(paise)).toMatch(/^\d+(\.\d{2})?$/);
    }
  });
});

describe("formatDateTime", () => {
  it("writes a moment the way an Indian store reads one, to the minute", () => {
    // Rendered in the runner's zone, so the assertion is built the same way
    // rather than hard-coding an offset the CI box may not share.
    const when = new Date("2026-08-01T12:00:00Z");
    const shown = formatDateTime("2026-08-01T12:00:00Z");
    expect(shown).toContain(String(when.getFullYear()));
    expect(shown).toMatch(/\d{1,2}:\d{2}/);
    // Month as a word, never a bare number: "1/8" and "8/1" are the same six
    // characters and different days, which is the confusion this format exists
    // to remove.
    expect(shown).toMatch(/[A-Za-z]{3}/);
  });

  it("distinguishes the two readings of an ambiguous date", () => {
    // The whole point on the request screens: 08/02 typed into a picker
    // rendering in another locale is a different day, and this is what makes
    // that visible before anybody commits to it.
    expect(formatDateTime("2026-02-08T10:00:00Z")).not.toBe(
      formatDateTime("2026-08-02T10:00:00Z"),
    );
  });
});
