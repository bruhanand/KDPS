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

import { addPiece, emptyCart } from "./cart";
import type { Cart } from "./cart";
import type { TillDb } from "./db";
import { clearDraft, persistDraft, readDraft, restoredCart, restoredCustomer } from "./draft";
import type { DraftPayload } from "./draft";
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
  it("reproduces the cart, the customer and the paper number exactly", async () => {
    const cart = cartOf();
    const customer: TillCustomer = { name: "Mrs Sharma", mobile: "9876543210", gstin: "" };

    await persistDraft(db, cart, customer, 305);

    expect(await readDraft(db)).toMatchObject({ cart, customer, paper: 305 });
  });

  it("is nothing at all until something has been saved", async () => {
    expect(await readDraft(db)).toBeNull();
  });

  it("overwrites what was there before - one row, not a history", async () => {
    await persistDraft(db, cartOf(), NO_CUSTOMER, null);
    const second = { ...cartOf(), lines: [] };

    await persistDraft(db, second, NO_CUSTOMER, null);

    expect((await readDraft(db))?.cart.lines).toHaveLength(0);
  });

  it("clears on commit success, New bill, and Hold", async () => {
    await persistDraft(db, cartOf(), NO_CUSTOMER, null);

    await clearDraft(db);

    expect(await readDraft(db)).toBeNull();
  });

  it("logs and carries on rather than blocking the bill on a failed write", async () => {
    const failing = vi.spyOn(db.draft, "put").mockRejectedValue(new Error("storage full"));
    const logged = vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(persistDraft(db, cartOf(), NO_CUSTOMER, null)).resolves.toBeUndefined();

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

describe("landing the read back on screen (the mount race)", () => {
  const draft: DraftPayload = {
    cart: cartOf(),
    customer: { name: "Mrs Sharma", mobile: "9876543210", gstin: "" },
    paper: null,
    savedAt: "2026-08-01T09:00:00.000Z",
  };

  it("applies the draft onto a screen nothing has touched yet", () => {
    expect(restoredCart(emptyCart(), draft)).toEqual(draft.cart);
    expect(restoredCustomer(NO_CUSTOMER, draft)).toEqual(draft.customer);
  });

  it("drops a read that lost the race to a piece already scanned", () => {
    // The read was issued at mount; a piece landing on the bill before it comes
    // back is realer than what it would restore, so the scan stands.
    const alreadyScanning = { ...emptyCart(), lines: [cartOf().lines[0]] };

    expect(restoredCart(alreadyScanning, draft)).toBe(alreadyScanning);
  });

  it("drops a read that lost the race to the exchange hand-off", () => {
    // `Billing.tsx` takes a parked exchange on mount too, in no guaranteed order
    // against this read. Landing second must not erase it.
    const withExchange: Cart = {
      ...emptyCart(),
      exchange: { original: { fy: "26-27", till_seq: 40, doc_number: "26-27/DEO/SAL/40" }, lines: [] },
    };

    expect(restoredCart(withExchange, draft)).toBe(withExchange);
  });

  it("leaves a customer field somebody already typed alone", () => {
    const typing: TillCustomer = { name: "Sharma Traders", mobile: "", gstin: "" };

    expect(restoredCustomer(typing, draft)).toBe(typing);
  });
});
