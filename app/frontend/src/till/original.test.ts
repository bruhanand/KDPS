import "fake-indexeddb/auto";

import { afterEach, describe, expect, it } from "vitest";

import {
  billSearchForCustomer,
  foundFromExchange,
  mergeRecentBills,
  recentQueuedBills,
  searchKnownCustomers,
  findQueuedBillByDoc,
  searchQueuedBillsByCustomer,
  withQueuedReturns,
} from "./original";
import type { FoundBill, RecentBillSummary } from "./original";
import { draft, freshTill } from "./testSupport";
import type { TillDb } from "./db";
import type { QueuedBill } from "./types";

let opened: ReturnType<typeof freshTill>[] = [];

afterEach(() => {
  for (const till of opened) till.close();
  opened = [];
});

function queued(seq: number, name: string, mobile: string): QueuedBill {
  return {
    ...draft({ customer: { name, mobile, gstin: "" } }),
    idempotency_uuid: `00000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    store: "DEO",
    fy: "26-27",
    till_seq: seq,
    origin: "offline",
    doc_number: `26-27/DEO/SAL/${seq}`,
    attempts: 0,
  };
}

describe("customer search over the till's own queue", () => {
  it("finds unsynced bills by name or normalised mobile while offline", async () => {
    const till = freshTill();
    opened.push(till);
    const db: TillDb = till.db;
    await db.queue.bulkAdd([
      queued(40, "Sunita Devi", "+91 98352 12345"),
      queued(41, "Ravi Kumar", "9182000000"),
    ]);

    expect((await searchQueuedBillsByCustomer(db, "name", "sunita")).map((b) => b.original.till_seq)).toEqual([40]);
    expect((await searchQueuedBillsByCustomer(db, "mobile", "983521")).map((b) => b.original.till_seq)).toEqual([40]);
  });

  it("finds the full receipt barcode even when the series has a suffix", async () => {
    const till = freshTill();
    opened.push(till);
    const db: TillDb = till.db;
    await db.queue.add({
      ...queued(42, "Anita", "9876543210"),
      doc_number: "26-27/DEO/SAL/42-A",
    });

    const found = await findQueuedBillByDoc(db, "26-27/deo/sal/42-a");

    expect(found?.original.doc_number).toBe("26-27/DEO/SAL/42-A");
  });

  it("keeps the bill's authoritative net instead of re-adding filtered lines", async () => {
    const till = freshTill();
    opened.push(till);
    const db: TillDb = till.db;
    await db.queue.add({
      ...queued(43, "Anita", "9876543210"),
      totals: { ...queued(43, "Anita", "9876543210").totals, net_paise: 49900 },
    });

    const found = await findQueuedBillByDoc(db, "26-27/DEO/SAL/43");

    expect(found?.net_paise).toBe(49900);
  });

  it("adds return legs still waiting in the local queue to a server bill", async () => {
    const till = freshTill();
    opened.push(till);
    const db: TillDb = till.db;
    const pending = queued(44, "Anita", "9876543210");
    const original = { fy: "26-27", till_seq: 8, doc_number: "26-27/DEO/SAL/8" };
    pending.exchange = {
      original: { fy: original.fy, till_seq: original.till_seq },
      lines: [
        {
          line_no: 2,
          original_line: 1,
          barcode: "8901000000011",
          season: "FW25",
          qty: 1,
          refund_paise: 149900,
          gst_rate: "5.00",
          gst_paise: 7138,
          reason: "size",
          condition: "good",
        },
      ],
    };
    await db.queue.add(pending);
    const server: FoundBill = {
      original,
      billed_at: "2026-07-20T10:00:00Z",
      customer_name: "Anita",
      customer_mobile: "9876543210",
      net_paise: 299800,
      local: false,
      lines: [
        {
          line_no: 1,
          barcode: "8901000000011",
          season: "FW25",
          design: "SHIRT-01",
          color: "NAVY",
          size: "M",
          brand: "MUFTI",
          item: "Shirt",
          hsn: "6205",
          qty: 2,
          net_paise: 299800,
          gst_rate: "5.00",
          gst_paise: 14276,
          manual_desc: "",
          direction: "sale",
          returned_qty: 0,
          returned_paise: 0,
        },
      ],
    };

    const found = await withQueuedReturns(db, server);

    expect(found.lines[0]).toMatchObject({ returned_qty: 1, returned_paise: 149900 });
  });

  it("reads the synced customer master by mobile or name", async () => {
    const till = freshTill();
    opened.push(till);
    const db: TillDb = till.db;
    await db.customers.bulkPut([
      { mobile: "9835212345", name: "Sunita Devi", gstin: "" },
      { mobile: "9182000000", name: "Ravi Kumar", gstin: "" },
    ]);

    expect((await searchKnownCustomers(db, "mobile", "98352")).map((row) => row.name)).toEqual([
      "Sunita Devi",
    ]);
    expect((await searchKnownCustomers(db, "name", "ravi")).map((row) => row.mobile)).toEqual([
      "9182000000",
    ]);
  });

  it("opens a picked customer's bill history by unique mobile, not shared name", () => {
    const first = { mobile: "9835212345", name: "Sunita Devi", gstin: "" };
    const second = { mobile: "9182000000", name: "Sunita Devi", gstin: "" };

    expect(billSearchForCustomer(first)).toEqual({ key: "mobile", term: "9835212345" });
    expect(billSearchForCustomer(second)).toEqual({ key: "mobile", term: "9182000000" });
  });

  it("reconstructs the against-bill card from an exchange saved in a draft", () => {
    const exchange = {
      original: { fy: "26-27", till_seq: 8, doc_number: "26-27/DEO/SAL/8" },
      billed_at: "2026-07-20T10:00:00Z",
      lines: [],
      original_bill: {
        lines: [],
        billed_at: "2026-07-20T10:00:00Z",
        customer_name: "Sunita Devi",
        customer_mobile: "9835212345",
        net_paise: 149900,
        local: false,
      },
    };

    expect(foundFromExchange(exchange)).toMatchObject({
      original: exchange.original,
      customer_name: "Sunita Devi",
      net_paise: 149900,
    });
  });
});

describe("recent bills helpers (return-start doors)", () => {
  it("returns up to limit local queued bills newest-first", async () => {
    const till = freshTill();
    opened.push(till);
    const db: TillDb = till.db;
    await db.queue.bulkAdd([
      { ...queued(1, "A", "9000000001"), billed_at: "2026-08-01T10:00:00Z" },
      { ...queued(2, "B", "9000000002"), billed_at: "2026-08-02T10:00:00Z" },
      { ...queued(3, "C", "9000000003"), billed_at: "2026-08-03T10:00:00Z" },
      { ...queued(4, "D", "9000000004"), billed_at: "2026-08-04T10:00:00Z" },
    ]);

    const recent = await recentQueuedBills(db, 3);
    expect(recent.length).toBe(3);
    // Reverse queue order: 4, 3, 2
    expect(recent.map((r) => r.doc_number)).toEqual([
      "26-27/DEO/SAL/4",
      "26-27/DEO/SAL/3",
      "26-27/DEO/SAL/2",
    ]);
  });

  it("merges local and server bills, deduplicating by doc_number", () => {
    const local: RecentBillSummary[] = [
      { doc_number: "BILL-2", billed_at: "2026-08-02T10:00:00Z", customer_name: "Local B", customer_mobile: "", net_paise: 10000, local: null },
      { doc_number: "BILL-1", billed_at: "2026-08-01T10:00:00Z", customer_name: "Local A", customer_mobile: "", net_paise: 20000, local: null },
    ];
    const server: RecentBillSummary[] = [
      { doc_number: "BILL-3", billed_at: "2026-08-03T10:00:00Z", customer_name: "Server C", customer_mobile: "", net_paise: 30000, local: null },
      { doc_number: "BILL-2", billed_at: "2026-08-02T10:00:00Z", customer_name: "Server B", customer_mobile: "", net_paise: 10000, local: null },
    ];

    const merged = mergeRecentBills(local, server, 3);
    expect(merged.length).toBe(3);
    // Ordered newest-first: BILL-3, BILL-2 (local), BILL-1
    expect(merged.map((m) => m.doc_number)).toEqual(["BILL-3", "BILL-2", "BILL-1"]);
    // Local copy of BILL-2 was kept, not server
    expect(merged[1].customer_name).toBe("Local B");
  });
});

