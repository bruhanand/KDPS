import { describe, expect, it } from "vitest";

import { formatINR, formatRupeeAmount } from "./format";

describe("formatINR", () => {
  it("groups in lakhs and crores, and drops empty paise", () => {
    expect(formatINR(28500000)).toBe("₹2,85,000");
    expect(formatINR(122250)).toBe("₹1,222.50");
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
