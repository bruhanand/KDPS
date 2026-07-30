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
    await commitBill(engine.db, storeCode, {
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
    });

    server.postSale = async () => refuse(0, "NETWORK", "No connection to head office.");
    await engine.syncNow();

    const snapshot = engine.getSnapshot();
    expect(snapshot.pending).toBe(1);
    expect(snapshot.status.colour).toBe("amber");
    expect(snapshot.queue[0].attempts).toBe(1);
    expect(snapshot.queue[0].last_error).toContain("No connection");
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
