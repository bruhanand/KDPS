// Parking a bill and picking it up again (#185, grill Q13).
//
// Three properties, and they are the three the ticket's acceptance criteria name:
//
//   · a hold moves nothing - no number, no shelf, no queue;
//   · a retrieved hold is priced at *today's* world, not the world it was parked
//     in, because a kept bill carries to the next day at that day's rules;
//   · nothing expires on its own. The only function that produces a list of stale
//     holds hands it to a person, and the only two ways one leaves are a person
//     resuming it and a person letting it go.

import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it } from "vitest";

import type { Cart } from "./cart";
import { META, readMeta } from "./db";
import type { HeldBill, TillDb } from "./db";
import {
  describeHold,
  dropHold,
  heldPayload,
  holdsToReview,
  keepHold,
  listHolds,
  localDay,
  mirrorRow,
  parkHold,
  restoreHold,
} from "./held";
import type { HeldPayload } from "./held";
import { freshTill, item, season } from "./testSupport";
import { emptyPayment } from "./tender";

const WORLD = {
  items: [item("8901000000011", "FW25", 149900)],
  stock: [{ barcode: "8901000000011", qty: 3 }],
  seasons: [season("FW25", 2)],
};

function cartOf(over: Partial<Cart["lines"][number]> = {}): Cart {
  return {
    lines: [
      {
        key: "l1",
        barcode: "8901000000011",
        season: "FW25",
        design: "SHIRT-01",
        brand: "MUFTI",
        item: "Shirt",
        size: "M",
        color: "NAVY",
        hsn: "6205",
        no_discount: false,
        mrp_paise: 149900,
        needs_price: false,
        qty: 1,
        disc_paise: 0,
        salesman: 3,
        alternatives: WORLD.items,
        stock: 3,
        manual_desc: "",
        sold_before_inward: false,
        ...over,
      },
    ],
    payment: { ...emptyPayment(), cash_received_paise: 200000 },
    authorisation: null,
    exchange: null,
  };
}

function payloadOf(cart = cartOf()): HeldPayload {
  return heldPayload(cart, { name: "Mrs Sharma", mobile: "9876543210", gstin: "" }, {
    net_paise: 149900,
    pieces: 1,
  });
}

async function park(db: TillDb, over: Partial<Parameters<typeof parkHold>[1]> = {}) {
  return parkHold(db, {
    held_uuid: `h${Math.random().toString(36).slice(2)}`,
    label: "Mrs Sharma",
    payload: payloadOf(),
    ...over,
  });
}

let till: ReturnType<typeof freshTill>;
let db: TillDb;

beforeEach(() => {
  till = freshTill();
  db = till.db;
});

describe("parking", () => {
  it("holds the cart and nothing else", async () => {
    await park(db);

    expect(await db.held.count()).toBe(1);
    // The three tables a sale would have moved. A hold that took a number or a
    // piece off the shelf would be a sale that nobody was charged for.
    expect(await db.queue.count()).toBe(0);
    expect(await readMeta(db, META.nextSeq, 1)).toBe(1);
    expect(await db.stock.get("8901000000011")).toBeUndefined();
  });

  it("keeps the cart's lines and drops what the counter can work out again", async () => {
    const held = await park(db);
    const payload = held.payload;

    expect(payload.lines).toHaveLength(1);
    expect(payload.lines[0].barcode).toBe("8901000000011");
    // `alternatives` is the item master and `stock` is the shelf: both are read
    // again on retrieval, and parking them would send a stale shelf to the server.
    expect(payload.lines[0]).not.toHaveProperty("alternatives");
    expect(payload.lines[0]).not.toHaveProperty("stock");
  });

  it("lists holds oldest first, the order somebody parked them in", async () => {
    await park(db, { held_uuid: "second", held_at: "2026-07-31T12:00:00.000Z" });
    await park(db, { held_uuid: "first", held_at: "2026-07-31T09:00:00.000Z" });

    expect((await listHolds(db)).map((h) => h.held_uuid)).toEqual(["first", "second"]);
  });

  it("names an unlabelled hold by what is in it", async () => {
    const held = await park(db, { label: "" });
    expect(describeHold(held)).toBe("1 piece");
  });
});

describe("picking it up", () => {
  it("prices the line at today's ticket price, not the one it was parked at", async () => {
    const held = await park(db);
    const marked = {
      ...WORLD,
      items: [{ ...WORLD.items[0], mrp_paise: 99900 }],
    };

    const restored = restoreHold(held, marked);

    expect(restored.cart.lines[0].mrp_paise).toBe(99900);
    expect(restored.staleLines).toBe(0);
  });

  it("re-reads the shelf and the other seasons rather than trusting the hold", async () => {
    const held = await park(db);

    const restored = restoreHold(held, { ...WORLD, stock: [{ barcode: "8901000000011", qty: 1 }] });

    expect(restored.cart.lines[0].stock).toBe(1);
    expect(restored.cart.lines[0].alternatives).toHaveLength(1);
  });

  it("keeps a price a human typed off the tag", async () => {
    // The books have no MRP for this piece, so a person typed one. Nobody else
    // knows it, and re-deriving it from a master that has nothing would put a
    // garment on the bill at nothing.
    const held = await park(db, {
      payload: payloadOf(cartOf({ needs_price: true, mrp_paise: 79900 })),
    });

    const restored = restoreHold(held, {
      ...WORLD,
      items: [{ ...WORLD.items[0], mrp_paise: null }],
    });

    expect(restored.cart.lines[0].mrp_paise).toBe(79900);
    expect(restored.cart.lines[0].needs_price).toBe(true);
  });

  it("keeps the parked price for a piece the counter no longer carries, and says so", async () => {
    const held = await park(db);

    const restored = restoreHold(held, { items: [], stock: [], seasons: [] });

    expect(restored.cart.lines[0].mrp_paise).toBe(149900);
    expect(restored.staleLines).toBe(1);
  });

  it("brings a sold-before-inward line back as one, and does not call it stale", async () => {
    // A piece the books never knew is not a piece the shop stopped carrying, so
    // the "check the lines the counter no longer stocks" warning is not about it.
    const held = await park(db, {
      payload: payloadOf(
        cartOf({
          barcode: "8909999999901",
          season: "",
          brand: "",
          item: "",
          hsn: "",
          needs_price: true,
          manual_desc: "Blue check shirt",
          sold_before_inward: true,
        }),
      ),
    });

    const restored = restoreHold(held, WORLD);

    expect(restored.cart.lines[0].manual_desc).toBe("Blue check shirt");
    expect(restored.cart.lines[0].sold_before_inward).toBe(true);
    expect(restored.staleLines).toBe(0);
  });

  it("stops calling it sold-before-inward once the paperwork has landed", async () => {
    // The PT arrived while the bill was parked: the cohort prices it now, so it
    // is an ordinary line and nothing goes into the costing queue (#186).
    const held = await park(db, {
      payload: payloadOf(
        cartOf({
          season: "",
          brand: "",
          needs_price: true,
          manual_desc: "Blue check shirt",
          sold_before_inward: true,
        }),
      ),
    });

    const restored = restoreHold(held, WORLD);

    expect(restored.cart.lines[0].sold_before_inward).toBe(false);
    expect(restored.cart.lines[0].brand).toBe("MUFTI");
  });

  it("takes a cart parked by a build that had no manual line in it", async () => {
    // Holds outlive deploys, and `undefined` reaching the close check would be a
    // description nobody typed.
    const held = await park(db);
    const line = held.payload.lines[0] as Record<string, unknown>;
    delete line.manual_desc;
    delete line.sold_before_inward;

    const restored = restoreHold(held, WORLD);

    expect(restored.cart.lines[0].manual_desc).toBe("");
    expect(restored.cart.lines[0].sold_before_inward).toBe(false);
  });

  it("brings the customer back with the cart", async () => {
    const held = await park(db);

    const restored = restoreHold(held, WORLD);

    expect(restored.customer).toEqual({ name: "Mrs Sharma", mobile: "9876543210", gstin: "" });
    expect(restored.cart.payment.cash_received_paise).toBe(200000);
  });

  it("brings a business customer's GSTIN back too (#187)", async () => {
    // A bill parked half-billed and picked up ten minutes later is the same
    // customer's. A hold that dropped the registration would turn their tax
    // invoice back into a retail bill with nobody at the counter noticing.
    const held = await park(db, {
      payload: heldPayload(
        cartOf(),
        { name: "Sharma Traders", mobile: "", gstin: "10AABCU9603R1Z2" },
        { net_paise: 149900, pieces: 1 },
      ),
    });

    expect(restoreHold(held, WORLD).customer.gstin).toBe("10AABCU9603R1Z2");
  });

  it("leaves the list when it is taken, and takes nothing else with it", async () => {
    const held = await park(db);

    await dropHold(db, held.held_uuid);

    expect(await db.held.count()).toBe(0);
    expect(await db.queue.count()).toBe(0);
  });
});

describe("day close", () => {
  // Relative to the clock the test runs on, because "before today" is the whole
  // subject: a fixed timestamp would pass or fail depending on the machine's date
  // and its offset from UTC.
  const YESTERDAY = new Date(Date.now() - 36 * 60 * 60_000).toISOString();

  function heldOn(at: string, over: Partial<HeldBill> = {}): HeldBill {
    return {
      held_uuid: "h1",
      label: "",
      held_at: at,
      expires_policy: "today",
      payload: payloadOf(),
      ...over,
    };
  }

  it("puts yesterday's holds to the store", () => {
    const stale = heldOn(YESTERDAY);
    const fresh = heldOn(new Date().toISOString(), { held_uuid: "h2" });

    expect(holdsToReview([stale, fresh]).map((h) => h.held_uuid)).toEqual(["h1"]);
  });

  it("stops asking once the store has answered today", async () => {
    await db.held.put(heldOn(YESTERDAY));

    await keepHold(db, "h1");

    const holds = await listHolds(db);
    expect(holds[0].expires_policy).toBe("kept");
    expect(holdsToReview(holds)).toEqual([]);
  });

  it("asks again tomorrow, so a kept hold is never invisible", async () => {
    await db.held.put(heldOn(YESTERDAY));
    await keepHold(db, "h1");

    const holds = await listHolds(db);
    const tomorrow = localDay(new Date(Date.now() + 24 * 60 * 60_000));

    expect(holdsToReview(holds, tomorrow)).toHaveLength(1);
  });

  it("expires nothing by itself - reviewing is a list, not a delete", async () => {
    await db.held.put(heldOn("2026-01-01T09:00:00.000Z"));

    const holds = await listHolds(db);
    holdsToReview(holds);

    expect(await db.held.count()).toBe(1);
  });

  it("reads the shop's own day, not the UTC one", () => {
    // 8pm IST on the 31st is 14:30 UTC the same day; an evening either side of
    // midnight UTC has to be one shop day, or a bill parked at closing time is
    // "from before today" while the same shift is still running.
    const evening = new Date("2026-07-31T14:30:00.000Z");
    expect(localDay(evening)).toBe(localDay(new Date(evening.getTime() + 60_000)));
  });
});

describe("the mirror", () => {
  it("sends the contract's columns and keeps the day-close answer at home", async () => {
    await db.held.put({
      held_uuid: "h1",
      label: "Mrs Sharma",
      held_at: "2026-07-31T09:00:00.000Z",
      expires_policy: "kept",
      payload: payloadOf(),
      reviewed_on: "2026-07-31",
    });

    const row = mirrorRow((await listHolds(db))[0]);

    expect(Object.keys(row).sort()).toEqual([
      "expires_policy",
      "held_at",
      "held_uuid",
      "label",
      "payload",
    ]);
  });
});
