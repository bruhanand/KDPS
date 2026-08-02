// The commit point (#180).
//
// Every test here is about one sentence from the ticket: "number + enqueue are
// one atomic local transaction; no path splits them". A bill number is the Tally
// join key, the till is its only writer, and a counter that got out of step with
// the queue would put two customers' purchases under one key or send a store
// looking for a bill nobody wrote.

import "fake-indexeddb/auto";

import { afterEach, describe, expect, it } from "vitest";

import { META, readMeta } from "./db";
import {
  commitBill,
  previewNextNumber,
  reenterPaperBill,
  renderBillNumber,
} from "./numbering";
import { draft, freshTill, item } from "./testSupport";

let close = () => undefined as void;
afterEach(() => close());

function till() {
  const made = freshTill();
  close = made.close;
  return made;
}

describe("numbering a bill", () => {
  it("counts from one and does not skip", async () => {
    const { db, storeCode } = till();

    const first = await commitBill(db, storeCode, draft());
    const second = await commitBill(db, storeCode, draft());

    expect(first.till_seq).toBe(1);
    expect(second.till_seq).toBe(2);
    expect(first.doc_number).toBe(renderBillNumber(first.fy, storeCode, 1));
  });

  it("queues exactly what it numbered, and nothing else", async () => {
    const { db, storeCode } = till();

    const bill = await commitBill(db, storeCode, draft());

    const queued = await db.queue.toArray();
    expect(queued).toHaveLength(1);
    expect(queued[0].till_seq).toBe(bill.till_seq);
    expect(queued[0].idempotency_uuid).toBe(bill.idempotency_uuid);
    expect(queued[0].attempts).toBe(0);
  });

  it("gives every bill its own idempotency key", async () => {
    // The server dedupes on this. Two bills sharing one would make the second a
    // replay of the first: the customer's money in the drawer and nothing on the
    // books to match it.
    const { db, storeCode } = till();

    const keys = new Set<string>();
    for (let i = 0; i < 5; i += 1) {
      keys.add((await commitBill(db, storeCode, draft())).idempotency_uuid);
    }

    expect(keys.size).toBe(5);
  });

  it("rolls the counter back when the queue write fails", async () => {
    // The failure this exists to prevent: the number is spent, the bill is not
    // written, and the server later reports a hole for a bill that never was.
    const { db, storeCode } = till();
    await commitBill(db, storeCode, draft());

    db.queue.hook("creating", () => {
      throw new Error("disk full");
    });
    await expect(commitBill(db, storeCode, draft())).rejects.toThrow();

    expect(await readMeta(db, META.nextSeq, 0)).toBe(2);
    expect(await db.queue.count()).toBe(1);
  });

  it("survives a reload - the counter and the queue are on disk", async () => {
    // The acceptance criterion in the ticket's own words. A queue held in memory
    // would lose a paid-for bill to a flat battery.
    const { db, storeCode, reopen } = till();
    await commitBill(db, storeCode, draft());
    await commitBill(db, storeCode, draft());

    const after = reopen();
    const third = await commitBill(after, storeCode, draft());

    expect(third.till_seq).toBe(3);
    expect((await after.queue.orderBy("id").toArray()).map((b) => b.till_seq)).toEqual([1, 2, 3]);
  });

  it("restarts at one in a new financial year", async () => {
    // The till rolls its own year on its own clock at midnight on 1 April; the
    // server seeds next year's series row in advance precisely so it can.
    const { db, storeCode } = till();
    const march = new Date("2027-03-31T18:00:00Z");
    const april = new Date("2027-04-01T04:00:00Z");

    const last = await commitBill(db, storeCode, draft(), march);
    const secondLast = await commitBill(db, storeCode, draft(), march);
    const first = await commitBill(db, storeCode, draft(), april);

    expect([last.fy, secondLast.fy]).toEqual(["26-27", "26-27"]);
    expect(secondLast.till_seq).toBe(2);
    expect(first.fy).toBe("27-28");
    expect(first.till_seq).toBe(1);
  });
});

describe("the local shelf", () => {
  it("comes down by what was sold, in the same transaction", async () => {
    const { db, storeCode } = till();
    await db.items.put(item("8901000000011"));
    await db.stock.put({ barcode: "8901000000011", qty: 3 });

    await commitBill(db, storeCode, draft());

    expect((await db.stock.get("8901000000011"))?.qty).toBe(2);
  });

  it("goes negative rather than refusing a sale", async () => {
    // Grill Q6: the piece was on the shelf, so the count was wrong. A count that
    // cannot go negative is a count that stops a real sale.
    const { db, storeCode } = till();
    await db.items.put(item("8901000000011"));
    await db.stock.put({ barcode: "8901000000011", qty: 0 });

    await commitBill(db, storeCode, draft());

    expect((await db.stock.get("8901000000011"))?.qty).toBe(-1);
  });

  it("invents no stock row for a piece the till has never heard of", async () => {
    // A sold-before-inward line. Writing a row here would put a piece the books
    // do not know about into the counter's own stock figures.
    const { db, storeCode } = till();

    await commitBill(db, storeCode, draft());

    expect(await db.stock.count()).toBe(0);
  });

  it("puts an exchanged piece back", async () => {
    const { db, storeCode } = till();
    await db.items.put(item("8901000000011"));
    await db.stock.put({ barcode: "8901000000011", qty: 1 });
    const exchange = draft();
    exchange.lines.push({ ...exchange.lines[0], line_no: 2, direction: "return", qty: 1 });

    await commitBill(db, storeCode, exchange);

    expect((await db.stock.get("8901000000011"))?.qty).toBe(1);
  });
});

describe("the counter's own credit notes (#182)", () => {
  const NOTE = { number: "26-27/DEO/CRN/4", remaining_paise: 120000, expires_on: "2027-01-30" };

  /** The one-line bill, part-paid with `spent` off the note. */
  function paidWithNote(spent: number, number = NOTE.number) {
    return draft({
      tenders: [
        { mode: "credit_note", amount_paise: spent, credit_note: number },
        { mode: "cash", amount_paise: 149900 - spent },
      ],
    });
  }

  it("comes down by what the bill spent, in the same transaction as the bill", async () => {
    // The server draws the real balance down when the bill syncs, which may be
    // days later. Until then a note whose local balance had not moved would pay
    // for a second bill, and a third, all of them refused at head office.
    const { db, storeCode } = till();
    await db.creditNotes.put(NOTE);

    await commitBill(db, storeCode, paidWithNote(50000));

    expect((await db.creditNotes.get(NOTE.number))?.remaining_paise).toBe(70000);
  });

  it("cannot be spent twice by two bills in a row", async () => {
    const { db, storeCode } = till();
    await db.creditNotes.put(NOTE);

    await commitBill(db, storeCode, paidWithNote(120000));
    await commitBill(db, storeCode, paidWithNote(120000));

    // The second bill is the counter's to refuse before it is written - what is
    // asserted here is that the cache says so rather than reading full again.
    expect((await db.creditNotes.get(NOTE.number))?.remaining_paise).toBe(0);
  });

  it("stays on the counter at nought rather than vanishing", async () => {
    // "There is nothing left on that note" and "never heard of that note" are
    // different sentences with different remedies.
    const { db, storeCode } = till();
    await db.creditNotes.put(NOTE);

    await commitBill(db, storeCode, paidWithNote(120000));

    expect(await db.creditNotes.get(NOTE.number)).toBeTruthy();
  });

  it("invents no note for one the counter has never been sent", async () => {
    // An unverified note, taken on a manager's OK. There is no local balance to
    // move, and inventing one would be inventing money.
    const { db, storeCode } = till();

    await commitBill(db, storeCode, paidWithNote(50000, "26-27/XXX/CRN/9"));

    expect(await db.creditNotes.count()).toBe(0);
  });
});

describe("re-entering a bill from its printed copy (#189)", () => {
  /** A counter that has already passed `seq` - which is what makes a hole a hole. */
  async function counterPast(seq: number) {
    const made = till();
    for (let i = 0; i < seq; i += 1) await commitBill(made.db, made.storeCode, draft());
    await made.db.queue.clear();
    return made;
  }

  it("takes the number from the paper and leaves the counter alone", async () => {
    // The whole point: this bill is *behind* the counter. A re-entry that
    // advanced it would spend a number on a bill nobody has printed.
    const { db, storeCode } = await counterPast(5);
    const before = await previewNextNumber(db, storeCode);

    const bill = await reenterPaperBill(db, storeCode, draft(), 3);

    expect(bill.till_seq).toBe(3);
    expect(bill.doc_number).toBe(renderBillNumber(bill.fy, storeCode, 3));
    expect(await previewNextNumber(db, storeCode)).toBe(before);
  });

  it("stamps it as paper, whatever the draft said", async () => {
    // `origin` is how the daily check tells a bill keyed in from a drawer from
    // one somebody stood at this counter and rang up.
    const { db, storeCode } = await counterPast(5);

    const bill = await reenterPaperBill(db, storeCode, { ...draft(), origin: "online" }, 3);

    expect(bill.origin).toBe("paper");
  });

  it("takes each number exactly once", async () => {
    // Two people working through the same drawer. The server would refuse the
    // second copy anyway, but only after it had printed nothing and halted the
    // queue behind it.
    const { db, storeCode } = await counterPast(5);
    await reenterPaperBill(db, storeCode, draft(), 3);

    await expect(reenterPaperBill(db, storeCode, draft(), 3)).rejects.toThrow(/already/);

    expect(await db.queue.count()).toBe(1);
  });

  it("still refuses it after the bill has synced and left the queue", async () => {
    // The one that matters, and the one a queue check alone would miss. A
    // re-entered bill is gone from the queue the moment head office takes it -
    // and the address that got somebody here still names it, so a reload would
    // key the same receipt in again: the shelf comes down twice, and the server
    // answers BILL_NO_TAKEN, which is terminal and stops the store's whole queue.
    const { db, storeCode } = await counterPast(5);
    await reenterPaperBill(db, storeCode, draft(), 3);
    await db.queue.clear();

    await expect(reenterPaperBill(db, storeCode, draft(), 3)).rejects.toThrow(/already/);

    expect(await db.queue.count()).toBe(0);
  });

  it("remembers only this year's re-entries", async () => {
    // The counter restarts at 1 every April, so last year's bill 3 and this
    // year's are two different bills and one must not block the other.
    const march = new Date("2027-03-31T10:00:00.000Z");
    const april = new Date("2027-04-01T10:00:00.000Z");
    const { db, storeCode } = till();
    for (let i = 0; i < 5; i += 1) await commitBill(db, storeCode, draft(), march);
    await db.queue.clear();
    await reenterPaperBill(db, storeCode, draft(), 3, march);
    for (let i = 0; i < 5; i += 1) await commitBill(db, storeCode, draft(), april);
    await db.queue.clear();

    const again = await reenterPaperBill(db, storeCode, draft(), 3, april);

    expect(again.fy).toBe("27-28");
    expect(again.till_seq).toBe(3);
  });

  it("refuses a number the counter has not reached", async () => {
    // Not a bill from the old machine - a bill that does not exist. Accepting it
    // would let somebody mint a number out of order and strand the one in between.
    const { db, storeCode } = await counterPast(5);

    await expect(reenterPaperBill(db, storeCode, draft(), 6)).rejects.toThrow(/not been printed/);
    await expect(reenterPaperBill(db, storeCode, draft(), 0)).rejects.toThrow(/not a bill number/);
    expect(await db.queue.count()).toBe(0);
  });

  it("takes the piece off this counter's shelf", async () => {
    // The garment left the shop on the old machine, but this till's stock came
    // from the server - which never heard about that bill - so its copy is still
    // holding the piece.
    const { db, storeCode } = await counterPast(5);
    await db.items.put(item("8901000000011"));
    await db.stock.put({ barcode: "8901000000011", qty: 3 });

    await reenterPaperBill(db, storeCode, draft(), 2);

    expect((await db.stock.get("8901000000011"))?.qty).toBe(2);
  });
});

describe("the next number, for a screen to show", () => {
  it("is what the next bill will actually take", async () => {
    const { db, storeCode } = till();
    expect(await previewNextNumber(db, storeCode)).toBe(
      renderBillNumber((await commitBill(db, storeCode, draft())).fy, storeCode, 1),
    );

    const next = await previewNextNumber(db, storeCode);

    expect(next).toContain("/SAL/2");
  });
});
