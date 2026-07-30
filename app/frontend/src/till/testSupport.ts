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
  QueuedBill,
  RegisterPayload,
} from "./types";

let counter = 0;

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
    deleted: { items: [], offers: [], credit_notes: [] },
    ...over,
  };
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
  registers: RegisterPayload[];
  /** Cursors the till asked from, in order. */
  asked: string[];
}

/** A server that takes every bill, unless a test says otherwise. */
export function fakeServer(over: Partial<FakeServer> = {}): FakeServer {
  const server: FakeServer = {
    offered: [],
    datasets: [],
    registers: [],
    asked: [],
    answer: (bill) => ({ doc_number: bill.doc_number, id: bill.till_seq, flags: [] }),
    async dataset(since: string) {
      server.asked.push(since);
      return server.datasets.shift() ?? dataset();
    },
    async register() {
      return server.registers.shift() ?? register();
    },
    async postSale(bill: QueuedBill) {
      server.offered.push(bill);
      return server.answer(bill);
    },
    ...over,
  };
  return server;
}

/** What the server says when it will not take a bill. */
export function refuse(status: number, code: string, message = "No."): never {
  throw new TillHttpError(status, code, message);
}
