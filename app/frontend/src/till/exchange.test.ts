import { describe, expect, it } from "vitest";

import { describeOriginal, legFor, refundFor, returnableQty, whyExchangeCannotClose } from "./exchange";
import type { Exchange, OriginalLine } from "./exchange";

// What a piece is worth back, at the counter (#184, D2).
//
// The arithmetic here is checked again by the server on a bill that has already
// printed - `accept._check_return_refund` refuses the whole bill where the two
// disagree by a single paisa, with the customer gone and the queue stopped
// behind it. So these cases are the same cases `test_sell_returns.py` states on
// the other side, and the two files are meant to be read together.

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

describe("what a piece is worth back", () => {
  it("gives back what the customer paid, not what the tag says", () => {
    // The line was discounted to ₹1,049.30 from a ₹1,499 tag; that is what comes
    // back, and today's ticket price has nothing to do with it.
    expect(refundFor(line({ net_paise: 104930 }), 1)).toBe(104930);
  });

  it("rounds a share half-up, never down", () => {
    // ₹29.99 over three pieces is 999.67 paise. Half-up is 1000; the banker's
    // rounding a naive `round()` would do on a float is what the server refuses.
    expect(refundFor(line({ qty: 3, net_paise: 2999 }), 1)).toBe(1000);
  });

  it("settles the remainder on the last piece, so the parts sum to what was paid", () => {
    const whole = line({ qty: 3, net_paise: 2999 });
    const first = refundFor(whole, 1);
    const second = refundFor({ ...whole, returned_qty: 1, returned_paise: first }, 1);
    const third = refundFor(
      { ...whole, returned_qty: 2, returned_paise: first + second },
      1,
    );
    expect([first, second, third]).toEqual([1000, 1000, 999]);
    expect(first + second + third).toBe(2999);
  });

  it("gives the whole line back when the whole line comes back", () => {
    expect(refundFor(line({ qty: 3, net_paise: 2999 }), 3)).toBe(2999);
  });

  it("counts what has already gone back, whichever way it went", () => {
    // The paise matter as much as the count: a till that knew only that one of
    // three had gone would settle the last two on the wrong remainder.
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
