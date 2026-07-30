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

import { closeTillDb, META, readMeta, tillDb, writeMeta } from "./db";
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
    status: { colour: "amber", reason: "Starting the till…" },
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
   */
  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    window.addEventListener("online", this.onOnline);
    window.addEventListener("offline", this.onOffline);
    await navigator.storage?.persist?.().catch(() => false);

    this.storageLost = await detectStorageLoss(this.db, this.storeCode);
    await this.refresh();
    this.timers = [
      setInterval(() => void this.pullDatasetAndRefresh(), DATASET_INTERVAL_MS),
      setInterval(() => void this.pushAndRefresh(), QUEUE_INTERVAL_MS),
    ];
    await this.syncNow({ bootstrapIfNewDay: true });
  }

  stop(): void {
    this.started = false;
    window.removeEventListener("online", this.onOnline);
    window.removeEventListener("offline", this.onOffline);
    for (const timer of this.timers) clearInterval(timer);
    this.timers = [];
    if (this.retry) clearTimeout(this.retry);
    this.retry = null;
    this.listeners.clear();
    closeTillDb(this.storeCode);
  }

  private onOnline = (): void => {
    // Both directions, immediately: prices first so nothing is billed off a stale
    // copy, and the queue behind it because that is money waiting.
    void this.syncNow();
  };

  private onOffline = (): void => {
    void this.refresh();
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
    if (options.bootstrapIfNewDay) await this.bootstrapIfNewDay();
    const failures = [
      await this.attempt(() => reconcileRegister(this.db, this.transport)),
      await this.pullDataset(),
      await this.push(),
    ].filter(Boolean);
    this.publish({ busy: false, lastError: failures[0] ?? "" });
    await this.refresh();
  }

  /** Clear the halt and offer the refused bill again. */
  async retryHalted(): Promise<void> {
    await clearHalt(this.db);
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

  private async pushAndRefresh(): Promise<void> {
    const failed = await this.push();
    this.publish({ lastError: failed });
    await this.refresh();
  }

  private async pullDatasetAndRefresh(): Promise<void> {
    const failed = await this.pullDataset();
    this.publish({ lastError: failed });
    await this.refresh();
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
