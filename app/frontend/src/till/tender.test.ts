// Splitting incoming money across cash, card and UPI.

import { describe, expect, it } from "vitest";

import {
  balanceStandingOf,
  canFillTenderRest,
  cashChips,
  emptyPayment,
  prefillFor,
  restTenderPatch,
  splitOf,
  stampManualUpi,
  toTenders,
  whyPaymentCannotClose,
} from "./tender";
import type { Payment } from "./tender";
const BILL = 149900;

function payment(over: Partial<Payment> = {}): Payment {
  return { ...emptyPayment(), ...over };
}

function split(p: Payment, net = BILL) {
  return splitOf(p, net);
}

describe("cash is the balance until somebody says otherwise", () => {
  it("takes the whole bill when nothing else was tendered", () => {
    const resolved = split(payment());

    expect(resolved.cash_paise).toBe(BILL);
    expect(resolved.balance_paise).toBe(0);
  });

  it("falls to what the other modes left", () => {
    const resolved = split(payment({ card_paise: 100000 }));

    expect(resolved.cash_paise).toBe(49900);
    expect(resolved.balance_paise).toBe(0);
  });

  it("stays where the cashier pinned it, and the shortfall shows", () => {
    const resolved = split(payment({ cash_paise: 10000, card_paise: 100000 }));

    expect(resolved.cash_paise).toBe(10000);
    expect(resolved.balance_paise).toBe(39900);
    expect(whyPaymentCannotClose(resolved)).toMatch(/does not cover/);
  });

  it("never goes negative when the other modes cover the bill on their own", () => {
    const resolved = split(payment({ card_paise: BILL }));

    expect(resolved.cash_paise).toBe(0);
    expect(resolved.balance_paise).toBe(0);
  });
});

describe("the explicit tender rest controls", () => {
  it("puts precisely the remaining paise on the selected tender", () => {
    const resolved = split(payment({ cash_paise: 0, card_paise: 100000 }));

    expect(restTenderPatch(resolved, "upi")).toEqual({ upi_paise: 49900 });
    expect(restTenderPatch(resolved, "card")).toEqual({ card_paise: BILL });
  });

  it("offers zero after explicit tenders already cover the bill", () => {
    const resolved = split(payment({ cash_paise: 0, card_paise: BILL }));

    expect(restTenderPatch(resolved, "upi")).toEqual({ upi_paise: 0 });
  });

  it("does not reopen a bank-confirmed UPI row for a second charge", () => {
    const resolved = split(
      payment({
        cash_paise: 0,
        upi_paise: 50000,
        upi_charge: { reference: "417223918811", amount_paise: 50000 },
      }),
    );

    expect(canFillTenderRest(resolved, "upi")).toBe(false);
    expect(canFillTenderRest(resolved, "card")).toBe(true);
  });
});

describe("a split across all three modes", () => {
  const three = payment({
    cash_paise: 49900,
    card_paise: 50000,
    upi_paise: 50000,
  });

  it("adds up to the bill", () => {
    expect(split(three).balance_paise).toBe(0);
    expect(whyPaymentCannotClose(split(three))).toBe("");
  });

  it("becomes three tender rows", () => {
    expect(toTenders(split(three))).toEqual([
      { mode: "cash", amount_paise: 49900 },
      { mode: "card", amount_paise: 50000 },
      { mode: "upi", amount_paise: 50000, upi_state: "manual" },
    ]);
  });

  it("leaves out the modes that took nothing", () => {
    expect(toTenders(split(payment({ upi_paise: BILL, cash_paise: 0 })))).toEqual([
      { mode: "upi", amount_paise: BILL, upi_state: "manual" },
    ]);
  });
});

describe("the UPI stamp (#241)", () => {
  it("toTenders stamps manual on a UPI row no charge ever answered for", () => {
    const rows = toTenders(split(payment({ upi_paise: BILL, cash_paise: 0 })));

    expect(rows).toEqual([{ mode: "upi", amount_paise: BILL, upi_state: "manual" }]);
  });

  it("stampManualUpi leaves an already-stamped row alone", () => {
    const rows = stampManualUpi([
      { mode: "upi", amount_paise: 50000, upi_state: "confirmed", upi_reference: "AXL1" },
    ]);

    expect(rows).toEqual([
      { mode: "upi", amount_paise: 50000, upi_state: "confirmed", upi_reference: "AXL1" },
    ]);
  });

  it("stampManualUpi leaves non-UPI rows unstamped", () => {
    const rows = stampManualUpi([
      { mode: "cash", amount_paise: 29900 },
      { mode: "card", amount_paise: 20000 },
    ]);

    expect(rows).toEqual([
      { mode: "cash", amount_paise: 29900 },
      { mode: "card", amount_paise: 20000 },
    ]);
  });

  it("stampManualUpi fills a legacy queued UPI row that never carried a stamp", () => {
    const rows = stampManualUpi([{ mode: "upi", amount_paise: 50000 }]);

    expect(rows).toEqual([{ mode: "upi", amount_paise: 50000, upi_state: "manual" }]);
  });

  it("stampManualUpi drops a reference left behind without a stamp", () => {
    // `upi_reference` on anything but a `confirmed` row is its own VALIDATION at
    // the server, and this function's whole job is keeping a queued bill it does
    // not control off that cliff - a refusal there halts the store's queue.
    const rows = stampManualUpi([
      { mode: "upi", amount_paise: 50000, upi_reference: "417223918811" },
    ]);

    expect(rows[0].upi_state).toBe("manual");
    expect(rows[0].upi_reference).toBeFalsy();
    expect(JSON.parse(JSON.stringify(rows[0]))).toEqual({
      mode: "upi",
      amount_paise: 50000,
      upi_state: "manual",
    });
  });
});

describe("a charge the bank confirmed (#248)", () => {
  const CHARGED = { reference: "417223918811", amount_paise: BILL };

  it("rides onto the UPI row as confirmed, with the acquirer's reference", () => {
    const resolved = split(payment({ upi_paise: BILL, cash_paise: 0, upi_charge: CHARGED }));

    expect(resolved.upi_confirmed).toBe(CHARGED.reference);
    expect(toTenders(resolved)).toEqual([
      { mode: "upi", amount_paise: BILL, upi_state: "confirmed", upi_reference: CHARGED.reference },
    ]);
  });

  it("falls back to manual the moment the figure stops being the one charged", () => {
    // The cashier charged ₹1,499 and then typed ₹2,000 into the UPI box. The
    // bank confirmed the first figure and knows nothing about the second, so
    // vouching for it is the till's own word - which is what `manual` says.
    const resolved = split(payment({ upi_paise: BILL + 50100, cash_paise: 0, upi_charge: CHARGED }));

    expect(resolved.upi_confirmed).toBeNull();
    expect(toTenders(resolved)).toEqual([
      { mode: "upi", amount_paise: BILL + 50100, upi_state: "manual" },
    ]);
  });

  it("falls away with the UPI row itself", () => {
    // The whole bill moved to card. There is no UPI tender left to stamp, and a
    // stray reference must not follow the next figure typed into the box.
    const resolved = split(payment({ upi_paise: 0, card_paise: BILL, upi_charge: CHARGED }));

    expect(resolved.upi_confirmed).toBeNull();
    expect(toTenders(resolved).some((row) => row.mode === "upi")).toBe(false);
  });

  it("is refused when the reference is blank - the server would refuse the bill", () => {
    const resolved = split(
      payment({ upi_paise: BILL, cash_paise: 0, upi_charge: { reference: " ", amount_paise: BILL } }),
    );

    expect(resolved.upi_confirmed).toBeNull();
    expect(toTenders(resolved)).toEqual([
      { mode: "upi", amount_paise: BILL, upi_state: "manual" },
    ]);
  });

  it("survives a bill kept on hold from before the charge card shipped", () => {
    // `restoreHold` and the draft both hand back a `Payment` written by an
    // older build, with no `upi_charge` key at all.
    const legacy = { ...payment({ upi_paise: BILL, cash_paise: 0 }) } as Partial<Payment>;
    delete legacy.upi_charge;

    const resolved = split(legacy as Payment);

    expect(resolved.upi_confirmed).toBeNull();
    expect(toTenders(resolved)).toEqual([
      { mode: "upi", amount_paise: BILL, upi_state: "manual" },
    ]);
  });
});

describe("a mismatch to the paisa is refused at the counter", () => {
  it("refuses one paisa short", () => {
    const resolved = split(payment({ cash_paise: BILL - 1 }));

    expect(resolved.balance_paise).toBe(1);
    expect(whyPaymentCannotClose(resolved)).toMatch(/does not cover/);
  });

  it("refuses one paisa over, and points at the cash-received box", () => {
    const resolved = split(payment({ cash_paise: BILL + 1 }));

    expect(whyPaymentCannotClose(resolved)).toMatch(/more than the bill/);
  });
});

describe("change is against the cash, not against the bill", () => {
  it("is what is left of the note the customer handed over", () => {
    const resolved = split(payment({ cash_received_paise: 200000 }));

    expect(resolved.change_paise).toBe(200000 - BILL);
  });

  it("counts only the cash half of a split bill", () => {
    // ₹1,000 card, ₹499 cash, and a ₹500 note handed over for the cash half.
    const resolved = split(payment({ card_paise: 100000, cash_received_paise: 50000 }));

    expect(resolved.cash_paise).toBe(49900);
    expect(resolved.change_paise).toBe(100);
  });

  it("is never negative - cash short of the cash tender is not change", () => {
    expect(split(payment({ cash_received_paise: 1000 })).change_paise).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// The prefill and the quick-cash chips (#246, grill Q4)
// ---------------------------------------------------------------------------

/** The ticket's own worked example: a ₹4,848 bill paid three ways. */
const REVAMP_BILL = 484800;

describe("what a tender box takes when the cashier taps into it", () => {
  it("offers the whole bill on an untouched panel", () => {
    expect(prefillFor(split(payment(), REVAMP_BILL))).toBe(REVAMP_BILL);
  });

  it("offers what the filled rows leave - ₹2,000 on card leaves ₹2,848 for UPI", () => {
    const resolved = split(payment({ card_paise: 200000 }), REVAMP_BILL);

    expect(prefillFor(resolved)).toBe(284800);
  });

  it("keeps offering the rest as the split grows - card and UPI leave ₹848 for cash", () => {
    const resolved = split(payment({ card_paise: 200000, upi_paise: 200000 }), REVAMP_BILL);

    expect(prefillFor(resolved)).toBe(84800);
  });

  it("ignores the cash the panel is only *about* to take, or every box would offer nought", () => {
    // The ordinary panel has `cash_paise: null` - cash silently absorbing the
    // whole bill - so the tender balance is already zero. Reading the prefill
    // off that balance would offer nothing to the first box tapped, which is
    // the one case the ticket names by hand.
    const resolved = split(payment({ card_paise: 200000 }), REVAMP_BILL);

    expect(resolved.balance_paise).toBe(0);
    expect(resolved.explicit_paise).toBe(200000);
    expect(prefillFor(resolved)).toBe(284800);
  });

  it("counts cash once the cashier has pinned it", () => {
    const resolved = split(payment({ cash_paise: 84800, card_paise: 200000 }), REVAMP_BILL);

    expect(resolved.explicit_paise).toBe(284800);
    expect(prefillFor(resolved)).toBe(200000);
  });

  it("never offers a negative - an over-tendered panel offers nothing", () => {
    const resolved = split(payment({ card_paise: REVAMP_BILL + 100 }), REVAMP_BILL);

    expect(prefillFor(resolved)).toBe(0);
  });

  it("offers nothing on a bill that owes the customer", () => {
    expect(prefillFor(split(payment(), 0))).toBe(0);
  });
});

describe("the quick-cash chips under the cash row", () => {
  it("offers exact, the next hundred and the next five hundred", () => {
    // ₹4,848 → ₹4,848 · ₹4,900 · ₹5,000.
    expect(cashChips(REVAMP_BILL)).toEqual([484800, 490000, 500000]);
  });

  it("offers the same three on the ₹848 the cash row is left with", () => {
    expect(cashChips(84800)).toEqual([84800, 90000, 100000]);
  });

  it("dedupes when the figure is already round - a ₹5,000 bill offers one chip", () => {
    expect(cashChips(500000)).toEqual([500000]);
  });

  it("dedupes the hundred against the five hundred", () => {
    // ₹4,900 is already a hundred, so only the ₹5,000 chip is added.
    expect(cashChips(490000)).toEqual([490000, 500000]);
  });

  it("keeps the paise on the exact chip - Exact must close to nought", () => {
    // ₹1,499.37: the exact chip is the figure to the paisa, not a rounded one.
    // Both round figures land on ₹1,500 here, so the row is two chips, not three.
    expect(cashChips(149937)).toEqual([149937, 150000]);
  });

  it("shows nothing when the cash row takes nothing", () => {
    expect(cashChips(0)).toEqual([]);
    expect(cashChips(-100)).toEqual([]);
  });
});

describe("the one balance line", () => {
  it("is red while the bill is short", () => {
    const standing = balanceStandingOf(split(payment({ cash_paise: 100000 }), REVAMP_BILL));

    expect(standing).toEqual({ tone: "short", says: "Still to pay", paise: 384800 });
  });

  it("is red when the panel has taken more than the bill, never green", () => {
    // whyPaymentCannotClose is about to refuse this; a green line would say the
    // sale is fine.
    const over = split(payment({ cash_paise: REVAMP_BILL + 100 }), REVAMP_BILL);
    const standing = balanceStandingOf(over);

    expect(standing).toEqual({ tone: "over", says: "Over by", paise: 100 });
  });

  it("is green only when there is cash to hand back", () => {
    const standing = balanceStandingOf(
      split(
        payment({ cash_paise: 84800, card_paise: 400000, cash_received_paise: 100000 }),
        REVAMP_BILL,
      ),
    );

    expect(standing).toEqual({ tone: "change", says: "Change to give", paise: 15200 });
  });

  it("refuses to call a stranded cash-received figure change - the drawer took nothing", () => {
    // The cashier tapped a chip, then put the whole bill on card. `change_paise`
    // still reports the ₹1,000, and green would be an instruction to pay it out.
    const standing = balanceStandingOf(
      split(payment({ card_paise: REVAMP_BILL, cash_received_paise: 100000 }), REVAMP_BILL),
    );

    expect(standing.tone).toBe("stranded");
    expect(standing.paise).toBe(100000);
    expect(standing.says).toMatch(/takes none/);
  });

  it("is quiet when the bill is settled and nothing goes back", () => {
    const standing = balanceStandingOf(split(payment(), REVAMP_BILL));

    expect(standing).toEqual({ tone: "settled", says: "Nothing left to pay", paise: 0 });
  });

  it("never says two things at once - every split lands on exactly one tone", () => {
    const splits = [
      split(payment(), REVAMP_BILL),
      split(payment({ cash_paise: 100000 }), REVAMP_BILL),
      split(payment({ cash_paise: REVAMP_BILL + 1 }), REVAMP_BILL),
      split(payment({ cash_received_paise: 500000 }), REVAMP_BILL),
      split(payment({ card_paise: REVAMP_BILL, cash_received_paise: 100000 }), REVAMP_BILL),
    ];

    expect(splits.map((s) => balanceStandingOf(s).tone)).toEqual([
      "settled",
      "short",
      "over",
      "change",
      "stranded",
    ]);
  });
});

describe("the split the ticket's worked example ends on", () => {
  it("closes to nought and hands back ₹152 of change", () => {
    // ₹4,848: ₹2,000 card, ₹2,000 UPI, ₹848 cash, a ₹1,000 note handed over.
    const resolved = split(
      payment({
        card_paise: 200000,
        upi_paise: 200000,
        cash_paise: 84800,
        cash_received_paise: 100000,
      }),
      REVAMP_BILL,
    );

    expect(resolved.balance_paise).toBe(0);
    expect(resolved.change_paise).toBe(15200);
    expect(whyPaymentCannotClose(resolved)).toBe("");
  });
});
