// The two directions (#180).
//
// Down is reference data and the tests are about *catching up*: a bootstrap
// replaces, a delta patches, and a row that was withdrawn has to leave.
//
// Up is money, and every test is about one of the ticket's promises - drains in
// order, replay-safe, a terminal 4xx halts with a visible reason, nothing
// silently dropped.

import "fake-indexeddb/auto";

import { afterEach, describe, expect, it } from "vitest";

import { META, readMeta } from "./db";
import { commitBill } from "./numbering";
import {
  applyDataset,
  backoffMs,
  clearHalt,
  drainQueue,
  forceBootstrap,
  reconcileRegister,
  syncDown,
} from "./sync";
import { dataset, draft, fakeServer, freshTill, item, refuse, register } from "./testSupport";
import type { QueueHalt } from "./types";

let close = () => undefined as void;
afterEach(() => close());

function till() {
  const made = freshTill();
  close = made.close;
  return made;
}

describe("the dataset landing", () => {
  it("fills the counter's copy from a bootstrap", async () => {
    const { db } = till();

    await applyDataset(
      db,
      dataset({
        items: [item("8901000000011"), item("8901000000012")],
        stock: [{ barcode: "8901000000011", qty: 3 }],
        salesmen: [{ id: 1, code: "ALIE", name: "Ali E.", is_active: true }],
        managers: [{ user_id: 7, name: "R. Kumar", till_pin_hash: "pbkdf2$x" }],
        credit_notes: [
          { number: "26-27/DEO/CRN/4", remaining_paise: 120000, expires_on: "2027-01-30" },
        ],
      }),
    );

    expect(await db.items.count()).toBe(2);
    expect((await db.stock.get("8901000000011"))?.qty).toBe(3);
    expect(await db.salesmen.count()).toBe(1);
    expect(await db.managers.count()).toBe(1);
    expect(await db.creditNotes.count()).toBe(1);
    expect(await readMeta(db, META.cursor, "")).toBe("2026-07-30T10:00:00.000Z");
  });

  it("keeps the same piece in two seasons apart", async () => {
    // A barcode is not a key: the same piece bought twice is two lots at two
    // ticket prices, and a counter that collapsed them would sell one at the
    // other's price.
    const { db } = till();

    await applyDataset(
      db,
      dataset({ items: [item("8901000000011", "FW25"), item("8901000000011", "SS26", 179900)] }),
    );

    expect(await db.items.count()).toBe(2);
  });

  it("patches on a delta instead of replacing", async () => {
    const { db } = till();
    await applyDataset(db, dataset({ items: [item("8901000000011"), item("8901000000012")] }));

    await applyDataset(
      db,
      dataset({ full: false, items: [item("8901000000011", "FW25", 199900)], cursor: "later" }),
    );

    expect(await db.items.count()).toBe(2);
    expect((await db.items.get(["8901000000011", "FW25"]))?.mrp_paise).toBe(199900);
  });

  it("throws away what a bootstrap did not send", async () => {
    // A bootstrap reports nothing as deleted, so anything it does not carry is
    // gone. Merging instead would keep a withdrawn piece on the shelf for ever.
    const { db } = till();
    await applyDataset(db, dataset({ items: [item("8901000000011")] }));

    await applyDataset(db, dataset({ items: [item("8901000000012")] }));

    expect((await db.items.toArray()).map((i) => i.barcode)).toEqual(["8901000000012"]);
  });

  it("takes every season of a withdrawn piece with it", async () => {
    const { db } = till();
    await applyDataset(
      db,
      dataset({
        items: [item("8901000000011", "FW25"), item("8901000000011", "SS26")],
        stock: [{ barcode: "8901000000011", qty: 2 }],
      }),
    );

    await applyDataset(
      db,
      dataset({
        full: false,
        deleted: { items: ["8901000000011"], offers: [], credit_notes: [] },
      }),
    );

    expect(await db.items.count()).toBe(0);
    expect(await db.stock.count()).toBe(0);
  });

  it("stops honouring a credit note the server closed", async () => {
    const { db } = till();
    await applyDataset(
      db,
      dataset({
        credit_notes: [
          { number: "26-27/DEO/CRN/4", remaining_paise: 120000, expires_on: "2027-01-30" },
        ],
      }),
    );

    await applyDataset(
      db,
      dataset({
        full: false,
        deleted: { items: [], offers: [], credit_notes: ["26-27/DEO/CRN/4"] },
      }),
    );

    expect(await db.creditNotes.count()).toBe(0);
  });

  it("replaces the manager list rather than patching it", async () => {
    // The one list that must never be stale: it is a set of override credentials
    // on a shop-floor device, so a rung withdrawn at head office is withdrawn
    // here on the very next response.
    const { db } = till();
    await applyDataset(
      db,
      dataset({
        managers: [
          { user_id: 7, name: "R. Kumar", till_pin_hash: "a" },
          { user_id: 8, name: "S. Devi", till_pin_hash: "b" },
        ],
      }),
    );

    await applyDataset(
      db,
      dataset({ full: false, managers: [{ user_id: 7, name: "R. Kumar", till_pin_hash: "a" }] }),
    );

    expect((await db.managers.toArray()).map((m) => m.user_id)).toEqual([7]);
  });

  it("drops a seller who has left, without a deletion channel", async () => {
    const { db } = till();
    await applyDataset(
      db,
      dataset({ salesmen: [{ id: 1, code: "ALIE", name: "Ali E.", is_active: true }] }),
    );

    await applyDataset(
      db,
      dataset({
        full: false,
        salesmen: [{ id: 1, code: "ALIE", name: "Ali E.", is_active: false }],
      }),
    );

    expect(await db.salesmen.count()).toBe(0);
  });

  it("asks from the cursor it was given, and takes a bootstrap when told to", async () => {
    const { db } = till();
    const server = fakeServer();
    server.datasets = [
      dataset({ cursor: "first" }),
      dataset({ cursor: "second", full: false }),
      dataset({ cursor: "third" }),
    ];

    await syncDown(db, server);
    await syncDown(db, server);
    await forceBootstrap(db);
    await syncDown(db, server);

    expect(server.asked).toEqual(["", "first", ""]);
  });
});

describe("reconciling with the register", () => {
  it("moves a counter that lost its state forward, never back", async () => {
    // A reinstalled till starts at 1 while the shop is on bill 300. Issuing 1
    // again would put two customers' purchases under one Tally key.
    const { db } = till();
    const server = fakeServer();
    server.registers = [register({ fy: "26-27", last_accepted_seq: 300 })];

    await reconcileRegister(db, server, new Date("2026-07-30T12:00:00Z"));

    expect(await readMeta(db, META.nextSeq, 0)).toBe(301);
  });

  it("leaves a till that is ahead alone", async () => {
    // The ordinary state of a busy counter: six bills queued, so the server is
    // six behind. Dragging the counter back would re-issue all six.
    const { db, storeCode } = till();
    for (let i = 0; i < 3; i += 1) await commitBill(db, storeCode, draft());
    const server = fakeServer();
    server.registers = [register({ fy: "26-27", last_accepted_seq: 1 })];

    await reconcileRegister(db, server, new Date("2026-07-30T12:00:00Z"));

    expect(await readMeta(db, META.nextSeq, 0)).toBe(4);
  });

  it("does not reconcile across a financial year", async () => {
    // The two clocks straddle 1 April for a few minutes. A till on the new year's
    // bill 1 that took last year's frontier would jump to 5,001 and stay there.
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft(), new Date("2027-04-01T04:00:00Z"));
    const server = fakeServer();
    server.registers = [register({ fy: "26-27", last_accepted_seq: 5000 })];

    await reconcileRegister(db, server, new Date("2027-04-01T04:00:00Z"));

    expect(await readMeta(db, META.nextSeq, 0)).toBe(2);
    expect(await readMeta(db, META.fy, "")).toBe("27-28");
  });

  it("keeps what the server said, for the screen to show", async () => {
    const { db } = till();
    const server = fakeServer();
    server.registers = [register({ holes: [61], hole_count: 1, series_open: false })];

    await reconcileRegister(db, server, new Date("2026-07-30T12:00:00Z"));

    expect(await readMeta(db, META.register, null)).toMatchObject({
      holes: [61],
      series_open: false,
    });
  });
});

describe("draining the queue", () => {
  it("sends the oldest bill first", async () => {
    const { db, storeCode } = till();
    for (let i = 0; i < 3; i += 1) await commitBill(db, storeCode, draft());
    const server = fakeServer();

    const result = await drainQueue(db, server);

    expect(server.offered.map((b) => b.till_seq)).toEqual([1, 2, 3]);
    expect(result.accepted).toBe(3);
    expect(await db.queue.count()).toBe(0);
  });

  it("sends the till's own bookkeeping to nobody", async () => {
    // `attempts` and the local row id are the queue's, not the contract's.
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft());
    const bodies: unknown[] = [];
    const server = fakeServer();
    const inner = server.postSale;
    server.postSale = async (bill) => {
      const { billBody } = await import("./transport");
      bodies.push(billBody(bill));
      return inner(bill);
    };

    await drainQueue(db, server);

    expect(Object.keys(bodies[0] as object)).not.toContain("attempts");
    expect(Object.keys(bodies[0] as object)).toContain("idempotency_uuid");
  });

  it("drops a bill the server recognises as a replay", async () => {
    // The server answers 200 with the original bill and writes nothing. Both
    // answers mean the same thing to the queue: this bill is on the books.
    const { db, storeCode } = till();
    const bill = await commitBill(db, storeCode, draft());
    const server = fakeServer({
      answer: (b) => ({ doc_number: b.doc_number, id: 1, flags: [] }),
    });

    await drainQueue(db, server);
    await drainQueue(db, server);

    expect(server.offered).toHaveLength(1);
    expect(await db.queue.count()).toBe(0);
    expect(bill.idempotency_uuid).toBeTruthy();
  });

  it("keeps a bill and retries for ever when the line is down", async () => {
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft());
    const server = fakeServer({ postSale: async () => refuse(0, "NETWORK", "No connection.") });

    const first = await drainQueue(db, server);
    const second = await drainQueue(db, server);

    expect(await db.queue.count()).toBe(1);
    expect((await db.queue.orderBy("id").first())?.attempts).toBe(2);
    expect(await readMeta<QueueHalt | null>(db, META.halt, null)).toBeNull();
    expect([first.retryAfterMs, second.retryAfterMs]).toEqual([5_000, 10_000]);
  });

  it("halts, names the bill and stops when the server refuses one", async () => {
    const { db, storeCode } = till();
    const refused = await commitBill(db, storeCode, draft());
    await commitBill(db, storeCode, draft());
    const server = fakeServer({
      postSale: async () =>
        refuse(409, "BILL_NO_TAKEN", "That bill number is already on another sale."),
    });

    const result = await drainQueue(db, server);

    expect(result.halt?.doc_number).toBe(refused.doc_number);
    expect(result.halt?.code).toBe("BILL_NO_TAKEN");
    expect(result.halt?.message).toContain("already on another sale");
    // Nothing dropped, nothing skipped: both bills are still here.
    expect(await db.queue.count()).toBe(2);
  });

  it("stays halted until a human clears it", async () => {
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft());
    const refusing = fakeServer({ postSale: async () => refuse(422, "TENDER_MISMATCH") });
    await drainQueue(db, refusing);

    const willing = fakeServer();
    const blocked = await drainQueue(db, willing);
    await clearHalt(db);
    const after = await drainQueue(db, willing);

    expect(willing.offered).toHaveLength(1);
    expect(blocked.accepted).toBe(0);
    expect(after.accepted).toBe(1);
  });

  it("does not halt over an expired session", async () => {
    // A 401 is the token, not the bill. Halting a counter's queue over one would
    // need a manager to clear something that fixed itself.
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft());
    const server = fakeServer({ postSale: async () => refuse(401, "NOT_AUTHENTICATED") });

    const result = await drainQueue(db, server);

    expect(result.halt).toBeNull();
    expect(result.retryAfterMs).toBe(5_000);
  });

  it("does not halt over a server fault", async () => {
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft());
    const server = fakeServer({ postSale: async () => refuse(500, "SERVER_ERROR") });

    expect((await drainQueue(db, server)).halt).toBeNull();
  });

  it("carries the server's flags back for the Dashboard", async () => {
    // A hole, an offer mismatch, a bill that arrived before the goods did. They
    // belong on an action queue, never at the counter mid-sale.
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft());
    const server = fakeServer({
      answer: (b) => ({ doc_number: b.doc_number, id: 1, flags: ["number_hole"] }),
    });

    expect((await drainQueue(db, server)).flags).toEqual(["number_hole"]);
  });

  it("runs one drain at a time", async () => {
    // Three triggers overlap by design - a timer, the online event and a button.
    // Two drains at once would race to delete the same row and to write the halt.
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft());
    let release = () => undefined as void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const server = fakeServer();
    const inner = server.postSale;
    server.postSale = async (bill) => {
      await gate;
      return inner(bill);
    };

    const both = Promise.all([drainQueue(db, server), drainQueue(db, server)]);
    release();
    await both;

    expect(server.offered).toHaveLength(1);
  });
});

describe("the backoff", () => {
  it("doubles from five seconds and stops at a minute", () => {
    expect([1, 2, 3, 4, 5, 9].map(backoffMs)).toEqual([5_000, 10_000, 20_000, 40_000, 60_000, 60_000]);
  });
});
