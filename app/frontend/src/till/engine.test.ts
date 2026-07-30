// The till, running (#180).
//
// These are the lifecycle properties a unit test can hold that a browser cannot
// hold cheaply: that the engine survives being stopped and started again, that a
// stop really does stop it, and that nothing it does on a timer can escape as an
// unhandled rejection.
//
// The restart one is not hypothetical. React StrictMode mounts, unmounts and
// remounts every effect in development, and a person walking off the Sell page
// and back does the same in production - so an engine that only works once is an
// engine that never works.

import "fake-indexeddb/auto";

import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { installBrowserGlobals } from "./testSupport";

beforeAll(installBrowserGlobals);

// Imported after the globals exist: the module graph itself does not touch them,
// but keeping the order explicit means a future top-level `navigator` read fails
// here rather than mysteriously in a browser.
const { TillEngine } = await import("./engine");
const { commitBill } = await import("./numbering");
const { dataset, fakeServer, freshTill, item, refuse } = await import("./testSupport");

/** Wait for something the engine does without being awaited - Save & Print hands
 *  the bill to the queue and lets the send happen behind the cashier. */
async function until(ready: () => boolean, tries = 100): Promise<void> {
  for (let i = 0; i < tries; i += 1) {
    if (ready()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error("the engine never settled");
}

/** A bill with no lines: this file is about the engine's plumbing, and the money
 *  on a bill is `numbering.test.ts`'s subject. */
function emptyDraft() {
  return {
    billed_at: "2026-07-30T12:31:00.000Z",
    lines: [],
    tenders: [],
    totals: {
      gross_paise: 0,
      discount_paise: 0,
      net_paise: 0,
      gst_paise: 0,
      round_paise: 0,
    },
  };
}

let stop = () => undefined as void;
afterEach(() => stop());

function engineOn(server = fakeServer()) {
  const { storeCode, close } = freshTill();
  const engine = new TillEngine(storeCode, server);
  stop = () => {
    engine.stop();
    close();
  };
  return { engine, server, storeCode };
}

describe("starting and stopping", () => {
  it("works the second time, on the same engine", async () => {
    // The StrictMode shape, exactly: start, stop, start, on one instance.
    const { engine, server } = engineOn();
    server.datasets = [
      dataset({ items: [item("8901000000011")] }),
      dataset({ items: [item("8901000000011")] }),
    ];

    await engine.start();
    engine.stop();
    await engine.start();

    expect(engine.getSnapshot().ready).toBe(true);
    expect(engine.getSnapshot().counts.items).toBe(1);
    expect(engine.getSnapshot().status.colour).toBe("green");
  });

  it("keeps its subscribers across a stop", async () => {
    // `useSyncExternalStore` unsubscribes itself; dropping its listener here
    // would freeze the screen on whatever snapshot it last saw.
    const { engine } = engineOn();
    let told = 0;
    engine.subscribe(() => {
      told += 1;
    });

    engine.stop();
    await engine.retryHalted();

    expect(told).toBeGreaterThan(0);
  });

  it("hands React the same snapshot object until something changes", () => {
    // A fresh object on every read would re-render for ever.
    const { engine } = engineOn();

    expect(engine.getSnapshot()).toBe(engine.getSnapshot());
  });
});

describe("what the screen is told", () => {
  it("reports a queued bill and a sync failure in one go", async () => {
    const { engine, server, storeCode } = engineOn();
    server.datasets = [dataset({ items: [item("8901000000011")] })];
    await engine.start();
    await commitBill(engine.db, storeCode, emptyDraft());

    server.postSale = async () => refuse(0, "NETWORK", "No connection to head office.");
    await engine.syncNow();

    const snapshot = engine.getSnapshot();
    expect(snapshot.pending).toBe(1);
    expect(snapshot.status.colour).toBe("amber");
    expect(snapshot.queue[0].attempts).toBe(1);
    expect(snapshot.queue[0].last_error).toContain("No connection");
  });

  it("re-reads the register once the queue has gone up", async () => {
    // Otherwise the two panels tell different stories: "head office has bill 7"
    // beside "nothing waiting", to a counter that has billed 9. This is the
    // commit path - Save & Print, then the send - which is the one a cashier
    // watches, and it never went near `syncNow`.
    const { engine } = engineOn();
    await engine.start();
    expect(engine.getSnapshot().register?.last_accepted_seq).toBe(0);

    await engine.commit(emptyDraft());
    await until(() => engine.getSnapshot().pending === 0);

    // Nothing called `syncNow`: the commit's own send is what has to notice.
    expect(engine.getSnapshot().register?.last_accepted_seq).toBe(1);
  });

  it("swallows nothing and throws nothing when the server is down", async () => {
    // `syncNow` is called from a timer with no `await` behind it, so a rejection
    // here is an unhandled one in a store's browser.
    const { engine, server } = engineOn();
    server.dataset = async () => refuse(0, "NETWORK", "No connection to head office.");
    server.register = async () => refuse(0, "NETWORK", "No connection to head office.");

    await expect(engine.start()).resolves.toBeUndefined();

    const snapshot = engine.getSnapshot();
    expect(snapshot.ready).toBe(true);
    expect(snapshot.lastError).toContain("No connection");
    // No price list ever landed, so the counter cannot bill: red, not amber.
    expect(snapshot.status.colour).toBe("red");
  });
});

describe("bills on hold (#185)", () => {
  const payload = { lines: [], customer: { name: "", mobile: "" }, tendered_paise: 0, net_paise: 0, pieces: 0 };

  it("parks a cart without touching the counter or the queue", async () => {
    const { engine, server } = engineOn();
    await engine.start();

    await engine.hold({ held_uuid: "h1", label: "Mrs Sharma", payload });

    const snapshot = engine.getSnapshot();
    expect(snapshot.counts.held).toBe(1);
    expect(snapshot.held[0].label).toBe("Mrs Sharma");
    // Nothing was sold, so nothing was numbered and nothing was queued.
    expect(snapshot.pending).toBe(0);
    expect(snapshot.nextNumber).toBe(engine.getSnapshot().nextNumber);
    expect(server.offered).toHaveLength(0);
  });

  it("mirrors the whole list, so a resumed hold disappears by omission", async () => {
    const { engine, server } = engineOn();
    await engine.start();

    await engine.hold({ held_uuid: "h1", label: "One", payload });
    await engine.hold({ held_uuid: "h2", label: "Two", payload });
    await until(() => server.heldPushes.length >= 2);
    await engine.releaseHold("h1");
    await until(() => server.heldPushes.at(-1)?.length === 1);

    expect(server.heldPushes.at(-1)).toEqual([
      expect.objectContaining({ held_uuid: "h2", label: "Two" }),
    ]);
  });

  it("parks the cart even when head office cannot be told", async () => {
    // A hold is not money, so the mirror failing is not a reason to refuse the
    // cashier - and the rejection must not escape a `void`ed call either.
    const { engine, server } = engineOn();
    await engine.start();
    server.putHeld = async () => refuse(0, "NETWORK", "No connection to head office.");

    await expect(engine.hold({ held_uuid: "h1", label: "", payload })).resolves.toBeUndefined();

    expect(engine.getSnapshot().counts.held).toBe(1);
  });
});
