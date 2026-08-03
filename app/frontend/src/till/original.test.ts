import "fake-indexeddb/auto";

import { afterEach, describe, expect, it } from "vitest";

import { findQueuedBillByDoc, searchQueuedBillsByCustomer } from "./original";
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
});
