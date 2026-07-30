import { describe, expect, it } from "vitest";

import { addPiece, capFor, changeFor, priceCart, toDraft, whyItCannotClose } from "./cart";
import type { Cart } from "./cart";
import { item, season } from "./testSupport";
import type { TillGstSlab } from "./types";

const SLAB: TillGstSlab = {
  hsn_prefix: "",
  threshold_paise: 250000,
  rate_below: "5.00",
  rate_above: "18.00",
  effective_from: "2020-01-01",
};

const WORLD = { seasons: [season("FW25", 2)], slabs: [SLAB] };

function cartOf(...lines: Cart["lines"]): Cart {
  return { lines, tenderedPaise: 0 };
}

function scanned(mrp: number, over: Partial<Cart["lines"][number]> = {}) {
  return { ...addPiece(item("8901", "FW25", mrp), { stock: 3, alternatives: [] }), ...over };
}

describe("what a line costs", () => {
  it("takes the tax out of the ticket price, never adds it on", () => {
    // ₹1,499 inclusive at 5%: base ₹1,427.62, tax ₹71.38. Base + tax is exactly
    // what the customer hands over, on every line.
    const bill = priceCart(cartOf(scanned(149900)), WORLD, "2026-07-30");

    expect(bill.lines[0].net_paise).toBe(149900);
    expect(bill.lines[0].gst_rate).toBe("5.00");
    expect(bill.lines[0].gst_paise).toBe(7138);
    expect(bill.gst_paise).toBe(7138);
  });

  it("prices the ₹2,500 threshold per piece, not per line", () => {
    // Two ₹2,000 shirts are two 5% pieces. Summing them first would tax the line
    // at 18% and the server's recomputation would disagree by ₹520.
    const bill = priceCart(cartOf(scanned(200000, { qty: 2 })), WORLD, "2026-07-30");

    expect(bill.lines[0].gst_rate).toBe("5.00");
  });

  it("subtracts a manual discount before the tax split", () => {
    const bill = priceCart(cartOf(scanned(200000, { disc_paise: 20000 })), WORLD, "2026-07-30");

    expect(bill.gross_paise).toBe(200000);
    expect(bill.discount_paise).toBe(20000);
    expect(bill.lines[0].net_paise).toBe(180000);
    expect(bill.saved_paise).toBe(20000);
  });
});

describe("what the bill comes to", () => {
  it("rounds the whole bill to the nearest rupee and carries the difference", () => {
    const bill = priceCart(cartOf(scanned(149949)), WORLD, "2026-07-30");

    expect(bill.subtotal_paise).toBe(149949);
    expect(bill.net_paise).toBe(149900);
    expect(bill.round_paise).toBe(-49);
  });

  it("rounds a half rupee up, the way a shop does", () => {
    const bill = priceCart(cartOf(scanned(149950)), WORLD, "2026-07-30");

    expect(bill.net_paise).toBe(150000);
    expect(bill.round_paise).toBe(50);
  });

  it("keeps the rounding line inside the fifty paise the server allows", () => {
    for (const mrp of [1, 49, 50, 51, 99, 100, 149999]) {
      const bill = priceCart(cartOf(scanned(mrp)), WORLD, "2026-07-30");
      expect(Math.abs(bill.round_paise), `${mrp}`).toBeLessThanOrEqual(50);
      expect(bill.net_paise % 100).toBe(0);
    }
  });

  it("leaves the tax alone when it rounds - rounding is not a discount", () => {
    const bill = priceCart(cartOf(scanned(149949)), WORLD, "2026-07-30");

    expect(bill.gst_paise).toBe(bill.lines[0].gst_paise);
  });

  it("adds the lines up the way the accept pipeline checks them", () => {
    const bill = priceCart(
      cartOf(scanned(149900), scanned(200000, { qty: 2, disc_paise: 5000 })),
      WORLD,
      "2026-07-30",
    );

    expect(bill.gross_paise).toBe(149900 + 400000);
    expect(bill.discount_paise).toBe(5000);
    expect(bill.subtotal_paise).toBe(bill.lines.reduce((n, l) => n + l.net_paise, 0));
    expect(bill.net_paise).toBe(bill.subtotal_paise + bill.round_paise);
    expect(bill.gst_paise).toBe(bill.lines.reduce((n, l) => n + l.gst_paise, 0));
    expect(bill.pieces).toBe(3);
  });
});

describe("the cashier's discount cap", () => {
  it("is a percentage of what the line is worth at full price", () => {
    expect(capFor(200000, 2, "7.50")).toBe(30000);
  });

  it("truncates rather than rounds, exactly as the accept pipeline does", () => {
    expect(capFor(333, 1, "7.50")).toBe(24);
  });

  it("is nothing at all until head office turns the dial", () => {
    expect(capFor(200000, 1, "0.00")).toBe(0);
  });

  it("marks a line the cashier may not discount on their own", () => {
    const bill = priceCart(cartOf(scanned(200000, { disc_paise: 20000 })), WORLD, "2026-07-30", {
      capPercent: "7.50",
    });

    expect(bill.lines[0].cap_paise).toBe(15000);
    expect(bill.lines[0].over_cap).toBe(true);
    expect(whyItCannotClose(bill)).toMatch(/manager/i);
  });

  it("lets a discount inside the cap through without a word", () => {
    const cart = { ...cartOf(scanned(200000, { disc_paise: 15000 })), tenderedPaise: 200000 };

    const bill = priceCart(cart, WORLD, "2026-07-30", { capPercent: "7.50" });

    expect(bill.lines[0].over_cap).toBe(false);
    expect(whyItCannotClose(bill)).toBe("");
  });
});

describe("what stops a bill closing", () => {
  it("an empty bill", () => {
    expect(whyItCannotClose(priceCart(cartOf(), WORLD, "2026-07-30"))).toMatch(/nothing/i);
  });

  it("a piece nobody has priced - never billed at nought (contract, step 3)", () => {
    const bill = priceCart(cartOf(scanned(0)), WORLD, "2026-07-30");

    expect(whyItCannotClose(bill)).toMatch(/price/i);
  });

  it("a discount bigger than the piece", () => {
    const bill = priceCart(cartOf(scanned(100000, { disc_paise: 200000 })), WORLD, "2026-07-30");

    expect(whyItCannotClose(bill)).toMatch(/discount/i);
  });

  it("cash short of the bill", () => {
    const cart = { ...cartOf(scanned(149900)), tenderedPaise: 100000 };

    expect(whyItCannotClose(priceCart(cart, WORLD, "2026-07-30"))).toMatch(/cash/i);
  });

  it("nothing, when the cash covers it", () => {
    const cart = { ...cartOf(scanned(149900)), tenderedPaise: 200000 };

    expect(whyItCannotClose(priceCart(cart, WORLD, "2026-07-30"))).toBe("");
  });
});

describe("the change in the drawer", () => {
  it("is what is left of the cash after the bill", () => {
    expect(changeFor(200000, 149900)).toBe(50100);
  });

  it("is nothing when the customer paid the exact amount, or less", () => {
    expect(changeFor(149900, 149900)).toBe(0);
    expect(changeFor(100000, 149900)).toBe(0);
  });
});

describe("the bill handed to the till", () => {
  const cart = {
    ...cartOf(scanned(149900, { salesman: 3 }), scanned(200000, { qty: 2, disc_paise: 5000 })),
    tenderedPaise: 600000,
  };
  const bill = priceCart(cart, WORLD, "2026-07-30");
  const drafted = toDraft(bill, {
    billedAt: "2026-07-30T12:31:00.000Z",
    customer: { name: "Mrs Sharma", mobile: "9876543210" },
  });

  it("numbers its lines from one, in the order they were scanned", () => {
    expect(drafted.lines.map((l) => l.line_no)).toEqual([1, 2]);
    expect(drafted.lines.every((l) => l.direction === "sale")).toBe(true);
  });

  it("satisfies the per-line arithmetic the server re-derives", () => {
    for (const line of drafted.lines) {
      expect(line.mrp_paise * line.qty - line.disc_paise).toBe(line.net_paise);
    }
  });

  it("tenders exactly the bill in cash - never the cash the customer held out", () => {
    expect(drafted.tenders).toEqual([{ mode: "cash", amount_paise: drafted.totals.net_paise }]);
  });

  it("carries the salesman the cashier credited", () => {
    expect(drafted.lines[0].salesman).toBe(3);
  });

  it("names the customer without needing to", () => {
    expect(drafted.customer).toEqual({ name: "Mrs Sharma", mobile: "9876543210", gstin: "" });
  });

  it("claims no offer, because there is no rulebook yet (#183)", () => {
    expect(drafted.lines.every((l) => l.offer_evidence && !("saved_paise" in l.offer_evidence)));
    expect(drafted.lines[0].offer_id ?? null).toBeNull();
  });
});
