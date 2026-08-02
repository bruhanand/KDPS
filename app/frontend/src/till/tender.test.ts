// Splitting the money four ways, and the notes among it (#182).

import { describe, expect, it } from "vitest";

import {
  emptyPayment,
  newNote,
  notesSpentBy,
  splitOf,
  stampManualUpi,
  toTenders,
  whyPaymentCannotClose,
} from "./tender";
import type { Payment } from "./tender";
import type { TillCreditNote } from "./types";

const TODAY = "2026-07-31";
const BILL = 149900;

/** ₹1,200 left on it, good until January. */
const NOTE: TillCreditNote = {
  number: "26-27/DEO/CRN/4",
  remaining_paise: 120000,
  expires_on: "2027-01-30",
};

function payment(over: Partial<Payment> = {}): Payment {
  return { ...emptyPayment(), ...over };
}

function withNote(number: string, amount_paise: number, over: Partial<Payment> = {}): Payment {
  return payment({ notes: [{ ...newNote(), number, amount_paise }], ...over });
}

function split(p: Payment, net = BILL, cached: TillCreditNote[] = [NOTE]) {
  return splitOf(p, net, cached, TODAY);
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
    expect(whyPaymentCannotClose(resolved, false)).toMatch(/does not cover/);
  });

  it("never goes negative when the other modes cover the bill on their own", () => {
    const resolved = split(payment({ card_paise: BILL }));

    expect(resolved.cash_paise).toBe(0);
    expect(resolved.balance_paise).toBe(0);
  });
});

describe("a split across all four modes", () => {
  const four = withNote("26-27/DEO/CRN/4", 20000, {
    cash_paise: 29900,
    card_paise: 50000,
    upi_paise: 50000,
  });

  it("adds up to the bill", () => {
    expect(split(four).balance_paise).toBe(0);
    expect(whyPaymentCannotClose(split(four), false)).toBe("");
  });

  it("becomes four tender rows", () => {
    expect(toTenders(split(four))).toEqual([
      { mode: "cash", amount_paise: 29900 },
      { mode: "card", amount_paise: 50000 },
      { mode: "upi", amount_paise: 50000, upi_state: "manual" },
      { mode: "credit_note", amount_paise: 20000, credit_note: "26-27/DEO/CRN/4" },
    ]);
  });

  it("leaves out the modes that took nothing", () => {
    expect(toTenders(split(payment({ upi_paise: BILL, cash_paise: 0 })))).toEqual([
      { mode: "upi", amount_paise: BILL, upi_state: "manual" },
    ]);
  });
});

describe("the UPI stamp (#241)", () => {
  it("toTenders stamps manual on the UPI row - the only thing the till can legitimately say until #248", () => {
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
      { mode: "credit_note", amount_paise: 20000, credit_note: "26-27/DEO/CRN/4" },
    ]);

    expect(rows).toEqual([
      { mode: "cash", amount_paise: 29900 },
      { mode: "credit_note", amount_paise: 20000, credit_note: "26-27/DEO/CRN/4" },
    ]);
  });

  it("stampManualUpi fills a legacy queued UPI row that never carried a stamp", () => {
    const rows = stampManualUpi([{ mode: "upi", amount_paise: 50000 }]);

    expect(rows).toEqual([{ mode: "upi", amount_paise: 50000, upi_state: "manual" }]);
  });
});

describe("a mismatch to the paisa is refused at the counter", () => {
  it("refuses one paisa short", () => {
    const resolved = split(payment({ cash_paise: BILL - 1 }));

    expect(resolved.balance_paise).toBe(1);
    expect(whyPaymentCannotClose(resolved, false)).toMatch(/does not cover/);
  });

  it("refuses one paisa over, and points at the cash-received box", () => {
    const resolved = split(payment({ cash_paise: BILL + 1 }));

    expect(whyPaymentCannotClose(resolved, false)).toMatch(/more than the bill/);
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

describe("a credit note this counter holds", () => {
  it("pays part of the bill and needs nobody", () => {
    const resolved = split(withNote(NOTE.number, 120000));

    expect(resolved.unverified).toEqual([]);
    expect(resolved.cash_paise).toBe(BILL - 120000);
    expect(whyPaymentCannotClose(resolved, false)).toBe("");
  });

  it("draws down by what the bill spent", () => {
    expect(notesSpentBy(toTenders(split(withNote(NOTE.number, 50000))))).toEqual(
      new Map([[NOTE.number, 50000]]),
    );
  });

  it("cannot be spent past what is left on it", () => {
    const resolved = split(withNote(NOTE.number, 120001));

    expect(resolved.unverified).toEqual([NOTE.number]);
    expect(whyPaymentCannotClose(resolved, false)).toMatch(/less left on it/);
  });

  it("is dead once its own date has passed", () => {
    const expired: TillCreditNote = { ...NOTE, expires_on: "2026-07-30" };
    const resolved = split(withNote(NOTE.number, 50000), BILL, [expired]);

    expect(resolved.unverified).toEqual([NOTE.number]);
    expect(whyPaymentCannotClose(resolved, false)).toMatch(/ran out on 2026-07-30/);
  });
});

describe("a credit note this counter has never heard of", () => {
  const unknown = withNote("26-27/XXX/CRN/9", 50000);

  it("is refused without a manager", () => {
    const resolved = split(unknown);

    expect(resolved.unverified).toEqual(["26-27/XXX/CRN/9"]);
    expect(whyPaymentCannotClose(resolved, false)).toMatch(/has to approve/);
  });

  it("is taken with one", () => {
    expect(whyPaymentCannotClose(split(unknown), true)).toBe("");
  });

  it("still travels on the bill so the server can flag it", () => {
    expect(toTenders(split(unknown))).toContainEqual({
      mode: "credit_note",
      amount_paise: 50000,
      credit_note: "26-27/XXX/CRN/9",
    });
  });
});

describe("what a note row must say before the bill closes", () => {
  it("needs a number", () => {
    expect(whyPaymentCannotClose(split(withNote("", 50000)), true)).toMatch(/Type the number/);
  });

  it("needs an amount", () => {
    expect(whyPaymentCannotClose(split(withNote(NOTE.number, 0)), true)).toMatch(
      /how much of/,
    );
  });

  it("refuses the same note twice - both rows would be checked against the same balance", () => {
    const twice = payment({
      notes: [
        { ...newNote(), number: NOTE.number, amount_paise: 25000 },
        { ...newNote(), number: NOTE.number, amount_paise: 25000 },
      ],
    });

    expect(whyPaymentCannotClose(split(twice), true)).toMatch(/on this bill twice/);
  });

  it("takes two different notes on one bill", () => {
    const second: TillCreditNote = { ...NOTE, number: "26-27/DEO/CRN/5", remaining_paise: 30000 };
    const two = payment({
      notes: [
        { ...newNote(), number: NOTE.number, amount_paise: 25000 },
        { ...newNote(), number: second.number, amount_paise: 30000 },
      ],
    });

    const resolved = split(two, BILL, [NOTE, second]);

    expect(whyPaymentCannotClose(resolved, false)).toBe("");
    expect(notesSpentBy(toTenders(resolved))).toEqual(
      new Map([
        [NOTE.number, 25000],
        [second.number, 30000],
      ]),
    );
  });

  it("ignores the whitespace a scanner or a person leaves around a number", () => {
    const resolved = split(withNote(`  ${NOTE.number} `, 50000));

    expect(resolved.unverified).toEqual([]);
    expect(toTenders(resolved)).toContainEqual({
      mode: "credit_note",
      amount_paise: 50000,
      credit_note: NOTE.number,
    });
  });
});
