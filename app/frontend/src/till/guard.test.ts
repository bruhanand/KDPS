// The counter's two hardware-shaped worries (#189).
//
// Both of them come down to the same question - does this tab know which bill
// number is next - and both answers are things a unit test can hold that a
// browser cannot hold cheaply: you cannot ask Chrome to evict IndexedDB on
// demand, and proving that a second tab is refused means being two tabs.

import { beforeEach, describe, expect, it } from "vitest";

import { installBrowserGlobals } from "./testSupport";

installBrowserGlobals();

const { CounterLock, billingBlock, detectStorageLoss, lostKey, markTillSeen, seenKey } =
  await import("./guard");
type LockManagerLike = import("./guard").LockManagerLike;

/** A database with `n` rows in `meta`, which is all the detector reads. */
function withMeta(n: number) {
  return { meta: { count: async () => n } };
}

/**
 * One browser's worth of Web Locks, shared by however many "tabs" a test makes.
 *
 * Exclusive and `ifAvailable`-only, which is the whole of what `CounterLock`
 * asks for: the name is either free or it is not, and a request that finds it
 * taken is answered with null rather than queued.
 */
function fakeLocks(): { manager: () => LockManagerLike } {
  const taken = new Set<string>();
  return {
    manager: () => ({
      async request(name, _options, callback) {
        if (taken.has(name)) {
          await callback(null);
          return;
        }
        taken.add(name);
        // Not awaited: the callback holds the lock until it settles, and the
        // release is what settles it. Awaiting here would deadlock exactly the
        // way awaiting the real one does.
        void callback({}).then(() => taken.delete(name));
      },
    }),
  };
}

beforeEach(() => localStorage.clear());

describe("the storage sentinel", () => {
  it("says nothing about a device that has never been a till", async () => {
    // A brand-new counter has an empty database too, and telling it that it lost
    // data would put every first-ever store open behind a recovery.
    expect(await detectStorageLoss(withMeta(0), "DEO")).toBe(false);
  });

  it("notices a till whose database was thrown away", async () => {
    markTillSeen("DEO");

    expect(await detectStorageLoss(withMeta(0), "DEO")).toBe(true);
  });

  it("leaves a till with its data alone", async () => {
    markTillSeen("DEO");

    expect(await detectStorageLoss(withMeta(4), "DEO")).toBe(false);
  });

  it("remembers the loss across a reload", async () => {
    // The trap this exists for: the first sync after a loss writes rows, so on
    // the next reload the database is no longer empty and the loss would appear
    // never to have happened - lifting the block with nobody told.
    markTillSeen("DEO");
    expect(await detectStorageLoss(withMeta(0), "DEO")).toBe(true);

    expect(await detectStorageLoss(withMeta(9), "DEO")).toBe(true);
  });

  it("forgets it once the counter has been recovered", async () => {
    markTillSeen("DEO");
    await detectStorageLoss(withMeta(0), "DEO");

    markTillSeen("DEO");

    expect(localStorage.getItem(lostKey("DEO"))).toBe(null);
    expect(await detectStorageLoss(withMeta(9), "DEO")).toBe(false);
  });

  it("keeps one store's markers away from another's", async () => {
    markTillSeen("DEO");

    expect(seenKey("DEO")).not.toBe(seenKey("GAY"));
    expect(await detectStorageLoss(withMeta(0), "GAY")).toBe(false);
  });
});

describe("the single-till lock", () => {
  it("is held by the first tab and refused to the second", async () => {
    const locks = fakeLocks();
    const first = new CounterLock("DEO", locks.manager());
    const second = new CounterLock("DEO", locks.manager());

    expect(await first.acquire()).toBe(true);
    expect(await second.acquire()).toBe(false);
    expect(first.held()).toBe(true);
    expect(second.held()).toBe(false);
  });

  it("hands the counter over when the first tab lets go", async () => {
    // Closing the first tab must not need a reload of the second: the second
    // asks again on the sync interval, and this is that ask.
    const locks = fakeLocks();
    const first = new CounterLock("DEO", locks.manager());
    const second = new CounterLock("DEO", locks.manager());
    await first.acquire();
    await second.acquire();

    first.release();
    // The browser hands a released lock on asynchronously, which is why the
    // second tab asks again on a timer rather than being notified.
    await new Promise((settled) => setTimeout(settled, 0));

    expect(await second.acquire()).toBe(true);
  });

  it("does not let one store's counter block another's", async () => {
    // Two shops on one machine are two counters, and neither is the other's
    // second tab.
    const locks = fakeLocks();
    const deo = new CounterLock("DEO", locks.manager());
    const gay = new CounterLock("GAY", locks.manager());

    expect(await deo.acquire()).toBe(true);
    expect(await gay.acquire()).toBe(true);
  });

  it("counts a browser with no lock API as holding it", async () => {
    // The lock is a warning over an invariant IndexedDB already enforces inside
    // the commit. Refusing to bill because an advisory API is missing would turn
    // a nicety into a lost day's trade.
    const lock = new CounterLock("DEO", undefined);

    expect(await lock.acquire()).toBe(true);
    expect(lock.held()).toBe(true);
  });

  it("counts a lock manager that threw the same way, and stops asking", async () => {
    let asked = 0;
    const broken: LockManagerLike = {
      async request() {
        asked += 1;
        throw new Error("no locks here");
      },
    };
    const lock = new CounterLock("DEO", broken);

    expect(await lock.acquire()).toBe(true);
    expect(await lock.acquire()).toBe(true);

    expect(lock.held()).toBe(true);
    expect(asked).toBe(1);
  });
});

describe("what stops a bill", () => {
  it("lets an ordinary counter bill", () => {
    expect(billingBlock({ storageLost: false, lockHeld: true })).toBe("");
  });

  it("stops a counter that lost its local data, and points at the recovery", () => {
    const why = billingBlock({ storageLost: true, lockHeld: true });

    expect(why).toContain("bill number");
    expect(why).toContain("Till & Sync");
  });

  it("stops the second tab", () => {
    expect(billingBlock({ storageLost: false, lockHeld: false })).toContain("another tab");
  });

  it("names the worse of the two first", () => {
    // A counter that lost its data and is also the second tab has one thing to
    // do about it, and it is not closing the tab.
    expect(billingBlock({ storageLost: true, lockHeld: false })).toContain("lost");
  });
});
