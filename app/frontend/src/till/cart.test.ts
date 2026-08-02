import { describe, expect, it } from "vitest";

import {
  addManualPiece,
  addPiece,
  capFor,
  changeFor,
  emptyCart,
  inheritBillSalesman,
  priceCart,
  qtyFrom,
  scanPiece,
  toDraft,
  whyItCannotClose,
} from "./cart";
import type { Cart } from "./cart";
import { legFor } from "./exchange";
import type { Exchange, OriginalLine } from "./exchange";
import type { Ask, Authorisation } from "./pin";
import { newNote } from "./tender";
import type { Payment } from "./tender";
import { item, season } from "./testSupport";
import type { TillCreditNote, TillGstSlab, TillOffer } from "./types";

const SLAB: TillGstSlab = {
  hsn_prefix: "",
  threshold_paise: 250000,
  rate_below: "5.00",
  rate_above: "18.00",
  effective_from: "2020-01-01",
};

/** ₹1,200 left on it, good until January. */
const NOTE: TillCreditNote = {
  number: "26-27/DEO/CRN/4",
  remaining_paise: 120000,
  expires_on: "2027-01-30",
};

const WORLD = { seasons: [season("FW25", 2)], slabs: [SLAB], offers: [], creditNotes: [NOTE] };

/** A manager who has already put their PIN in for exactly these asks. */
function approved(...asks: Ask[]): Authorisation {
  return { user_id: 7, name: "R. Kumar", asks, at: "2026-07-30T12:29:00.000Z" };
}

/** What the bill is about to ask a manager for, from the bill itself - so a test
 *  approves what the screen would actually have shown. */
function asksOf(cart: Cart, options: Parameters<typeof priceCart>[3] = {}): Ask[] {
  return priceCart(cart, WORLD, "2026-07-30", options).asks;
}

function cartOf(...lines: Cart["lines"]): Cart {
  return { ...emptyCart(), lines };
}

/** The same cart, paying a particular way. */
function paying(cart: Cart, payment: Partial<Payment>): Cart {
  return { ...cart, payment: { ...cart.payment, ...payment } };
}

/** A scanned piece, credited to somebody.
 *
 *  The salesman is part of the default because a line without one is a line the
 *  server refuses (`_resolve_line`), so a cart that had none would be an
 *  unclosable cart - and every test here about *something else* would be
 *  measuring that instead. The one test that is about it passes `salesman: null`. */
function scanned(mrp: number | null, over: Partial<Cart["lines"][number]> = {}) {
  return {
    ...addPiece(item("8901", "FW25", mrp), { stock: 3, alternatives: [] }),
    salesman: 1,
    ...over,
  };
}

describe("a rescan of a piece already on the bill (#244, grill Q1)", () => {
  const PIECE = item("8901", "FW25", 149900);

  it("bumps the existing line's qty instead of adding a second one", () => {
    const once = scanPiece(cartOf(), PIECE, { stock: 3, alternatives: [] }, 1);
    const twice = scanPiece(once, PIECE, { stock: 3, alternatives: [] }, 1);

    expect(twice.lines).toHaveLength(1);
    expect(twice.lines[0].qty).toBe(2);
  });

  it("keeps the matched line's salesman, discount and rate untouched", () => {
    // A second unit needing a different salesman is edited per line, as ruled -
    // the rescan itself must never re-stamp today's default onto what is
    // already there.
    const first = scanPiece(cartOf(), PIECE, { stock: 3, alternatives: [] }, 1);
    const withDiscount = {
      ...first,
      lines: [{ ...first.lines[0], disc_paise: 5000 }],
    };

    const rescanned = scanPiece(withDiscount, PIECE, { stock: 3, alternatives: [] }, 9);

    expect(rescanned.lines[0].salesman).toBe(1);
    expect(rescanned.lines[0].disc_paise).toBe(5000);
    expect(rescanned.lines[0].mrp_paise).toBe(149900);
  });

  it("matches on the resolved (barcode, season) cohort, not the barcode alone", () => {
    const fw25 = scanPiece(cartOf(), PIECE, { stock: 3, alternatives: [] }, 1);
    const ss26 = scanPiece(fw25, item("8901", "SS26", 99900), { stock: 1, alternatives: [] }, 1);

    expect(ss26.lines).toHaveLength(2);
    expect(ss26.lines.map((l) => l.season)).toEqual(["FW25", "SS26"]);
  });

  it("never merges into an off-the-tag line, even with the same barcode", () => {
    const manual = { ...cartOf(), lines: [{ ...addManualPiece("8901"), salesman: 1 }] };

    const rescanned = scanPiece(manual, PIECE, { stock: 3, alternatives: [] }, 1);

    expect(rescanned.lines).toHaveLength(2);
    expect(rescanned.lines[1].sold_before_inward).toBe(false);
    expect(rescanned.lines[1].qty).toBe(1);
  });

  it("credits a fresh line to the scanning salesman, as an ordinary scan does", () => {
    const fresh = scanPiece(cartOf(), PIECE, { stock: 3, alternatives: [] }, 4);

    expect(fresh.lines).toHaveLength(1);
    expect(fresh.lines[0].salesman).toBe(4);
  });
});

describe("bill-level Sold by", () => {
  it("fills only lines without an actor, leaving an explicit line choice alone", () => {
    const cart = cartOf(scanned(149900, { salesman: null }), scanned(149900, { salesman: 9 }));

    expect(inheritBillSalesman(cart, 4).lines.map((line) => line.salesman)).toEqual([4, 9]);
  });

  it("leaves a bill unattributed when its bill-level actor is empty", () => {
    const cart = cartOf(scanned(149900, { salesman: null }));

    expect(inheritBillSalesman(cart, null).lines[0].salesman).toBeNull();
  });
});

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
    expect(bill.needsAuthorising).toEqual([
      { kind: "over_cap_discount", ref: bill.lines[0].key, paise: 20000, label: "Line 1" },
    ]);
    expect(whyItCannotClose(bill)).toMatch(/manager/i);
  });

  it("lets a discount inside the cap through without a word", () => {
    const bill = priceCart(cartOf(scanned(200000, { disc_paise: 15000 })), WORLD, "2026-07-30", {
      capPercent: "7.50",
    });

    expect(bill.lines[0].over_cap).toBe(false);
    expect(bill.needsAuthorising).toEqual([]);
    expect(whyItCannotClose(bill)).toBe("");
  });

  it("closes once a manager has approved the over-cap line", () => {
    const cap = { capPercent: "7.50" };
    const discounted = cartOf(scanned(200000, { disc_paise: 20000 }));
    const cart = { ...discounted, authorisation: approved(...asksOf(discounted, cap)) };

    const bill = priceCart(cart, WORLD, "2026-07-30", cap);

    expect(bill.needsAuthorising).toEqual([]);
    expect(whyItCannotClose(bill)).toBe("");
  });

  it("asks again when the cashier raises the discount the manager agreed to", () => {
    // The hole this closes: a manager nods at ₹200 off, the cashier makes it
    // ₹500, and the bill closes with the manager's name on it.
    const cap = { capPercent: "7.50" };
    const agreed = cartOf(scanned(200000, { disc_paise: 20000 }));
    const raised = {
      ...cartOf({ ...agreed.lines[0], disc_paise: 50000 }),
      authorisation: approved(...asksOf(agreed, cap)),
    };

    const bill = priceCart(raised, WORLD, "2026-07-30", cap);

    expect(bill.needsAuthorising).toHaveLength(1);
    expect(whyItCannotClose(bill)).toMatch(/manager/i);
  });

  it("stands when the cashier takes some of that discount back off", () => {
    const cap = { capPercent: "7.50" };
    const agreed = cartOf(scanned(200000, { disc_paise: 50000 }));
    const trimmed = {
      ...cartOf({ ...agreed.lines[0], disc_paise: 20000 }),
      authorisation: approved(...asksOf(agreed, cap)),
    };

    expect(whyItCannotClose(priceCart(trimmed, WORLD, "2026-07-30", cap))).toBe("");
  });

  it("asks again for a second over-cap line the manager never saw", () => {
    const cap = { capPercent: "7.50" };
    const first = cartOf(scanned(200000, { disc_paise: 20000 }));
    const both = {
      ...cartOf(first.lines[0], scanned(200000, { disc_paise: 20000 })),
      authorisation: approved(...asksOf(first, cap)),
    };

    const bill = priceCart(both, WORLD, "2026-07-30", cap);

    expect(bill.asks).toHaveLength(2);
    expect(bill.needsAuthorising).toHaveLength(1);
    expect(whyItCannotClose(bill)).toMatch(/Line 2/);
  });

  it("asks again for an exception of another kind entirely", () => {
    // They approved the credit note and walked away; the cashier then keyed in a
    // discount past the cap.
    const cap = { capPercent: "7.50" };
    const noted = paying(cartOf(scanned(200000)), {
      notes: [{ ...newNote(), number: "26-27/XXX/CRN/9", amount_paise: 20000 }],
    });
    const andDiscounted = {
      ...paying(cartOf(scanned(200000, { disc_paise: 20000 })), noted.payment),
      authorisation: approved(...asksOf(noted, cap)),
    };

    const bill = priceCart(andDiscounted, WORLD, "2026-07-30", cap);

    expect(bill.needsAuthorising.map((ask) => ask.kind)).toEqual(["over_cap_discount"]);
    expect(whyItCannotClose(bill)).toMatch(/manager/i);
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

  it("a piece nobody is credited with - the refusal that halted a queue", () => {
    // Found in browser QA of #185: the counter let a bill close with no salesman
    // on the line, printed it, took the money, and the queue then halted for ever
    // on a `VALIDATION` from `_resolve_line` - with every later bill stuck behind
    // it, because the queue will not reorder itself past a refused bill.
    const bill = priceCart(cartOf(scanned(149900, { salesman: null })), WORLD, "2026-07-30");

    expect(whyItCannotClose(bill)).toMatch(/salesman/i);
  });

  it("a split that leaves part of the bill unpaid", () => {
    const cart = paying(cartOf(scanned(149900)), { cash_paise: 10000, card_paise: 10000 });

    expect(whyItCannotClose(priceCart(cart, WORLD, "2026-07-30"))).toMatch(/does not cover/i);
  });

  it("a credit note this counter cannot check, until a manager approves it", () => {
    const cart = paying(cartOf(scanned(149900)), {
      notes: [{ ...newNote(), number: "26-27/XXX/CRN/9", amount_paise: 50000 }],
    });

    const bill = priceCart(cart, WORLD, "2026-07-30");

    expect(bill.needsAuthorising).toEqual([
      {
        kind: "credit_note",
        ref: "26-27/XXX/CRN/9",
        paise: 50000,
        label: "26-27/XXX/CRN/9",
      },
    ]);
    expect(whyItCannotClose(bill)).toMatch(/has to approve/i);
    expect(
      whyItCannotClose(
        priceCart(
          { ...cart, authorisation: approved(...asksOf(cart)) },
          WORLD,
          "2026-07-30",
        ),
      ),
    ).toBe("");
  });

  it("nothing, when cash quietly takes the whole bill", () => {
    expect(whyItCannotClose(priceCart(cartOf(scanned(149900)), WORLD, "2026-07-30"))).toBe("");
  });
});

describe("the change in the drawer", () => {
  it("is what is left of the cash handed over, against the cash the bill took", () => {
    expect(changeFor(200000, 149900)).toBe(50100);
  });

  it("is nothing when the customer paid the exact amount, or less", () => {
    expect(changeFor(149900, 149900)).toBe(0);
    expect(changeFor(100000, 149900)).toBe(0);
  });
});

describe("the bill handed to the till", () => {
  const cart = paying(
    cartOf(scanned(149900, { salesman: 3 }), scanned(200000, { qty: 2, disc_paise: 5000 })),
    { cash_received_paise: 600000 },
  );
  const bill = priceCart(cart, WORLD, "2026-07-30");
  const drafted = toDraft(bill, {
    billedAt: "2026-07-30T12:31:00.000Z",
    customer: { name: "Mrs Sharma", mobile: "9876543210", gstin: "" },
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

  it("claims no offer when no rule reached the line", () => {
    expect(drafted.lines[0].offer_evidence).toEqual({});
    expect(drafted.lines[0].offer_id ?? null).toBeNull();
  });

  it("names nobody when nobody had to authorise anything", () => {
    expect(drafted.override).toBeUndefined();
  });

  it("says a retail bill carries no tax split at all", () => {
    expect(drafted.b2b_tax_kind).toBe("none");
  });
});

describe("a GSTIN on the bill (#187)", () => {
  const cart = paying(cartOf(scanned(149900, { salesman: 3 })), { cash_received_paise: 149900 });

  function draftFor(gstin: string, storeStateCode = "10") {
    return toDraft(priceCart(cart, WORLD, "2026-07-30"), {
      billedAt: "2026-07-30T12:31:00.000Z",
      customer: { name: "Sharma Traders", mobile: "", gstin },
      storeStateCode,
    });
  }

  it("says what the customer's copy was printed with, so the server can check it", () => {
    // Contract step 11: the server derives its own split and *flags* a
    // disagreement rather than preferring either - which only works if the till
    // says what it printed.
    expect(draftFor("10AABCU9603R1Z2").b2b_tax_kind).toBe("cgst_sgst");
    expect(draftFor("20AABCU9603R1Z1").b2b_tax_kind).toBe("igst");
  });

  it("tidies the registration once, so paper, split and books hold one string", () => {
    const drafted = draftFor(" 10aabcu9603r1z2 ");

    expect(drafted.customer?.gstin).toBe("10AABCU9603R1Z2");
    expect(drafted.b2b_tax_kind).toBe("cgst_sgst");
  });

  it("still closes a bill whose GSTIN is mistyped", () => {
    // The soft check lives on the screen; nothing in the money path refuses.
    expect(draftFor("10AABCU9603R1ZM").b2b_tax_kind).toBe("cgst_sgst");
  });

  it("will not raise a tax invoice a counter cannot put a tax on", () => {
    // No shop state means no honest split, and both dishonest ones charge the
    // wrong tax on a printed customer copy: guessing IGST because the comparison
    // failed, or guessing CGST + SGST because it did not. A retail bill is
    // recoverable; a tax invoice charging the wrong tax is not. The screen keeps
    // the field disabled in this state; this is the backstop behind it.
    const drafted = toDraft(priceCart(cart, WORLD, "2026-07-30"), {
      billedAt: "2026-07-30T12:31:00.000Z",
      customer: { name: "Sharma Traders", mobile: "", gstin: "10AABCU9603R1Z2" },
      storeStateCode: null,
    });

    expect(drafted.customer?.gstin).toBe("");
    expect(drafted.b2b_tax_kind).toBe("none");
  });
});

describe("the bill's split, as the till hands it over", () => {
  const split = paying(cartOf(scanned(149900, { salesman: 3 })), {
    cash_paise: 29900,
    card_paise: 50000,
    upi_paise: 50000,
    notes: [{ ...newNote(), number: NOTE.number, amount_paise: 20000 }],
  });

  it("carries a row per mode that took money", () => {
    const drafted = toDraft(priceCart(split, WORLD, "2026-07-30"), {
      billedAt: "2026-07-30T12:31:00.000Z",
    });

    expect(drafted.tenders).toEqual([
      { mode: "cash", amount_paise: 29900 },
      { mode: "card", amount_paise: 50000 },
      { mode: "upi", amount_paise: 50000, upi_state: "manual" },
      { mode: "credit_note", amount_paise: 20000, credit_note: NOTE.number },
    ]);
    expect(drafted.tenders.reduce((n, t) => n + t.amount_paise, 0)).toBe(drafted.totals.net_paise);
  });

  it("names the manager, what they saw and when they typed the PIN", () => {
    const paidWithUnknownNote = paying(cartOf(scanned(149900, { salesman: 3 })), {
      notes: [{ ...newNote(), number: "26-27/XXX/CRN/9", amount_paise: 50000 }],
    });
    const authorised = {
      ...paidWithUnknownNote,
      authorisation: approved(...asksOf(paidWithUnknownNote)),
    };

    const drafted = toDraft(priceCart(authorised, WORLD, "2026-07-30"), {
      billedAt: "2026-07-30T12:31:00.000Z",
    });

    expect(drafted.override).toEqual({
      user_id: 7,
      kind: "credit_note",
      at: "2026-07-30T12:29:00.000Z",
    });
  });

  it("says both, in one order, when a bill needed two things approving", () => {
    const cap = { capPercent: "7.50" };
    const messy = paying(cartOf(scanned(200000, { salesman: 3, disc_paise: 20000 })), {
      notes: [{ ...newNote(), number: "26-27/XXX/CRN/9", amount_paise: 20000 }],
    });
    const authorised = { ...messy, authorisation: approved(...asksOf(messy, cap)) };

    const drafted = toDraft(priceCart(authorised, WORLD, "2026-07-30", cap), {
      billedAt: "2026-07-30T12:31:00.000Z",
    });

    expect(drafted.override?.kind).toBe("over_cap_discount+credit_note");
  });

  it("leaves an authorisation off a bill that ended up asking for nothing", () => {
    // The cashier took the discount back off after the manager approved it.
    // Sending the override anyway would put a manager's name on an ordinary bill.
    const cap = { capPercent: "7.50" };
    const agreed = cartOf(scanned(200000, { salesman: 3, disc_paise: 20000 }));
    const undone = {
      ...cartOf({ ...agreed.lines[0], disc_paise: 0 }),
      authorisation: approved(...asksOf(agreed, cap)),
    };

    const drafted = toDraft(priceCart(undone, WORLD, "2026-07-30", cap), {
      billedAt: "2026-07-30T12:31:00.000Z",
    });

    expect(drafted.override).toBeUndefined();
  });
});

// --- what the rulebook does to the money on the screen (#183) --------------

const MUFTI_HALF: TillOffer = {
  id: 7,
  name: "Mufti flat 50",
  layer: "brand",
  brand: "MUFTI",
  trigger_type: "none",
  trigger_config: {},
  reward_type: "pct_off",
  reward_config: { percent: "50.00" },
  item_scope: {},
  starts_on: "2026-07-01",
  ends_on: null,
  combinable: false,
  priority: 100,
};

const RULEBOOK = { ...WORLD, offers: [MUFTI_HALF] };

describe("the rulebook, on the line and on the bill", () => {
  it("takes the offer off the line and says which rule did it", () => {
    const bill = priceCart(cartOf(scanned(149900)), RULEBOOK, "2026-07-30");

    expect(bill.lines[0].offer_paise).toBe(74950);
    expect(bill.lines[0].offer_id).toBe(7);
    expect(bill.lines[0].offer_credits).toEqual([
      { offer_id: 7, offer_name: "Mufti flat 50", layer: "brand", saved_paise: 74950 },
    ]);
    expect(bill.lines[0].net_paise).toBe(74950);
  });

  it("quotes the whole saving to the customer, rulebook and cashier together", () => {
    const bill = priceCart(cartOf(scanned(149900, { disc_paise: 5000 })), RULEBOOK, "2026-07-30");

    expect(bill.saved_paise).toBe(79950);
    expect(bill.discount_paise).toBe(79950);
    expect(bill.subtotal_paise).toBe(69950);
    expect(bill.net_paise).toBe(70000); // the bill's own rounding, as ever
  });

  it("does not let an offer count against the cashier's own cap", () => {
    // ₹749.50 is far past any cashier's cap, and it is head office's decision.
    // If the offer counted, every discounted line in the shop would demand a
    // manager and the counter would stop.
    const cart = { ...cartOf(scanned(149900)), tenderedPaise: 100000 };

    const bill = priceCart(cart, RULEBOOK, "2026-07-30", { capPercent: "7.50" });

    expect(bill.lines[0].over_cap).toBe(false);
    expect(whyItCannotClose(bill)).toBe("");
  });

  it("still caps what the cashier keyed in on top of an offer", () => {
    const bill = priceCart(cartOf(scanned(149900, { disc_paise: 20000 })), RULEBOOK, "2026-07-30", {
      capPercent: "7.50",
    });

    expect(bill.lines[0].over_cap).toBe(true);
    expect(whyItCannotClose(bill)).toContain("more than a cashier may");
  });

  it("stops a rule the day it stops, on the counter's own clock", () => {
    const ended = { ...WORLD, offers: [{ ...MUFTI_HALF, ends_on: "2026-07-29" }] };

    expect(priceCart(cartOf(scanned(149900)), ended, "2026-07-30").lines[0].offer_paise).toBe(0);
  });

  it("sends the whole discount up the wire, with the evidence behind it", () => {
    const bill = priceCart(cartOf(scanned(149900, { disc_paise: 5000 })), RULEBOOK, "2026-07-30");
    const draft = toDraft(bill, { billedAt: "2026-07-30T12:31:00.000Z" });

    // One number on the bill, because that is what the customer paid; which part
    // of it the rulebook owns is the server's own question to re-answer.
    expect(draft.lines[0].disc_paise).toBe(79950);
    expect(draft.lines[0].net_paise).toBe(69950);
    expect(draft.lines[0].offer_id).toBe(7);
    expect(draft.lines[0].offer_evidence).toMatchObject({
      offer_id: 7,
      layer: "brand",
      saved_paise: 74950,
    });
  });

  it("leaves a no-discount piece alone (D5 Q3)", () => {
    const protectedPiece = {
      ...addPiece({ ...item("8902", "FW25", 149900), no_discount: true }, {
        stock: 1,
        alternatives: [],
      }),
    };

    const bill = priceCart(cartOf(protectedPiece), RULEBOOK, "2026-07-30");

    expect(bill.lines[0].offer_paise).toBe(0);
    expect(bill.lines[0].net_paise).toBe(149900);
  });
});

describe("a quantity as the counter may type it", () => {
  // `step={1}` on the input is a validation hint, not a filter: the browser
  // hands "1.5" straight to the change handler. A fraction that reached the
  // cart would put a float on the write path and then draw a 400 from the
  // server's `IntegerField(min_value=1)` - on a bill already in a customer's
  // hand, with the whole queue stuck behind it.
  it("keeps whole pieces out of a fraction", () => {
    expect(qtyFrom("1.5")).toBe(1);
    expect(qtyFrom("2.9")).toBe(2);
    expect(qtyFrom(3.7)).toBe(3);
  });

  it("never lets a line go to nought or below", () => {
    expect(qtyFrom("0")).toBe(1);
    expect(qtyFrom("-4")).toBe(1);
  });

  it("survives a box the cashier has emptied mid-edit", () => {
    expect(qtyFrom("")).toBe(1);
    expect(qtyFrom("abc")).toBe(1);
  });

  it("prices a fractional entry as the whole pieces it became", () => {
    const bill = priceCart(cartOf(scanned(149900, { qty: qtyFrom("2.6") })), WORLD, "2026-07-30");

    expect(bill.lines[0].qty).toBe(2);
    expect(bill.lines[0].gross_paise).toBe(299800);
    expect(Number.isInteger(bill.net_paise)).toBe(true);
  });
});

describe("a piece the books never priced", () => {
  it("is marked as needing a price, so the box survives the first digit typed", () => {
    // The bug this guards: keying the price box off `mrp_paise > 0` unmounts it
    // the moment "1" becomes 100 paise, stranding a ₹1,499 garment at ₹1 on a
    // bill so internally consistent the server would take it.
    const line = scanned(null);
    expect(line.needs_price).toBe(true);

    const typing = { ...line, mrp_paise: 100 };
    expect(typing.needs_price).toBe(true);
  });

  it("leaves a priced piece alone", () => {
    expect(scanned(149900).needs_price).toBe(false);
  });

  it("refuses to close until a human types the price off the tag", () => {
    const bill = priceCart(cartOf(scanned(null)), WORLD, "2026-07-30");
    expect(whyItCannotClose(bill)).toContain("no price");
  });
});

describe("what the chips on a line say", () => {
  const STOREWIDE: TillOffer = {
    ...MUFTI_HALF,
    id: 9,
    name: "Monsoon extra 10",
    layer: "storewide",
    brand: undefined,
    reward_config: { percent: "10.00" },
    combinable: true,
  };

  it("gives each rule its own chip and its own share", () => {
    // The defect browser QA found: one chip reading "Mufti flat 50 · ₹824.45",
    // where ₹824.45 was the 50% *and* a storewide 10% - so the counter would
    // have quoted the brand's offer as a sixth more generous than it is.
    const bill = priceCart(
      cartOf(scanned(149900)),
      { ...WORLD, offers: [MUFTI_HALF, STOREWIDE] },
      "2026-07-30",
    );

    expect(bill.lines[0].offer_credits).toEqual([
      { offer_id: 7, offer_name: "Mufti flat 50", layer: "brand", saved_paise: 74950 },
      { offer_id: 9, offer_name: "Monsoon extra 10", layer: "storewide", saved_paise: 7495 },
    ]);
    // And the parts still come to the whole, which is what the customer paid.
    expect(bill.lines[0].offer_paise).toBe(74950 + 7495);
  });

  it("says nothing at all when no rule reached the line", () => {
    expect(priceCart(cartOf(scanned(149900)), WORLD, "2026-07-30").lines[0].offer_credits).toEqual(
      [],
    );
  });

  it("names only the add-on when there was no brand offer to sit on", () => {
    const bill = priceCart(
      cartOf(scanned(149900)),
      { ...WORLD, offers: [STOREWIDE] },
      "2026-07-30",
    );

    expect(bill.lines[0].offer_credits).toEqual([
      { offer_id: 9, offer_name: "Monsoon extra 10", layer: "storewide", saved_paise: 14990 },
    ]);
  });
});

describe("a piece the counter has never heard of", () => {
  /** A manual line, credited to somebody and priced off the tag - which is how
   *  one reaches Save & Print. */
  function offTheTag(over: Partial<Cart["lines"][number]> = {}) {
    return {
      ...addManualPiece("8909999999901"),
      salesman: 1,
      manual_desc: "Blue check shirt",
      mrp_paise: 149900,
      ...over,
    };
  }

  it("keeps the barcode that found nothing", () => {
    // It is not decoration: the server parks the line's cost against this
    // barcode, and the sweep releases it when the PT prices that cohort (#186).
    expect(addManualPiece(" 8909999999901 ").barcode).toBe("8909999999901");
  });

  it("carries no brand, no season and no price, because nothing recorded any", () => {
    const line = addManualPiece("8909999999901");

    expect(line.sold_before_inward).toBe(true);
    expect(line.needs_price).toBe(true);
    expect(line.mrp_paise).toBe(0);
    expect([line.brand, line.season, line.hsn, line.item]).toEqual(["", "", "", ""]);
  });

  it("is taxed at the general apparel slab, having no HSN of its own", () => {
    const bill = priceCart(cartOf(offTheTag()), WORLD, "2026-07-30");

    expect(bill.lines[0].gst_rate).toBe("5.00");
    expect(bill.lines[0].gst_paise).toBe(7138);
  });

  it("no brand rule can reach, because it has no brand yet to be written about", () => {
    // Not a special case anywhere: `item_scope` simply does not match a line with
    // nothing in it. A *storewide* rule still reaches it, and should - "10% off
    // everything today" is a sentence about the shop, not about a cohort.
    const bill = priceCart(cartOf(offTheTag()), RULEBOOK, "2026-07-30");

    expect(bill.lines[0].offer_paise).toBe(0);
    expect(bill.lines[0].offer_credits).toEqual([]);
  });

  it("refuses to close until somebody says what it is", () => {
    // `LINE_UNRESOLVED` on the server, and it arrives after the receipt has
    // printed - halting every bill queued behind it.
    const bill = priceCart(cartOf(offTheTag({ manual_desc: "  " })), WORLD, "2026-07-30");

    expect(whyItCannotClose(bill)).toContain("not in the system");
  });

  it("still refuses to close until somebody types the price off the tag", () => {
    const bill = priceCart(cartOf(offTheTag({ mrp_paise: 0 })), WORLD, "2026-07-30");

    expect(whyItCannotClose(bill)).toContain("no price");
  });

  it("closes once it has a description, a price and a salesman", () => {
    const cart = paying(cartOf(offTheTag()), { cash_received_paise: 149900 });

    expect(whyItCannotClose(priceCart(cart, WORLD, "2026-07-30"))).toBe("");
  });

  it("sends the typed description up with the bill", () => {
    const bill = priceCart(cartOf(offTheTag()), WORLD, "2026-07-30");
    const drafted = toDraft(bill, { billedAt: "2026-07-30T12:31:00.000Z" });

    expect(drafted.lines[0].manual_desc).toBe("Blue check shirt");
    expect(drafted.lines[0].barcode).toBe("8909999999901");
    // And it is an ordinary sale line in every other way, so the arithmetic the
    // server re-derives holds on it too.
    expect(drafted.lines[0].mrp_paise * drafted.lines[0].qty - drafted.lines[0].disc_paise).toBe(
      drafted.lines[0].net_paise,
    );
  });

  it("says nothing about a description on an ordinary scanned line", () => {
    const bill = priceCart(cartOf(scanned(149900)), WORLD, "2026-07-30");
    const drafted = toDraft(bill, { billedAt: "2026-07-30T12:31:00.000Z" });

    expect(drafted.lines[0].manual_desc).toBe("");
  });
});

// --- an exchange on the bill (#184) ----------------------------------------
//
// Every figure here is checked again by `accept._check_totals` on a bill that
// has already printed, so what these cases pin is the identity the server
// re-derives:
//
//   gross    = Σ mrp × qty                (sold lines only)
//   discount = Σ disc                     (sold lines only)
//   net      = Σ sold net − Σ refunds + round
//   GST      = Σ sold GST − Σ refund GST
//   tenders  = max(net, 0)

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

function priced(cart: Cart) {
  return priceCart(cart, WORLD, "2026-07-30");
}

describe("a piece coming back on the same bill", () => {
  it("comes off the bill at what was paid, and takes its tax with it", () => {
    const bill = priced({ ...cartOf(scanned(149900)), exchange: exchangeOf(sold()) });

    expect(bill.refund_paise).toBe(120000);
    // Gross and discount are about what is being *sold*; what comes back is not
    // a discount on it.
    expect(bill.gross_paise).toBe(149900);
    expect(bill.discount_paise).toBe(0);
    expect(bill.net_paise).toBe(149900 - 120000);
    expect(bill.gst_paise).toBe(7138 - 5714);
  });

  it("takes no money at all when the returns outweigh the sales", () => {
    // ₹1,200 back against a ₹499 shirt: the customer is owed ₹701, and it leaves
    // as a credit note (grill Q7) rather than out of the drawer.
    const bill = priced({ ...cartOf(scanned(49900)), exchange: exchangeOf(sold()) });

    expect(bill.net_paise).toBe(49900 - 120000);
    expect(bill.credit_note_paise).toBe(120000 - 49900);
    expect(whyItCannotClose(bill)).toBe("");
    expect(toDraft(bill, { billedAt: "2026-07-30T12:31:00Z" }).tenders).toEqual([]);
  });

  it("is a bill even with nothing being bought", () => {
    const bill = priced({ ...emptyCart(), exchange: exchangeOf(sold()) });

    expect(whyItCannotClose(bill)).toBe("");
    expect(bill.credit_note_paise).toBe(120000);
  });

  it("numbers the returned legs on from the sold lines", () => {
    // The server keys every line of a bill by `line_no` and refuses one that is
    // used twice, so a leg may not reuse a sold line's number.
    const bill = priced({
      ...cartOf(scanned(149900), scanned(49900)),
      exchange: exchangeOf(sold(), sold({ line_no: 2 })),
    });

    const draft = toDraft(bill, { billedAt: "2026-07-30T12:31:00Z" });
    expect(draft.lines.map((l) => l.line_no)).toEqual([1, 2]);
    expect(draft.exchange).toMatchObject({
      original: { fy: "26-27", till_seq: 40 },
      lines: [{ line_no: 3, original_line: 1 }, { line_no: 4, original_line: 2 }],
    });
  });

  it("sends what the customer paid and the tax the bill charged", () => {
    const bill = priced({ ...cartOf(scanned(149900)), exchange: exchangeOf(sold()) });

    const draft = toDraft(bill, { billedAt: "2026-07-30T12:31:00Z" });
    expect(draft.exchange).toMatchObject({
      lines: [{ refund_paise: 120000, gst_rate: "5.00", gst_paise: 5714, condition: "good" }],
    });
  });

  it("refuses to close while a leg gives back nothing", () => {
    const bill = priced({
      ...cartOf(scanned(149900)),
      exchange: exchangeOf(sold({ net_paise: 0 })),
    });

    expect(whyItCannotClose(bill)).toMatch(/nothing to give back/);
  });

  it("leaves an ordinary bill with no exchange block on the wire", () => {
    const draft = toDraft(priced(cartOf(scanned(149900))), {
      billedAt: "2026-07-30T12:31:00Z",
    });
    expect(draft.exchange).toBeUndefined();
  });
});
