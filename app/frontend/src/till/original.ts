// Finding the bill a piece was bought on (#184, D10 step 5).
//
// **Local first, server when online**, and the order is not an optimisation.
// A bill the counter rang up ten minutes ago may still be in the queue - the line
// went down, or it simply has not drained yet - and the server cannot answer
// about it at all. That is the commonest exchange there is: the customer walks
// back in with the wrong size. So the counter's own queue is asked first, and
// only then head office.
//
// The two answers differ in where they came from, but both can back the same new
// Sale: the accept pipeline resolves an unsynced original once the queue drains
// in order, while a synced bill can be checked immediately.
//
// Everything a returned line is worth is read off the bill rather than off the
// price list: what comes back is what was paid (D2), which is a fact about that
// bill and about no other.

import type { TillDb } from "./db";
import type { ExchangeOriginal, OriginalLine } from "./exchange";
import type { QueuedBill, TillItem } from "./types";

/** A bill found, and where it was found. */
export interface FoundBill {
  original: ExchangeOriginal;
  lines: OriginalLine[];
  billed_at: string;
  customer_name: string;
  customer_mobile: string;
  /** True when this bill is still in the counter's own queue. */
  local: boolean;
}

/** How a bill is asked for: the sequence number off the printed slip. */
export function billSeqFrom(typed: string): number | null {
  const trimmed = typed.trim();
  if (!trimmed) return null;
  // A person reads "74" off the slip as often as the whole key, and the whole key
  // ends in the same number - so the last run of digits is what they mean either
  // way. `26-27/DEO/SAL/74` and `74` are the same question.
  const digits = trimmed.match(/(\d+)\s*$/);
  const seq = digits ? Number(digits[1]) : NaN;
  return Number.isInteger(seq) && seq > 0 ? seq : null;
}

/**
 * The bill this counter numbered `seq` and has not yet sent, or null.
 *
 * Read out of the queue, which is the only copy of it that exists anywhere.
 * `returned_qty` is worked out from the other bills in the same queue: an
 * exchange against this one, rung up while both were still local, is a piece
 * already given back and the counter must not offer it twice.
 */
export async function findQueuedBill(
  db: TillDb,
  fy: string,
  seq: number,
): Promise<FoundBill | null> {
  const queue = await db.queue.orderBy("id").toArray();
  const bill = queue.find((row) => row.fy === fy && row.till_seq === seq);
  if (!bill) return null;
  const given = alreadyGivenBack(queue, fy, seq);
  const items = await db.items.toArray();
  return fromQueued(bill, given, items);
}

/** A queued bill by the exact document number encoded in its receipt barcode.
 * Kept separate from the sequence lookup because configured voucher-series
 * suffixes need not end in digits. */
export async function findQueuedBillByDoc(
  db: TillDb,
  docNumber: string,
): Promise<FoundBill | null> {
  const wanted = docNumber.trim().toLocaleLowerCase();
  if (!wanted) return null;
  const queue = await db.queue.orderBy("id").toArray();
  const bill = queue.find((row) => row.doc_number.toLocaleLowerCase() === wanted);
  if (!bill) return null;
  const given = alreadyGivenBack(queue, bill.fy, bill.till_seq);
  const items = await db.items.toArray();
  return fromQueued(bill, given, items);
}

/** Unsynced bills whose snapshotted customer matches the third find-bill door.
 * This is deliberately local even while online: the bill rung up five minutes
 * ago may not exist at head office yet. */
export async function searchQueuedBillsByCustomer(
  db: TillDb,
  key: "mobile" | "name",
  term: string,
): Promise<FoundBill[]> {
  const query = key === "mobile" ? digitsOf(term) : term.trim().toLocaleLowerCase();
  if (!query) return [];
  const queue = await db.queue.orderBy("id").reverse().toArray();
  const items = await db.items.toArray();
  return queue
    .filter((bill) => {
      const value =
        key === "mobile"
          ? digitsOf(bill.customer?.mobile ?? "")
          : (bill.customer?.name ?? "").toLocaleLowerCase();
      return value.includes(query);
    })
    .map((bill) => fromQueued(bill, alreadyGivenBack(queue, bill.fy, bill.till_seq), items));
}

function digitsOf(value: string): string {
  return value.replace(/\D/g, "");
}

function fromQueued(
  bill: QueuedBill,
  given: Map<number, { qty: number; paise: number }>,
  items: TillItem[],
): FoundBill {
  return {
    original: { fy: bill.fy, till_seq: bill.till_seq, doc_number: bill.doc_number },
    billed_at: bill.billed_at,
    customer_name: bill.customer?.name ?? "",
    customer_mobile: bill.customer?.mobile ?? "",
    local: true,
    lines: bill.lines
      .filter((line) => line.direction !== "return")
      .map((line) => {
        const back = given.get(line.line_no) ?? { qty: 0, paise: 0 };
        const piece = items.find(
          (row) => row.barcode === line.barcode && row.season === (line.season ?? ""),
        );
        return {
          line_no: line.line_no,
          barcode: line.barcode,
          season: line.season ?? "",
          ...describedBy(piece),
          qty: line.qty,
          net_paise: line.net_paise,
          gst_rate: line.gst_rate,
          gst_paise: line.gst_paise,
          manual_desc: line.manual_desc ?? "",
          direction: "sale",
          returned_qty: back.qty,
          returned_paise: back.paise,
        };
      }),
  };
}

/** What every other bill still in this queue has already given back off `seq`. */
function alreadyGivenBack(
  queue: QueuedBill[],
  fy: string,
  seq: number,
): Map<number, { qty: number; paise: number }> {
  const given = new Map<number, { qty: number; paise: number }>();
  for (const bill of queue) {
    const exchange = bill.exchange;
    if (exchange?.original.fy !== fy || exchange.original.till_seq !== seq) continue;
    for (const leg of exchange.lines) {
      const seen = given.get(leg.original_line) ?? { qty: 0, paise: 0 };
      given.set(leg.original_line, {
        qty: seen.qty + leg.qty,
        paise: seen.paise + leg.refund_paise,
      });
    }
  }
  return given;
}

/** The seven merchandising words for a piece the counter still stocks - or
 *  blanks, which `describeOriginal` falls back through to the typed description
 *  and then to the barcode. */
function describedBy(piece: TillItem | undefined) {
  return {
    design: piece?.design ?? "",
    color: piece?.color ?? "",
    size: piece?.size ?? "",
    brand: piece?.brand ?? "",
    item: piece?.item ?? "",
    hsn: piece?.hsn ?? "",
  };
}

/** The read shape of `GET /api/sell/sales/{doc_number}`, narrowed to what a
 *  return needs. Hand-written for the reason `types.ts` gives: this is the
 *  till's copy of a contract, and it has to keep compiling when the generated
 *  schema is not to hand. */
export interface SaleDetail {
  doc_number: string;
  fy: string;
  till_seq: number;
  billed_at: string;
  customer_name: string;
  customer_mobile: string;
  lines: OriginalLine[];
}

/** A bill head office holds, in the same shape as a queued one. */
export function fromServer(detail: SaleDetail): FoundBill {
  return {
    original: { fy: detail.fy, till_seq: detail.till_seq, doc_number: detail.doc_number },
    billed_at: detail.billed_at,
    customer_name: detail.customer_name,
    customer_mobile: detail.customer_mobile,
    local: false,
    // A bill's own exchange legs are lines too, and they are not returnable -
    // they are pieces that already came back.
    lines: detail.lines.filter((line) => line.direction !== "return"),
  };
}
