// The counter's own copy of the world (#180, D10 step 3).
//
// This is the till's source of truth, not a cache in front of one. A bill is
// final the moment Save & Print writes it here (grill Q2); the server hears about
// it afterwards, possibly days afterwards, and its only job is to accept what was
// already printed. Everything downstream of that follows:
//
//   · **One database per store.** The name carries the store code, so a device
//     that is signed into DEO can never bill against GAY's counter, its stock or
//     its credit notes - and a store login change opens a different database
//     rather than mixing two shops' rows in one.
//   · **The queue is a table, not a variable.** It has to survive a reload, a
//     crash and a flat battery, because what is in it is money that has already
//     changed hands.
//   · **`meta` holds the counter.** `nextSeq` is the till's half of the bill
//     series, and the whole reason `numbering.ts` exists is that it may only ever
//     be read and advanced inside the transaction that queues the bill.
//
// Everything here is quantity, price and identity. No cost, ever (H2): the
// dataset feed does not send it, and nothing in this module invents it.

import Dexie from "dexie";
import type { Table } from "dexie";

import type { HeldPayload } from "./held";
import type {
  QueuedBill,
  TillCreditNote,
  TillGstSlab,
  TillItem,
  TillManager,
  TillOffer,
  TillSalesman,
  TillSeason,
  TillStock,
} from "./types";

/** A bill the counter parked to serve the next customer. Mirrored to the server
 *  best-effort so the Dashboard can count them; the till stays authoritative.
 *
 *  `payload` is typed rather than left as loose JSON, even though the *server*
 *  keeps it opaque: the till writes it and the till reads it back, so a cart is
 *  the only thing it can hold, and calling it `Record<string, unknown>` here
 *  would buy a cast at every one of those reads. The import is type-only, so
 *  nothing circular survives the compiler. */
export interface HeldBill {
  held_uuid: string;
  label: string;
  held_at: string;
  /** `today` until the store says otherwise at day close; `kept` once it has. */
  expires_policy: "today" | "kept";
  payload: HeldPayload;
  /** The local day the store last answered "keep this" - and the one field here
   *  that is **not** mirrored up.
   *
   *  A hold parked before today is put to the store at day close, and keeping it
   *  has to be an answer about *that* close rather than for ever: a hold kept on
   *  Monday and still parked on Thursday is a cart nobody has thought about in
   *  three days, and a policy of `kept` alone would hide it for good. The server
   *  has no use for the answer - the mirror is a count on a Dashboard - and the
   *  contract's five columns are what `PUT /api/sell/held-bills` takes, so this
   *  stays where the decision was made. */
  reviewed_on?: string;
}

/** One row of `meta` - the till's small pile of state, keyed by name so a new
 *  fact does not need a schema version. */
export interface MetaRow {
  key: string;
  value: unknown;
}

/** The keys `meta` holds, spelled once. */
export const META = {
  /** The dataset cursor to ask the next delta from. */
  cursor: "cursor",
  /** The financial year the counter is numbering in. */
  fy: "fy",
  /** The number the next bill will take. */
  nextSeq: "nextSeq",
  /** The store this database belongs to, and its GSTIN. */
  store: "store",
  /** When the dataset last landed. */
  syncedAt: "syncedAt",
  /** The day the till last took a full bootstrap, ISO. */
  bootstrapDay: "bootstrapDay",
  /** The bill the server refused, and why - see `QueueHalt`. */
  halt: "halt",
  /** What the server last said it had accepted from this counter. */
  register: "register",
  /** The shop floor's money dials - see `TillPolicy`. */
  policy: "policy",
  /** The salesman the counter picked last, defaulted onto the next line. */
  lastSalesman: "lastSalesman",
} as const;

export class TillDb extends Dexie {
  items!: Table<TillItem, [string, string]>;
  stock!: Table<TillStock, string>;
  offers!: Table<TillOffer, number>;
  creditNotes!: Table<TillCreditNote, string>;
  salesmen!: Table<TillSalesman, number>;
  seasons!: Table<TillSeason, string>;
  managers!: Table<TillManager, number>;
  gstSlabs!: Table<TillGstSlab, [string, string]>;
  meta!: Table<MetaRow, string>;
  queue!: Table<QueuedBill, number>;
  held!: Table<HeldBill, string>;

  constructor(storeCode: string) {
    super(databaseName(storeCode));
    this.version(1).stores({
      // A piece is a barcode *in a season*: the same barcode bought twice is two
      // lots at two ticket prices, and the counter has to be able to tell them
      // apart. `barcode` is indexed on its own because a withdrawal arrives as a
      // bare barcode and takes every season of that piece with it.
      items: "[barcode+season], barcode, brand",
      stock: "barcode",
      offers: "id",
      creditNotes: "number",
      salesmen: "id",
      managers: "user_id",
      // Slabs are replaced whole on every sync, so their key only has to be
      // stable enough to upsert on: one prefix has one rate from one date.
      gstSlabs: "[hsn_prefix+effective_from]",
      meta: "key",
      // `++id` is the FIFO. Dexie hands out ascending keys, so "the oldest bill
      // still unsent" is the first row in key order - the queue does not need a
      // sequence number of its own, and cannot disagree with one.
      queue: "++id, idempotency_uuid",
      held: "held_uuid",
    });
    // The season master's ordering, for resolving a scan that names no season
    // (#181). A version of its own rather than an edit to version 1: a counter
    // that has been billing since #180 has a database on disk with unsynced
    // money in it, and Dexie upgrades that one in place instead of asking the
    // browser to throw it away and start again.
    this.version(2).stores({ seasons: "code" });
  }
}

/** The IndexedDB name for a store's till. */
export function databaseName(storeCode: string): string {
  return `kdps-till-${storeCode}`;
}

// One database object per store for the life of the tab. Dexie connections are
// expensive to open and a second one to the same name blocks the first during a
// version change, so a screen asks for the till rather than constructing one.
const open = new Map<string, TillDb>();

export function tillDb(storeCode: string): TillDb {
  let db = open.get(storeCode);
  if (!db) {
    db = new TillDb(storeCode);
    open.set(storeCode, db);
  }
  return db;
}

/** Forget the cached connection (tests, and a sign-out that changes store). */
export function closeTillDb(storeCode: string): void {
  open.get(storeCode)?.close();
  open.delete(storeCode);
}

export async function readMeta<T>(db: TillDb, key: string, fallback: T): Promise<T> {
  const row = await db.meta.get(key);
  return row === undefined ? fallback : (row.value as T);
}

export async function writeMeta(db: TillDb, key: string, value: unknown): Promise<void> {
  await db.meta.put({ key, value });
}
