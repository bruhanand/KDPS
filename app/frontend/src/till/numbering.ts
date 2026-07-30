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
import type { BillDraft, QueuedBill } from "./types";

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
  const seq = (await readMeta(db, META.fy, "")) === fy ? await readMeta(db, META.nextSeq, 1) : 1;
  return renderBillNumber(fy, storeCode, seq);
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
  return db.transaction("rw", [db.meta, db.queue, db.stock, db.items], async () => {
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
    return bill;
  });
}

/**
 * Take the next sequence for `fy` and advance the counter.
 *
 * Deliberately not exported. It MUST run inside `commitBill`'s transaction - on
 * its own it is a way to spend a number on nothing.
 */
async function nextBillNumber(db: TillDb, fy: string): Promise<number> {
  const countingFor = await readMeta(db, META.fy, "");
  // A new financial year is a new series, starting at 1. Reading the stored year
  // rather than comparing dates means a till that was switched off across 1 April
  // rolls over when it is switched on, not when somebody remembers.
  const seq = countingFor === fy ? await readMeta(db, META.nextSeq, 1) : 1;
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

/** A v4 UUID, from the platform where there is one. */
function newUuid(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  // Chrome is the standardised till (grill Q5) and has had `randomUUID` on
  // secure origins for years, so this is for a plain-http dev box, not for a
  // counter. It is still a v4 shape, so nothing downstream can tell.
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => {
    const n = Number(c);
    return (n ^ (Math.floor(Math.random() * 256) & (15 >> (n / 4)))).toString(16);
  });
}
