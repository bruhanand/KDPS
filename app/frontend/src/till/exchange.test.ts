import { describe, expect, it } from "vitest";

import {
  describeOriginal,
  isPastReturnWindow,
  legsFrom,
  legFor,
  markReturnedPiece,
  returnableQty,
  takeEverythingBack,
  whyExchangeCannotClose,
} from "./exchange";
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

describe("the return window on the till's local calendar", () => {
  const now = new Date(2026, 7, 3, 12);

  it("keeps the last allowed day inside the window", () => {
    expect(isPastReturnWindow("2026-07-04T06:30:00Z", 30, now)).toBe(false);
  });

  it("requires a manager on the following local date", () => {
    expect(isPastReturnWindow("2026-07-03T06:30:00Z", 30, now)).toBe(true);
  });

  it("fails closed when the original date cannot be read", () => {
    expect(isPastReturnWindow("not-a-date", 30, now)).toBe(true);
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

describe("marking pieces back on the counter", () => {
  const found = {
    original: { fy: "26-27", till_seq: 40, doc_number: "26-27/DEO/SAL/40" },
    billed_at: "2026-08-01T10:00:00.000Z",
    customer_name: "Sunita Devi",
    customer_mobile: "9835212345",
    local: false,
    lines: [line({ qty: 3, returned_qty: 1, returned_paise: 49967 })],
  };

  it("a scan marks one piece and stops at bought minus already returned", () => {
    const first = markReturnedPiece(found, {}, "8901000000011");
    const second = markReturnedPiece(found, first.picked, "8901000000011");
    const capped = markReturnedPiece(found, second.picked, "8901000000011");

    expect(first.picked[1].qty).toBe(1);
    expect(second.picked[1].qty).toBe(2);
    expect(capped.picked[1].qty).toBe(2);
    expect(capped.error).toMatch(/already marked/i);
  });

  it("take everything back selects every remaining piece without losing reason and condition", () => {
    const another = line({
      line_no: 2,
      barcode: "8901000000028",
      qty: 2,
      returned_qty: 0,
      returned_paise: 0,
    });
    const picked = takeEverythingBack(
      { ...found, lines: [...found.lines, another] },
      { 1: { qty: 1, reason: "defect", condition: "damaged" } },
    );

    expect(picked).toMatchObject({
      1: { qty: 2, reason: "defect", condition: "damaged" },
      2: { qty: 2, reason: "", condition: "good" },
    });
  });

  it("turns the marked quantities into the Sale's return legs", () => {
    const legs = legsFrom(found, {
      1: { qty: 2, reason: "defect", condition: "damaged" },
    });

    expect(legs).toHaveLength(1);
    expect(legs[0]).toMatchObject({
      original_line: 1,
      qty: 2,
      reason: "defect",
      condition: "damaged",
      refund_paise: 149900 - 49967,
    });
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
