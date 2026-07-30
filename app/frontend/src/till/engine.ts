// The till, running (#180, D10 step 3).
//
// `db.ts` holds the counter's world, `numbering.ts` commits a bill into it and
// `sync.ts` moves rows in each direction. This is the thing that decides *when*:
// what happens at store open, what happens every minute, what happens the moment
// the line comes back, and what the sync light says while all of that is going on.
//
// It is a plain object with a subscribe/snapshot pair rather than a hook, for two
// reasons. The till outlives any one screen - a bill queued on the Sell page must
// keep draining while the cashier is looking at the Dashboard - and the sync
// engine has to be drivable from a test without a React renderer.
//
// Everything it does is safe to do twice. A drain is single-flight, a sync is
// idempotent by key, and the server's idempotency makes a re-offered bill a
// no-op. That matters because the triggers overlap by design: a till that comes
// back online during its own retry backoff should sync at once, not wait.
//
// Two departures from `design.md`'s sketch of a separate `guard.ts`, both
// deliberate and both recorded here rather than in a file that does not exist:
//
//   · **The storage sentinel is in `localStorage`, not in `meta`.** design.md
//     lists `storageSentinel` as a `meta` row, and a sentinel that lives inside
//     the database cannot survive the database being thrown away - which is the
//     one event it exists to detect. It has to sit outside, and `localStorage` is
//     the only other durable place a browser offers.
//   · **There is no `navigator.locks` single-till lock.** It was there to stop a
//     second tab double-writing the counter, and IndexedDB already does: two
//     read-write transactions whose scopes overlap are serialised across every
//     connection to the database, tabs included, so `commitBill`'s transaction is
//     the lock. What the lock would still add is telling a person they have two
//     tills open, which is a warning rather than an invariant, and it belongs
//     with the rest of the PWA hardening in #189.

import { META, readMeta, tillDb, writeMeta } from "./db";
import type { TillDb } from "./db";
import { commitBill, previewNextNumber } from "./numbering";
import { deriveStatus } from "./status";
import type { SyncStatus } from "./status";
import { clearHalt, drainQueue, forceBootstrap, reconcileRegister, syncDown } from "./sync";
import { httpTransport } from "./transport";
import type { TillTransport } from "./transport";
import type { BillDraft, QueueHalt, QueuedBill, RegisterPayload } from "./types";

/** How often the counter pulls new prices and offers while it is online. */
export const DATASET_INTERVAL_MS = 5 * 60_000;
/** How often it offers whatever is in the queue. */
export const QUEUE_INTERVAL_MS = 60_000;

export interface TillCounts {
  items: number;
  stock: number;
  offers: number;
  creditNotes: number;
  salesmen: number;
  managers: number;
  gstSlabs: number;
  held: number;
}

export interface TillSnapshot {
  storeCode: string;
  /** The engine has read the local database at least once. Until then a screen
   *  knows nothing, which is not the same as knowing the till is empty. */
  ready: boolean;
  status: SyncStatus;
  pending: number;
  queue: QueuedBill[];
  datasetReady: boolean;
  syncedAt: string | null;
  online: boolean;
  halt: QueueHalt | null;
  register: RegisterPayload | null;
  counts: TillCounts;
  /** What the next bill will be numbered, for a screen to show. Advisory. */
  nextNumber: string;
  /** A sync or a drain is in flight. */
  busy: boolean;
  /** Flags the server raised on the bills that went up last - a hole, an offer
   *  mismatch. Shown on the Dashboard's action queue, never at the counter. */
  lastFlags: string[];
  /** Why the last attempt did not finish, if it did not. */
  lastError: string;
}

const EMPTY_COUNTS: TillCounts = {
  items: 0,
  stock: 0,
  offers: 0,
  creditNotes: 0,
  salesmen: 0,
  managers: 0,
  gstSlabs: 0,
  held: 0,
};

function initialSnapshot(storeCode: string): TillSnapshot {
  return {
    storeCode,
    ready: false,
    status: { colour: "amber", label: "Starting", reason: "Opening the counter…" },
    pending: 0,
    queue: [],
    datasetReady: false,
    syncedAt: null,
    online: true,
    halt: null,
    register: null,
    counts: EMPTY_COUNTS,
    nextNumber: "",
    busy: false,
    lastFlags: [],
    lastError: "",
  };
}

export class TillEngine {
  readonly db: TillDb;
  private snapshot: TillSnapshot;
  private readonly listeners = new Set<() => void>();
  private timers: ReturnType<typeof setInterval>[] = [];
  private retry: ReturnType<typeof setTimeout> | null = null;
  private started = false;
  private storageLost = false;
  /** Bumped by every start and every stop, so a boot sequence that was
   *  interrupted half way through stops touching the engine it no longer owns. */
  private generation = 0;

  constructor(
    readonly storeCode: string,
    private readonly transport: TillTransport = httpTransport,
  ) {
    this.db = tillDb(storeCode);
    this.snapshot = initialSnapshot(storeCode);
  }

  // -- what React reads ------------------------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Cached and replaced whole, never mutated: `useSyncExternalStore` compares
   *  by identity and would loop for ever on a fresh object each call. */
  getSnapshot = (): TillSnapshot => this.snapshot;

  private publish(patch: Partial<TillSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of this.listeners) listener();
  }

  // -- lifecycle -------------------------------------------------------------

  /**
   * Open the counter.
   *
   * Three things happen here that do not happen anywhere else:
   *
   *   · **Persistent storage is requested.** Without it the browser may evict the
   *     database under pressure, and what it would be evicting is unsynced bills.
   *   · **A bootstrap is taken once a day.** The delta cursor laps a quarter of an
   *     hour behind the clock, which *bounds* a missed row rather than preventing
   *     one; a bootstrap cannot miss anything by construction, so taking one at
   *     store open bounds any hole to a single day (contract amendment, #179).
   *   · **The register is read.** The server says how far it has got, and a till
   *     that lost its local state moves its counter forward rather than re-issuing
   *     a number that is already on a posted bill.
   *
   * Start and stop are a matched pair that can run any number of times on one
   * engine, because React runs them that way: StrictMode mounts, unmounts and
   * remounts every effect in development, and a person walking off the Sell page
   * and back does the same in production. The timers are armed before the first
   * `await` for that reason - a `stop()` landing mid-start would otherwise clear
   * an empty list and leave two intervals firing at nobody.
   */
  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    const generation = (this.generation += 1);
    window.addEventListener("online", this.onOnline);
    window.addEventListener("offline", this.onOffline);
    this.timers = [
      setInterval(() => void this.pullDatasetAndRefresh(), DATASET_INTERVAL_MS),
      setInterval(() => void this.pushAndRefresh(), QUEUE_INTERVAL_MS),
    ];

    await navigator.storage?.persist?.().catch(() => false);
    if (generation !== this.generation) return;
    this.storageLost = await detectStorageLoss(this.db, this.storeCode);
    if (generation !== this.generation) return;
    await this.refresh();
    if (generation !== this.generation) return;
    await this.syncNow({ bootstrapIfNewDay: true });
  }

  /** Put the engine down without putting the *database* down.
   *
   *  The Dexie connection is a per-store singleton shared by whatever else the
   *  tab opens, and closing it here would leave a memoised engine holding a dead
   *  handle - which is exactly what a StrictMode remount does, and what a person
   *  walking off the Sell page and back does in production. It stays open for the
   *  life of the tab; `closeTillDb` exists for tests and for a sign-out that
   *  really is finished with this store.
   *
   *  Subscribers are left alone too: `useSyncExternalStore` unsubscribes itself,
   *  and dropping its listener here would freeze the screen on the last snapshot
   *  it happened to see. */
  stop(): void {
    this.started = false;
    this.generation += 1;
    window.removeEventListener("online", this.onOnline);
    window.removeEventListener("offline", this.onOffline);
    for (const timer of this.timers) clearInterval(timer);
    this.timers = [];
    if (this.retry) clearTimeout(this.retry);
    this.retry = null;
  }

  private onOnline = (): void => {
    // Both directions, immediately: prices first so nothing is billed off a stale
    // copy, and the queue behind it because that is money waiting.
    void this.syncNow();
  };

  private onOffline = (): void => {
    void this.attempt(() => this.refresh());
  };

  // -- the work --------------------------------------------------------------

  /**
   * Down then up, in that order.
   *
   * Every step is independent and none of them throws. That is not tidiness: the
   * queue is money and the dataset is reference data, so a failed price pull must
   * never be a reason not to send a bill that is already paid for. Three separate
   * attempts, worst case three recorded reasons, and the light tells the story.
   */
  async syncNow(options: { bootstrapIfNewDay?: boolean } = {}): Promise<void> {
    this.publish({ busy: true, lastError: "" });
    const failures = [
      options.bootstrapIfNewDay ? await this.attempt(() => this.bootstrapIfNewDay()) : "",
      await this.attempt(() => reconcileRegister(this.db, this.transport)),
      await this.pullDataset(),
      await this.push(),
      await this.attempt(() => this.refresh()),
    ].filter(Boolean);
    this.publish({ busy: false, lastError: failures[0] ?? "" });
  }

  /** Clear the halt and offer the refused bill again. Called from a button with
   *  no `await` behind it, so it reports rather than throws. */
  async retryHalted(): Promise<void> {
    const failed = await this.attempt(() => clearHalt(this.db));
    if (failed) {
      this.publish({ lastError: failed });
      return;
    }
    await this.pushAndRefresh();
  }

  /** Number a bill, queue it and try to send it - the Save & Print path.
   *
   *  The commit is awaited and the send is not, deliberately: the bill is final
   *  the moment it is in the queue (grill Q2), and the counter must be ready for
   *  the next customer whether or not there is a network. */
  async commit(draft: BillDraft): Promise<QueuedBill> {
    const bill = await commitBill(this.db, this.storeCode, draft);
    await this.refresh();
    void this.pushAndRefresh();
    return bill;
  }

  private async bootstrapIfNewDay(): Promise<void> {
    const today = new Date().toISOString().slice(0, 10);
    if ((await readMeta(this.db, META.bootstrapDay, "")) === today) return;
    await forceBootstrap(this.db);
    await writeMeta(this.db, META.bootstrapDay, today);
  }

  /** Pull the dataset. Answers the reason it could not, rather than throwing. */
  private async pullDataset(): Promise<string> {
    return this.attempt(async () => {
      await syncDown(this.db, this.transport);
      // A dataset that landed is proof the database is alive, and the marker is
      // what a later session compares against to notice it was thrown away.
      this.storageLost = false;
      localStorage.setItem(seenKey(this.storeCode), "1");
    });
  }

  /** Offer the queue, and schedule the next attempt if the line was down. */
  private async push(): Promise<string> {
    return this.attempt(async () => {
      const result = await drainQueue(this.db, this.transport);
      this.publish({ lastFlags: result.flags });
      if (this.retry) clearTimeout(this.retry);
      this.retry = result.retryAfterMs
        ? setTimeout(() => void this.pushAndRefresh(), result.retryAfterMs)
        : null;
    });
  }

  // Both of these are fired from a timer with `void`, so nothing is waiting to
  // catch them: an unhandled rejection here is a store's browser logging an
  // error nobody reads and a light that stops moving. Every step, the refresh
  // included, goes through `attempt`.
  private async pushAndRefresh(): Promise<void> {
    const failed = await this.push();
    // The refresh runs whether or not the push worked - a failed attempt has an
    // attempt count and a reason on it, and those are what the screen is for.
    const stale = await this.attempt(() => this.refresh());
    this.publish({ lastError: failed || stale });
  }

  private async pullDatasetAndRefresh(): Promise<void> {
    const failed = await this.pullDataset();
    const stale = await this.attempt(() => this.refresh());
    this.publish({ lastError: failed || stale });
  }

  private async attempt(work: () => Promise<unknown>): Promise<string> {
    try {
      await work();
      return "";
    } catch (error) {
      return messageOf(error);
    }
  }

  /** Re-read everything a screen shows from the local database. Cheap - these
   *  are counts and one small table - and it is the only writer of the snapshot's
   *  facts, so nothing on screen can drift from what is on disk. */
  async refresh(): Promise<void> {
    const [items, stock, offers, creditNotes, salesmen, managers, gstSlabs, held] =
      await Promise.all([
        this.db.items.count(),
        this.db.stock.count(),
        this.db.offers.count(),
        this.db.creditNotes.count(),
        this.db.salesmen.count(),
        this.db.managers.count(),
        this.db.gstSlabs.count(),
        this.db.held.count(),
      ]);
    const queue = await this.db.queue.orderBy("id").toArray();
    const halt = await readMeta<QueueHalt | null>(this.db, META.halt, null);
    const register = await readMeta<RegisterPayload | null>(this.db, META.register, null);
    const syncedAt = await readMeta<string | null>(this.db, META.syncedAt, null);
    const nextNumber = await previewNextNumber(this.db, this.storeCode);
    const online = navigator.onLine;
    const datasetReady = Boolean(syncedAt);

    this.publish({
      ready: true,
      counts: { items, stock, offers, creditNotes, salesmen, managers, gstSlabs, held },
      queue,
      pending: queue.length,
      halt,
      register,
      syncedAt,
      nextNumber,
      online,
      datasetReady,
      status: deriveStatus({
        datasetReady,
        pending: queue.length,
        halt,
        register,
        storageLost: this.storageLost,
        online,
      }),
    });
  }
}

/** Has this device been a till before and lost the database since?
 *
 *  A best-effort detector, and honest about it: the marker lives in
 *  `localStorage`, which a browser clearing site data would take with it. What it
 *  does catch is the common case - IndexedDB evicted under storage pressure, or a
 *  "clear cached images and files" - where the counter would otherwise start
 *  again at bill 1 with no idea anything had happened. The register call fixes the
 *  numbering; this is what makes the light go red so somebody knows to make it. */
async function detectStorageLoss(db: TillDb, storeCode: string): Promise<boolean> {
  const wasATill = localStorage.getItem(seenKey(storeCode)) === "1";
  if (!wasATill) return false;
  return (await db.meta.count()) === 0;
}

function seenKey(storeCode: string): string {
  return `kdps-till-seen-${storeCode}`;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
