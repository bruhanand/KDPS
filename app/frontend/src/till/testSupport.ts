// Fixtures for the till's tests: a store's worth of data, and a fake server.
//
// Imported only by `*.test.ts` in this folder, so it never reaches a bundle. It
// is a module rather than a copy in each file because the dataset payload has
// eleven sections and a test that had to spell all of them out would be a test
// about the fixture.

import { closeTillDb, tillDb } from "./db";
import type { TillDb } from "./db";
import type { TillTransport } from "./transport";
import { TillHttpError } from "./transport";
import type {
  AcceptedBill,
  BillDraft,
  DatasetPayload,
  HandoverPayload,
  QueuedBill,
  RegisterPayload,
} from "./types";

let counter = 0;

/** The three browser globals the engine reads, for a test running in node.
 *
 *  Deliberately the smallest possible: `window` for the online/offline events,
 *  `navigator` for `onLine` and the persistent-storage request, `localStorage`
 *  for the storage-loss marker. Anything the engine starts reading beyond these
 *  should fail loudly here rather than only in a browser. */
export function installBrowserGlobals(): void {
  const listeners = new Map<string, Set<() => void>>();
  define("window", {
    addEventListener: (name: string, fn: () => void) => {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name)!.add(fn);
    },
    removeEventListener: (name: string, fn: () => void) => listeners.get(name)?.delete(fn),
    dispatchEvent: (event: { type: string }) => {
      for (const fn of listeners.get(event.type) ?? []) fn();
      return true;
    },
  });
  define("navigator", { onLine: true, storage: { persist: async () => true } });
  const held = new Map<string, string>();
  define("localStorage", {
    getItem: (key: string) => held.get(key) ?? null,
    setItem: (key: string, value: string) => held.set(key, value),
    removeItem: (key: string) => held.delete(key),
    clear: () => held.clear(),
  });
}

function define(name: string, value: unknown): void {
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
}

/** A fresh, empty till, on a database name no other test is using.
 *
 *  `reopen` is what a reload looks like from here: the connection is dropped and
 *  a new one is made to the same IndexedDB database, which is the only way to
 *  tell a counter that survives a crash from one that keeps its state in a
 *  variable. */
export function freshTill(): {
  db: TillDb;
  storeCode: string;
  reopen: () => TillDb;
  close: () => void;
} {
  const storeCode = `T${(counter += 1)}`;
  return {
    db: tillDb(storeCode),
    storeCode,
    reopen: () => {
      closeTillDb(storeCode);
      return tillDb(storeCode);
    },
    close: () => closeTillDb(storeCode),
  };
}

/** A dataset response. Pass only the sections a test is about. */
export function dataset(over: Partial<DatasetPayload> = {}): DatasetPayload {
  return {
    cursor: "2026-07-30T10:00:00.000Z",
    full: true,
    store: { code: "DEO", gstin: "10AAAAA0000A1Z5", state_code: "10" },
    items: [],
    stock: [],
    gst_slabs: [],
    offers: [],
    credit_notes: [],
    salesmen: [],
    managers: [],
    seasons: [],
    customers: [],
    policy: { manual_discount_cap_percent: "10.00", manual_discount_on_offer_lines: false },
    deleted: { items: [], offers: [], credit_notes: [] },
    ...over,
  };
}

/** A season, with the master's own ordering. Lower `sort_order` is older. */
export function season(code: string, sort_order: number, status = "open") {
  return { code, name: `Season ${code}`, status, sort_order };
}

export function item(barcode: string, season = "FW25", mrp: number | null = 149900) {
  return {
    barcode,
    season,
    design: "SHIRT-01",
    brand: "MUFTI",
    item: "Shirt",
    size: "M",
    color: "NAVY",
    hsn: "6205",
    mrp_paise: mrp,
    no_discount: false,
  };
}

export function register(over: Partial<RegisterPayload> = {}): RegisterPayload {
  return {
    fy: "26-27",
    last_accepted_seq: 0,
    holes: [],
    hole_count: 0,
    series_open: true,
    ...over,
  };
}

/** A one-line cash bill that adds up, for the queue to carry. */
export function draft(over: Partial<BillDraft> = {}): BillDraft {
  return {
    billed_at: "2026-07-30T12:31:00.000Z",
    lines: [
      {
        line_no: 1,
        direction: "sale",
        barcode: "8901000000011",
        season: "FW25",
        qty: 1,
        mrp_paise: 149900,
        disc_paise: 0,
        net_paise: 149900,
        gst_rate: "5.00",
        gst_paise: 7138,
        offer_evidence: {},
      },
    ],
    tenders: [{ mode: "cash", amount_paise: 149900 }],
    totals: {
      gross_paise: 149900,
      discount_paise: 0,
      net_paise: 149900,
      gst_paise: 7138,
      round_paise: 0,
    },
    ...over,
  };
}

export interface FakeServer extends TillTransport {
  /** Every bill offered, in the order it was offered - replays included. */
  offered: QueuedBill[];
  /** What `postSale` should do next; the default is to accept. */
  answer: (bill: QueuedBill) => AcceptedBill;
  datasets: DatasetPayload[];
  /** Scripted register answers. Empty - the usual case - means the fake works
   *  it out from the bills it has actually taken, which is what a real server
   *  does and what keeps a test off the order the till happens to ask in. */
  registers: RegisterPayload[];
  /** Cursors the till asked from, in order. */
  asked: string[];
  /** Every held-bill push, in order - each one the whole list as it stood. */
  heldPushes: Record<string, unknown>[][];
  /** Every register handover asked for, by reason (#189). */
  handovers: string[];
}

/** A server that takes every bill, unless a test says otherwise. */
export function fakeServer(over: Partial<FakeServer> = {}): FakeServer {
  const landed: number[] = [];
  const server: FakeServer = {
    offered: [],
    datasets: [],
    registers: [],
    asked: [],
    heldPushes: [],
    handovers: [],
    answer: (bill) => ({ doc_number: bill.doc_number, id: bill.till_seq, flags: [] }),
    async dataset(since: string) {
      server.asked.push(since);
      return server.datasets.shift() ?? dataset();
    },
    async register() {
      return (
        server.registers.shift() ??
        register({ last_accepted_seq: landed.length ? Math.max(...landed) : 0 })
      );
    },
    async postSale(bill: QueuedBill) {
      server.offered.push(bill);
      const accepted = server.answer(bill);
      landed.push(bill.till_seq);
      return accepted;
    },
    async putHeld(held: Record<string, unknown>[]) {
      server.heldPushes.push(held);
      return { count: held.length };
    },
    async handover(reason: string): Promise<HandoverPayload> {
      server.handovers.push(reason);
      const last = landed.length ? Math.max(...landed) : 0;
      const holes = [];
      for (let seq = 1; seq < last; seq += 1) if (!landed.includes(seq)) holes.push(seq);
      return { resume_from_seq: last + 1, unsynced_hint: holes, hole_count: holes.length };
    },
    ...over,
  };
  return server;
}

/** What the server says when it will not take a bill. */
export function refuse(status: number, code: string, message = "No."): never {
  throw new TillHttpError(status, code, message);
}
