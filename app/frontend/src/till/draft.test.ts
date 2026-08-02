// The bill that survives a crash (#244, grill ruling 30 Jul 2026).
//
// Three properties, matching the acceptance criteria:
//
//   · a draft written then read back reproduces the cart exactly, paise intact;
//   · a read that lands after the screen has already moved on is dropped, not
//     applied - the mount race and the exchange hand-off both land here;
//   · a failed write is a safety net that missed, never a gate on the bill.

import "fake-indexeddb/auto";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { addPiece, emptyCart, newKey } from "./cart";
import type { Cart } from "./cart";
import type { TillDb } from "./db";
import { clearDraft, persistDraft, readDraft, rekeyDraft, restoredDraft } from "./draft";
import type { DraftPayload } from "./draft";
import { newLegKey } from "./exchange";
import type { ExchangeLeg } from "./exchange";
import { covers, OVER_CAP_DISCOUNT, UNVERIFIED_NOTE } from "./pin";
import type { Ask, Authorisation } from "./pin";
import { tillToday } from "./pricing";
import { freshTill, item } from "./testSupport";
import { emptyPayment } from "./tender";
import type { TillCustomer } from "./types";

const NO_CUSTOMER: TillCustomer = { name: "", mobile: "", gstin: "" };

function cartOf(): Cart {
  return {
    lines: [{ ...addPiece(item("8901000000011"), { stock: 3, alternatives: [] }), salesman: 3 }],
    payment: { ...emptyPayment(), cash_received_paise: 149900 },
    authorisation: null,
    exchange: null,
  };
}

function legOf(key: string): ExchangeLeg {
  return {
    key,
    original_line: 1,
    barcode: "8901000000011",
    season: "FW25",
    brand: "MUFTI",
    item: "Shirt",
    design: "SHIRT-01",
    size: "M",
    qty: 1,
    refund_paise: 149900,
    gst_rate: "5.00",
    gst_paise: 7138,
    reason: "",
    condition: "good",
    description: "MUFTI · Shirt · SHIRT-01 · M",
  };
}

let till: ReturnType<typeof freshTill>;
let db: TillDb;

beforeEach(() => {
  till = freshTill();
  db = till.db;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("writing the draft through", () => {
  it("reproduces the cart, the customer and the paper state exactly", async () => {
    const cart = cartOf();
    const customer: TillCustomer = { name: "Mrs Sharma", mobile: "9876543210", gstin: "" };

    await persistDraft(db, cart, customer, 305, "2026-08-01T09:15");

    expect(await readDraft(db)).toMatchObject({
      cart,
      customer,
      paper: 305,
      paperAt: "2026-08-01T09:15",
    });
  });

  it("is nothing at all until something has been saved", async () => {
    expect(await readDraft(db)).toBeNull();
  });

  it("overwrites what was there before - one row, not a history", async () => {
    await persistDraft(db, cartOf(), NO_CUSTOMER, null, null);
    const second = { ...cartOf(), lines: [] };

    await persistDraft(db, second, NO_CUSTOMER, null, null);

    expect((await readDraft(db))?.cart.lines).toHaveLength(0);
  });

  it("clears on commit success, New bill, and Hold", async () => {
    await persistDraft(db, cartOf(), NO_CUSTOMER, null, null);

    await clearDraft(db);

    expect(await readDraft(db)).toBeNull();
  });

  it("logs and carries on rather than blocking the bill on a failed write", async () => {
    const failing = vi.spyOn(db.draft, "put").mockRejectedValue(new Error("storage full"));
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(persistDraft(db, cartOf(), NO_CUSTOMER, null, null)).resolves.toBeUndefined();

    expect(failing).toHaveBeenCalled();
    expect(logged).toHaveBeenCalled();
  });

  it("logs and carries on rather than reporting a held or committed bill as failed", async () => {
    // Clearing follows a hold or a commit that has already gone through - a
    // storage error here must not read back to the cashier as that sale
    // having failed.
    const failing = vi.spyOn(db.draft, "delete").mockRejectedValue(new Error("storage full"));
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(clearDraft(db)).resolves.toBeUndefined();

    expect(failing).toHaveBeenCalled();
    expect(logged).toHaveBeenCalled();
  });
});

describe("the one restore decision (the 2 Aug 2026 atomic-restore and draft-age rulings)", () => {
  const draft: DraftPayload = {
    cart: cartOf(),
    customer: { name: "Mrs Sharma", mobile: "9876543210", gstin: "" },
    paper: null,
    paperAt: null,
    savedAt: "2026-08-01T09:00:00.000Z",
  };
  const savedDay = tillToday(new Date(draft.savedAt));
  const nextDay = tillToday(new Date("2026-08-02T09:00:00.000Z"));

  it("an empty screen restores all four parts from one snapshot", () => {
    const withPaper: DraftPayload = { ...draft, paper: 61, paperAt: "2026-08-01T09:05" };

    const decision = restoredDraft(
      { cart: emptyCart(), customer: NO_CUSTOMER },
      withPaper,
      savedDay,
      true,
    );

    expect(decision).toEqual({ kind: "apply", draft: withPaper });
  });

  it("a live cart plus an empty customer strip restores neither half", () => {
    // Round-2's defect: the exchange hand-off (or a scan) landing on the cart
    // must not leave the customer strip's own emptiness free to pull in a
    // different, crashed bill's name, mobile and GSTIN.
    const decision = restoredDraft({ cart: cartOf(), customer: NO_CUSTOMER }, draft, savedDay, true);

    expect(decision).toEqual({ kind: "drop" });
  });

  it("an exchange leg on an otherwise empty cart also drops the draft whole", () => {
    const withExchange: Cart = {
      ...emptyCart(),
      exchange: { original: { fy: "26-27", till_seq: 40, doc_number: "26-27/DEO/SAL/40" }, lines: [] },
    };

    const decision = restoredDraft(
      { cart: withExchange, customer: NO_CUSTOMER },
      draft,
      savedDay,
      true,
    );

    expect(decision).toEqual({ kind: "drop" });
  });

  it("an empty cart plus a customer field somebody already typed restores neither half", () => {
    const typing: TillCustomer = { name: "Sharma Traders", mobile: "", gstin: "" };

    const decision = restoredDraft({ cart: emptyCart(), customer: typing }, draft, savedDay, true);

    expect(decision).toEqual({ kind: "drop" });
  });

  it("a draft saved yesterday is not auto-applied", () => {
    const decision = restoredDraft(
      { cart: emptyCart(), customer: NO_CUSTOMER },
      draft,
      nextDay,
      true,
    );

    expect(decision).toEqual({ kind: "stale", draft });
  });

  it("a same-day draft is auto-applied", () => {
    const decision = restoredDraft(
      { cart: emptyCart(), customer: NO_CUSTOMER },
      draft,
      savedDay,
      true,
    );

    expect(decision).toEqual({ kind: "apply", draft });
  });

  it("a paper draft whose number the counter no longer holds is not applied", () => {
    const paperDraft: DraftPayload = { ...draft, paper: 61, paperAt: "2026-08-01T09:05" };

    const decision = restoredDraft(
      { cart: emptyCart(), customer: NO_CUSTOMER },
      paperDraft,
      savedDay,
      false,
    );

    expect(decision).toEqual({ kind: "paper-conflict", draft: paperDraft });
  });

  it("a paper conflict is flagged ahead of the age check, not silently swallowed by it", () => {
    const paperDraft: DraftPayload = { ...draft, paper: 61, paperAt: "2026-08-01T09:05" };

    const decision = restoredDraft(
      { cart: emptyCart(), customer: NO_CUSTOMER },
      paperDraft,
      nextDay,
      false,
    );

    expect(decision).toEqual({ kind: "paper-conflict", draft: paperDraft });
  });
});

describe("rekeying a draft at restore (the crash-restore line-identity ruling, 2 Aug 2026)", () => {
  function draftOf(overrides: Partial<Cart> = {}): DraftPayload {
    return {
      cart: { ...cartOf(), ...overrides },
      customer: NO_CUSTOMER,
      paper: null,
      paperAt: null,
      savedAt: "2026-08-01T09:00:00.000Z",
    };
  }

  it("restored keys differ from the saved ones", () => {
    const draft = draftOf();
    const savedKey = draft.cart.lines[0].key;

    const fresh = rekeyDraft(draft);

    expect(fresh.cart.lines[0].key).not.toBe(savedKey);
  });

  it("a key minted after a restore collides with no restored line or leg", () => {
    const draft = draftOf({
      exchange: {
        original: { fy: "26-27", till_seq: 40, doc_number: "26-27/DEO/SAL/40" },
        lines: [legOf("x9")],
      },
    });

    const fresh = rekeyDraft(draft);
    const nextLine = newKey();
    const nextLeg = newLegKey();

    expect(fresh.cart.lines.map((line) => line.key)).not.toContain(nextLine);
    expect((fresh.cart.exchange?.lines ?? []).map((leg) => leg.key)).not.toContain(nextLeg);
  });

  it("an over-cap authorisation still covers its own line after the rekey", () => {
    const line = { ...addPiece(item("8901000000011"), { stock: 3, alternatives: [] }), salesman: 3 };
    const authorisation: Authorisation = {
      user_id: 7,
      name: "Store Manager",
      at: "2026-08-01T09:00:00.000Z",
      asks: [{ kind: OVER_CAP_DISCOUNT, ref: line.key, paise: 500, label: "Line 1" }],
    };
    const draft = draftOf({ lines: [line], authorisation });

    const fresh = rekeyDraft(draft);
    const ask: Ask = {
      kind: OVER_CAP_DISCOUNT,
      ref: fresh.cart.lines[0].key,
      paise: 500,
      label: "Line 1",
    };

    expect(covers(fresh.cart.authorisation, [ask])).toBe(true);
  });

  it("an over-cap authorisation does not cover another restored line after the rekey", () => {
    const first = { ...addPiece(item("8901000000011"), { stock: 3, alternatives: [] }), salesman: 3 };
    const second = { ...addPiece(item("8901000000028"), { stock: 3, alternatives: [] }), salesman: 3 };
    const authorisation: Authorisation = {
      user_id: 7,
      name: "Store Manager",
      at: "2026-08-01T09:00:00.000Z",
      asks: [{ kind: OVER_CAP_DISCOUNT, ref: first.key, paise: 500, label: "Line 1" }],
    };
    const draft = draftOf({ lines: [first, second], authorisation });

    const fresh = rekeyDraft(draft);
    const askOnSecondLine: Ask = {
      kind: OVER_CAP_DISCOUNT,
      ref: fresh.cart.lines[1].key,
      paise: 500,
      label: "Line 2",
    };

    expect(covers(fresh.cart.authorisation, [askOnSecondLine])).toBe(false);
  });

  it("leaves a credit-note ref alone - it is a note number, never a line key", () => {
    const authorisation: Authorisation = {
      user_id: 7,
      name: "Store Manager",
      at: "2026-08-01T09:00:00.000Z",
      asks: [{ kind: UNVERIFIED_NOTE, ref: "CN-100", paise: 20000, label: "CN-100" }],
    };
    const draft = draftOf({ authorisation });

    const fresh = rekeyDraft(draft);

    expect(fresh.cart.authorisation?.asks[0].ref).toBe("CN-100");
  });

  it("rekeys exchange-leg keys too", () => {
    const draft = draftOf({
      exchange: {
        original: { fy: "26-27", till_seq: 40, doc_number: "26-27/DEO/SAL/40" },
        lines: [legOf("x9")],
      },
    });

    const fresh = rekeyDraft(draft);

    expect(fresh.cart.exchange?.lines[0].key).not.toBe("x9");
  });
});
