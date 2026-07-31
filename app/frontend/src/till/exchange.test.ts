import { describe, expect, it } from "vitest";

import { describeOriginal, legFor, returnableQty, whyExchangeCannotClose } from "./exchange";
import type { Exchange, OriginalLine } from "./exchange";

// The counter's half of an exchange, minus the arithmetic (#184, D2).
//
// What a piece is *worth* back is not here: those cases live in
// `sell/vectors/refunds.json` and are driven by `refund.vectors.test.ts` against
// the very same file the server's suite reads, because a second hand-written
// copy of that rule is the thing the pairing exists to prevent. What is here is
// everything with no Python counterpart - the leg a refund becomes on the bill,
// its tax, and why an exchange will not close.

function line(over: Partial<OriginalLine> = {}): OriginalLine {
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
    net_paise: 149900,
    gst_rate: "5.00",
    gst_paise: 7138,
    manual_desc: "",
    direction: "sale",
    returned_qty: 0,
    returned_paise: 0,
    ...over,
  };
}

describe("how much of a line is still returnable", () => {
  it("counts what has already gone back, whichever way it went", () => {
    expect(returnableQty(line({ qty: 3, returned_qty: 2 }))).toBe(1);
    expect(returnableQty(line({ qty: 3, returned_qty: 3 }))).toBe(0);
  });
});

describe("a leg on the bill", () => {
  it("carries the tax the bill charged, out of the refund", () => {
    const leg = legFor(line({ net_paise: 104930, gst_rate: "5.00" }), 1);
    // The identity the server checks: refund less the base at the quoted rate.
    expect(leg.refund_paise).toBe(104930);
    expect(leg.gst_paise).toBe(104930 - 99933);
    expect(leg.gst_rate).toBe("5.00");
  });

  it("comes back on the shelf unless somebody says it is damaged", () => {
    expect(legFor(line(), 1).condition).toBe("good");
  });

  it("describes the piece the books' way, and the cashier's when there is no other", () => {
    expect(describeOriginal(line())).toBe("MUFTI · Shirt · SHIRT-01 · M");
    const offTheTag = line({ brand: "", item: "", design: "", size: "", manual_desc: "Blue kurta" });
    expect(describeOriginal(offTheTag)).toBe("Blue kurta");
    expect(describeOriginal({ ...offTheTag, manual_desc: "" })).toBe("8901000000011");
  });
});

describe("why an exchange cannot close", () => {
  const original = { fy: "26-27", till_seq: 40, doc_number: "26-27/DEO/SAL/40" };

  it("is silent on a bill with no exchange on it at all", () => {
    expect(whyExchangeCannotClose(null)).toBe("");
  });

  it("refuses an exchange whose lines have all been taken off", () => {
    expect(whyExchangeCannotClose({ original, lines: [] })).toMatch(/No piece is being given back/);
  });

  it("refuses to give anything back for a piece that was billed at nothing", () => {
    const leg = legFor(line({ net_paise: 0 }), 1);
    const exchange: Exchange = { original, lines: [leg] };
    expect(whyExchangeCannotClose(exchange)).toMatch(/nothing to give back/);
  });

  it("is silent on an ordinary exchange", () => {
    expect(whyExchangeCannotClose({ original, lines: [legFor(line(), 1)] })).toBe("");
  });
});
