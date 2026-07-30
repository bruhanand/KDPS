// The commit point (#180, D10 step 3, grill Q1 and Q2).
//
// Save & Print is where a sale becomes a fact: the number is assigned, the shelf
// goes down by one, the receipt prints, and none of it waits for a network. The
// till owns the bill counter for its store - one POS per store is a hard
// invariant, so there is exactly one writer on the series - and the server's job
// at sync is to accept each number exactly once, never to hand one out.
//
// That makes this module small and load-bearing in equal measure. The number and
// the queued bill **must** be written in one local transaction. Split them and
// each half is a way to lose money:
//
//   · number first, queue second, crash between - the number is spent on a bill
//     that does not exist. The server later sees a hole and the store spends the
//     evening looking for a bill nobody wrote.
//   · queue first, number second - two bills carry the same number, the second
//     one is refused for ever with `BILL_NO_TAKEN`, and two customers' purchases
//     sit under one Tally key.
//
// So there is exactly one way in - `commitBill` - and the function that reads the
// counter is not exported. Nothing outside this file can obtain a bill number.

import { financialYear } from "../lib/fiscal";

import { META, readMeta } from "./db";
import type { TillDb } from "./db";
import { notesSpentBy } from "./tender";
import type { BillDraft, QueuedBill } from "./types";
import { newUuid } from "./uuid";

/** The document type the till numbers. The kernel accepts external numbers on
 *  this series and no other (`core.documents.EXTERNAL_NUMBER_DOC_TYPES`). */
const SALE_DOC_TYPE = "SAL";

/** How a bill number reads on the customer's copy, and in Tally.
 *  The mirror of `VoucherSeries.render` with no configured affixes. */
export function renderBillNumber(fy: string, storeCode: string, seq: number): string {
  return `${fy}/${storeCode}/${SALE_DOC_TYPE}/${seq}`;
}

/** The number the next bill will take, for a screen to show. Read-only, and
 *  advisory: by the time anything acts on it another bill may have taken it.
 *  Assigning a number happens in `commitBill` and nowhere else. */
export async function previewNextNumber(
  db: TillDb,
  storeCode: string,
  now: Date = new Date(),
): Promise<string> {
  const fy = financialYear(now);
  return renderBillNumber(fy, storeCode, await counterFor(db, fy));
}

/**
 * Move the counter up to `seq`, and never down.
 *
 * The one legitimate reason to write the counter from outside a commit: the
 * server has told us it already holds a bill at a number this till would hand
 * out again (see `sync.reconcileRegister`). It lives here, with the counter's
 * other two readers, so the rule about what "where are we up to" means is
 * written in one file rather than re-derived at each site.
 *
 * Forward only, and by a floor rather than an assignment: the ordinary state of
 * a busy counter is to be ahead of the server by whatever is still queued, and a
 * plain write would re-issue every one of those numbers.
 */
export async function fastForwardTo(db: TillDb, fy: string, seq: number): Promise<number> {
  return db.transaction("rw", db.meta, async () => {
    const local = await counterFor(db, fy);
    const next = Math.max(local, seq);
    await db.meta.bulkPut([
      { key: META.fy, value: fy },
      { key: META.nextSeq, value: next },
    ]);
    return next;
  });
}

/** Where this till's counter stands for `fy` - 1 for a year it has not counted
 *  in yet, which is what makes a financial-year rollover a read rather than a
 *  scheduled job. */
async function counterFor(db: TillDb, fy: string): Promise<number> {
  const countingFor = await readMeta(db, META.fy, "");
  return countingFor === fy ? await readMeta(db, META.nextSeq, 1) : 1;
}

/**
 * Number a bill and queue it, all or nothing.
 *
 * One Dexie read-write transaction covering `meta` (the counter), `queue` (the
 * bill) and `stock` (the shelf), which is the same set the design names for Save
 * & Print. If any part throws, IndexedDB rolls the whole thing back and the
 * counter is exactly where it was - the customer is told the bill did not save,
 * which is recoverable, rather than being handed a receipt whose number the till
 * has already given away.
 *
 * The financial year is the till's own clock (grill Q1): at midnight on 1 April
 * the counter restarts at 1 without anybody deploying anything, because the
 * server seeds next year's series row alongside this year's.
 */
export async function commitBill(
  db: TillDb,
  storeCode: string,
  draft: BillDraft,
  now: Date = new Date(),
): Promise<QueuedBill> {
  // Generated outside the transaction because it is not state: the key exists to
  // make the *server* side idempotent, so a bill that rolls back here and is
  // retried by the cashier is a genuinely different bill and wants a new one.
  const idempotencyUuid = newUuid();
  const fy = financialYear(now);

  // `items` is in scope because the shelf move asks it whether the piece is one
  // the counter has ever heard of. Read-only in practice, but a Dexie
  // transaction has to declare every table it will touch, and a commit that
  // reached outside its own scope would throw at the worst possible moment.
  return db.transaction(
    "rw",
    [db.meta, db.queue, db.stock, db.items, db.creditNotes],
    async () => {
      const seq = await nextBillNumber(db, fy);
      const bill: QueuedBill = {
        ...draft,
        idempotency_uuid: idempotencyUuid,
        store: storeCode,
        fy,
        till_seq: seq,
        origin: draft.origin ?? (navigator.onLine ? "online" : "offline"),
        doc_number: renderBillNumber(fy, storeCode, seq),
        attempts: 0,
      };
      await db.queue.add(bill);
      await moveStock(db, bill);
      await moveNotes(db, bill);
      return bill;
    },
  );
}

/**
 * Take the next sequence for `fy` and advance the counter.
 *
 * Deliberately not exported. It MUST run inside `commitBill`'s transaction - on
 * its own it is a way to spend a number on nothing.
 */
async function nextBillNumber(db: TillDb, fy: string): Promise<number> {
  // A new financial year is a new series, starting at 1. Reading the stored year
  // rather than comparing dates means a till that was switched off across 1 April
  // rolls over when it is switched on, not when somebody remembers.
  const seq = await counterFor(db, fy);
  await db.meta.bulkPut([
    { key: META.fy, value: fy },
    { key: META.nextSeq, value: seq + 1 },
  ]);
  return seq;
}

/**
 * Move the counter's own copy of the shelf, in the same transaction as the bill.
 *
 * The local count is what the next scan reads, so it has to move at Save & Print
 * rather than when the server hears about the sale - otherwise a busy counter
 * offline sells the same last piece all afternoon.
 *
 * A count that goes negative is allowed and is not an error (grill Q6): the piece
 * was on the shelf, so the count was wrong, and the next stock count reconciles
 * it. A barcode the till has never heard of is a sold-before-inward line and gets
 * no stock row - inventing one would put a piece the books do not know about into
 * the counter's own stock figures.
 */
async function moveStock(db: TillDb, bill: QueuedBill): Promise<void> {
  const net = new Map<string, number>();
  for (const line of bill.lines) {
    const delta = line.direction === "return" ? line.qty : -line.qty;
    net.set(line.barcode, (net.get(line.barcode) ?? 0) + delta);
  }
  for (const [barcode, delta] of net) {
    if (!delta) continue;
    const row = await db.stock.get(barcode);
    if (row) {
      await db.stock.put({ barcode, qty: row.qty + delta });
      continue;
    }
    const known = await db.items.where("barcode").equals(barcode).count();
    if (known) await db.stock.put({ barcode, qty: delta });
  }
}

/**
 * Spend the counter's own copy of every credit note this bill took (#182).
 *
 * In the same transaction as the bill, and for the same reason the shelf is:
 * what the next customer is offered has to reflect what the last one just spent.
 * The server draws the real balance down when the bill syncs, which may be days
 * later - and until then a note whose local balance had not moved would pay for
 * a second bill, and a third, all of them landing at head office to be refused.
 *
 * A note that reaches nought is left on the cache at nought rather than deleted:
 * the next attempt to spend it should read "nothing left on it" and not "this
 * counter has never heard of that note", which is a different sentence with a
 * different remedy. The sync's `deleted.credit_notes` is what removes it.
 */
async function moveNotes(db: TillDb, bill: QueuedBill): Promise<void> {
  await drawDownNotes(db, notesSpentBy(bill.tenders));
}

/**
 * Take `spent` off the counter's copy of each named note.
 *
 * Exported because the sync does the same write for a different reason: it has
 * to subtract the queue's spending from a balance the server has just re-stated
 * (`sync.replayQueuedNotes`). Two copies of "what a spent note now says" is two
 * chances to write one of them differently.
 *
 * A note the counter does not hold is skipped: it is an unverified one taken on
 * a manager's OK, there is no local balance to move, and inventing one would be
 * inventing money. A note that reaches nought stays in the cache at nought, so
 * the next attempt reads "nothing left on it" rather than "never heard of it".
 */
export async function drawDownNotes(db: TillDb, spent: Map<string, number>): Promise<void> {
  for (const [number, amount] of spent) {
    const note = await db.creditNotes.get(number);
    if (!note) continue;
    await db.creditNotes.put({
      ...note,
      remaining_paise: Math.max(0, note.remaining_paise - amount),
    });
  }
}
