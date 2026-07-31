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
const { CounterLock, markTillSeen } = await import("./guard");
const { commitBill } = await import("./numbering");
const { dataset, fakeServer, freshTill, item, refuse, register } = await import("./testSupport");
const { emptyPayment } = await import("./tender");

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

function engineOn(server = fakeServer(), lock?: InstanceType<typeof CounterLock>) {
  const { storeCode, close } = freshTill();
  const engine = new TillEngine(storeCode, server, lock);
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

describe("a counter that lost its local data (#189)", () => {
  /** An engine on a store this device has billed at before. */
  function afterALoss() {
    const { storeCode, close } = freshTill();
    // The marker a previous session left, with an empty database behind it -
    // which is exactly what an eviction looks like on the next store open.
    markTillSeen(storeCode);
    const server = fakeServer();
    const engine = new TillEngine(storeCode, server);
    stop = () => {
      engine.stop();
      close();
    };
    return { engine, server, storeCode };
  }

  it("goes red and refuses to bill, even after a clean sync", async () => {
    // The sync at store open succeeds - there is nothing wrong with the line -
    // and the till still may not bill, because its counter went back to 1 while
    // the store's series carried on without it.
    const { engine, server } = afterALoss();
    server.registers = [register({ last_accepted_seq: 73 })];

    await engine.start();

    const snapshot = engine.getSnapshot();
    expect(snapshot.storageLost).toBe(true);
    expect(snapshot.status.colour).toBe("red");
    expect(snapshot.blocked).toContain("bill number");
    await expect(engine.commit(emptyDraft())).rejects.toThrow(/bill number/);
  });

  it("lifts the block only when somebody recovers it, and says where the counter is", async () => {
    const { engine, server } = afterALoss();
    server.registers = [register({ last_accepted_seq: 73 }), register({ last_accepted_seq: 73 })];
    await engine.start();

    await engine.recover();

    const snapshot = engine.getSnapshot();
    expect(snapshot.storageLost).toBe(false);
    expect(snapshot.blocked).toBe("");
    // No silent counter reset: the till resumes above what the server holds
    // rather than starting again at 1.
    expect(snapshot.nextNumber).toContain("/SAL/74");
    await expect(engine.commit(emptyDraft())).resolves.toBeDefined();
  });

  it("takes the whole dataset again, not a delta", async () => {
    // A cursor that survived the loss would leave the counter pricing from a
    // price list that is missing whatever changed while it was gone.
    const { engine, server } = afterALoss();
    await engine.start();
    server.asked = [];

    await engine.recover();

    expect(server.asked).toEqual([""]);
  });

  it("stays blocked when the recovery cannot reach head office", async () => {
    // A till that lost its numbering and has no line has nothing to bill from.
    // The refusal goes back to the person who pressed the button.
    const { engine, server } = afterALoss();
    await engine.start();
    server.dataset = async () => refuse(0, "NETWORK", "No connection to head office.");

    await expect(engine.recover()).rejects.toThrow(/No connection/);

    expect(engine.getSnapshot().blocked).toContain("bill number");
  });
});

describe("a second window on the same counter (#189)", () => {
  /** Two engines on one store, sharing one browser's worth of locks. */
  function twoTabs() {
    const taken = new Set<string>();
    const manager = () => ({
      async request(name: string, _o: unknown, callback: (lock: unknown | null) => Promise<void>) {
        if (taken.has(name)) {
          await callback(null);
          return;
        }
        taken.add(name);
        void callback({}).then(() => taken.delete(name));
      },
    });
    const { storeCode, close } = freshTill();
    const server = fakeServer();
    const first = new TillEngine(storeCode, server, new CounterLock(storeCode, manager()));
    const second = new TillEngine(storeCode, server, new CounterLock(storeCode, manager()));
    stop = () => {
      first.stop();
      second.stop();
      close();
    };
    return { first, second };
  }

  it("bills from the first and refuses the second", async () => {
    const { first, second } = twoTabs();

    await first.start();
    await second.start();

    expect(first.getSnapshot().blocked).toBe("");
    expect(second.getSnapshot().blocked).toContain("another tab");
    expect(second.getSnapshot().status.colour).toBe("red");
    await expect(second.commit(emptyDraft())).rejects.toThrow(/another tab/);
    await expect(first.commit(emptyDraft())).resolves.toBeDefined();
  });

  it("hands the counter over when the first window closes", async () => {
    const { first, second } = twoTabs();
    await first.start();
    await second.start();

    first.stop();
    await new Promise((settled) => setTimeout(settled, 0));
    await second.refresh();

    expect(second.getSnapshot().blocked).toBe("");
  });
});

describe("moving the counter to this machine (#189)", () => {
  it("resumes above what head office holds, and lists what never arrived", async () => {
    const { engine, server } = engineOn();
    await engine.start();
    server.registers = [register({ last_accepted_seq: 73, holes: [61], hole_count: 1 })];
    server.handover = async (reason: string) => {
      server.handovers.push(reason);
      return { resume_from_seq: 74, unsynced_hint: [61], hole_count: 1 };
    };

    const state = await engine.handOver("counter machine replaced");

    expect(server.handovers).toEqual(["counter machine replaced"]);
    expect(state.unsynced_hint).toEqual([61]);
    expect(engine.getSnapshot().nextNumber).toContain("/SAL/74");
    expect(engine.getSnapshot().handover?.resume_from_seq).toBe(74);
  });

  it("ticks a bill off the list when it is keyed back in, and keeps the tick", async () => {
    // The tick has to outlive the queue: a re-entered bill leaves it the moment
    // the server takes it, and the list somebody is working down must not lose
    // its place underneath them. It also has to outlive the *list* - putting the
    // job away is not the same as saying the receipts were never entered.
    const { engine, server } = engineOn();
    await engine.start();
    server.handover = async () => ({ resume_from_seq: 74, unsynced_hint: [61, 62], hole_count: 2 });
    server.registers = [register({ last_accepted_seq: 73 })];
    await engine.handOver("machine died");

    await engine.reenterFromPaper(emptyDraft(), 61);
    await until(() => engine.getSnapshot().pending === 0);
    expect(engine.getSnapshot().paperEntered).toEqual([61]);

    await engine.clearHandover();

    expect(engine.getSnapshot().handover).toBe(null);
    expect(engine.getSnapshot().paperEntered).toEqual([61]);
    await expect(engine.reenterFromPaper(emptyDraft(), 61)).rejects.toThrow(/already/);
  });

  it("leaves the counter alone when the two clocks disagree about the year", async () => {
    // 1 April, and a shop-floor clock a day out. `reconcileRegister` declines to
    // move a counter against another year's frontier, and the handover must not
    // step around that guard: a till standing at 25-26 bill 305 reset to bill 1
    // would collide with every number it has already printed.
    const { engine, server } = engineOn();
    await engine.start();
    await engine.commit(emptyDraft());
    await until(() => engine.getSnapshot().pending === 0);
    const before = engine.getSnapshot().nextNumber;
    server.registers = [register({ fy: "99-00", last_accepted_seq: 5000 })];
    server.handover = async () => ({ resume_from_seq: 5001, unsynced_hint: [], hole_count: 0 });

    await engine.handOver("machine died");

    expect(engine.getSnapshot().nextNumber).toBe(before);
  });

  it("tells the manager when head office refuses, rather than moving anything", async () => {
    // A handover that failed quietly would leave somebody believing the counter
    // had moved, and the next bill would take a number the old machine printed.
    const { engine, server } = engineOn();
    await engine.start();
    const before = engine.getSnapshot().nextNumber;
    server.handover = async () => refuse(403, "TILL_SCOPE", "This login is not a counter.");

    await expect(engine.handOver("machine died")).rejects.toThrow(/not a counter/);

    expect(engine.getSnapshot().nextNumber).toBe(before);
    expect(engine.getSnapshot().handover).toBe(null);
  });
});

describe("bills on hold (#185)", () => {
  const payload = {
    lines: [],
    customer: { name: "", mobile: "", gstin: "" },
    payment: emptyPayment(),
    net_paise: 0,
    pieces: 0,
  };

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
