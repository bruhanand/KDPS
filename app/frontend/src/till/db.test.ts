// The till's own schema, and the one thing a schema change here can destroy.
//
// This database is not a cache. A counter mid-shift has bills in `queue` that
// are printed, paid for and in customers' hands, and the server has never heard
// of them - so a Dexie version that is not purely additive is a shop losing a
// morning's takings on the deploy that ships it. Dexie is unforgiving about the
// distinction: adding a version upgrades an existing database in place, but
// *editing* a version that has already shipped makes it throw the old one away.
//
// The test is therefore not "does version 4 have a customers table" - the type
// system says that. It is: open a database at the previous version, put money in
// it, and open it again at the current one.

import "fake-indexeddb/auto";

import Dexie from "dexie";
import { afterEach, describe, expect, it } from "vitest";

import { closeTillDb, databaseName, tillDb } from "./db";

const OPENED: string[] = [];

afterEach(async () => {
  for (const code of OPENED.splice(0)) {
    closeTillDb(code);
    await Dexie.delete(databaseName(code));
  }
});

/** A store code no other test in this file is using.
 *
 *  `freshTill` is the fixture everywhere else in this folder, and deliberately
 *  not used here: it hands back a database already opened at the current
 *  version, and this test has to write the *previous* one first. */
let counter = 0;
function storeCode(): string {
  const code = `DB${(counter += 1)}`;
  OPENED.push(code);
  return code;
}

describe("the till's schema", () => {
  it("upgrades a version-3 database in place, keeping its unsynced bills (#245)", async () => {
    const code = storeCode();
    // Version 3 exactly as it shipped with #244, spelled out here rather than
    // imported: the point of the test is that today's class can open *that*
    // database, so reusing today's definition would prove nothing.
    const old = new Dexie(databaseName(code));
    old.version(1).stores({
      items: "[barcode+season], barcode, brand",
      stock: "barcode",
      offers: "id",
      creditNotes: "number",
      salesmen: "id",
      managers: "user_id",
      gstSlabs: "[hsn_prefix+effective_from]",
      meta: "key",
      queue: "++id, idempotency_uuid",
      held: "held_uuid",
    });
    old.version(2).stores({ seasons: "code" });
    old.version(3).stores({ draft: "" });
    await old.open();
    await old.table("queue").add({ doc_number: "26-27/DEO/SAL/74", idempotency_uuid: "u-1" });
    await old.table("meta").put({ key: "nextSeq", value: 75 });
    await old.table("items").put({ barcode: "8901000000011", season: "FW25" });
    old.close();

    const db = tillDb(code);
    await db.open();

    // The money first: a bill the server has not seen, still there.
    expect(await db.queue.count()).toBe(1);
    expect((await db.queue.toArray())[0].doc_number).toBe("26-27/DEO/SAL/74");
    expect(await db.meta.get("nextSeq")).toMatchObject({ value: 75 });
    expect(await db.items.count()).toBe(1);
    // And the new table exists, empty, waiting for the next dataset pull.
    expect(await db.customers.count()).toBe(0);
  });
});
