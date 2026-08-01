// How the bill was paid (#182, D10 §4, grill Q4).
//
// The trimmed payment panel is four modes - cash, card, UPI, credit note - and a
// bill may use any of them together. Everything about the arithmetic here is
// decided by one fact at the other end: `accept.py` step 3 refuses a bill whose
// tenders do not come to `totals.net_paise` **exactly**, and a refused bill is a
// receipt already in a customer's hand and a queue that has stopped. So a split
// that does not add up is stopped at the counter, where a person can still fix
// it, and never allowed to become a printed bill.
//
// Two shapes here are decisions rather than convenience.
//
// **Cash is the balance until somebody says otherwise.** The ordinary sale is
// all cash, and the counter should not have to type the total into a box to say
// so. `cash_paise: null` means "whatever is left of the bill", so a plain cash
// sale is zero keystrokes and a split is exactly as explicit as it should be;
// typing into the cash box pins it, and then the panel shows what is unpaid.
//
// **A credit note is verified against the counter's own cached list.** Same-store
// only in v1, and offline redemption is only ever allowed against a note the
// dataset actually sent (grill Q4). A note the till does not recognise may still
// be genuine and simply unsynced, with the customer standing there - so it takes
// a manager's PIN and goes up flagged, which is exactly what the server does with
// it (`_plan_tenders`).

import type { BillTender, TillCreditNote } from "./types";

export type TenderMode = "cash" | "card" | "upi" | "credit_note";

/** How each mode reads to a person - on the customer's copy and on any screen
 *  that lists what a bill was paid with.
 *
 *  Here rather than in `receipt.ts`, where it started, because a second reader
 *  arrived: browser QA of #184 found the reprint screen showing a raw
 *  `credit_note` where the paper says "Credit note". The words belong with the
 *  modes, and one map means the paper and the screen cannot disagree about what
 *  a customer paid with. */
export const TENDER_WORDS: Record<string, string> = {
  cash: "Cash",
  card: "Card",
  upi: "UPI",
  credit_note: "Credit note",
};

/** One credit note the customer handed over. */
export interface NoteTender {
  /** Stable across edits, so React and the row's own inputs have something to
   *  hold that is not the note number the cashier is halfway through typing. */
  key: string;
  number: string;
  amount_paise: number;
}

export interface Payment {
  /** `null` = "the rest of the bill" - the ordinary cash sale, untouched. */
  cash_paise: number | null;
  card_paise: number;
  upi_paise: number;
  notes: NoteTender[];
  /** Cash the customer physically handed over. Presentation only: what posts to
   *  CASH is what the bill took, and the difference is change out of the drawer. */
  cash_received_paise: number;
}

/** What a note is worth here, and why it might not be honoured. */
export interface NoteStanding {
  note: NoteTender;
  /** The cached note, if this counter knows it at all. */
  cached: TillCreditNote | null;
  /** Why it needs a manager, in a sentence - or "" when it is plainly good. */
  doubt: string;
}

/** The bill's payment, resolved: what each mode takes and what is still unpaid. */
export interface TenderSplit {
  cash_paise: number;
  card_paise: number;
  upi_paise: number;
  notes: NoteStanding[];
  /** Everything the customer has put up. */
  total_paise: number;
  /** Bill less tendered. Positive = unpaid, negative = over-tendered. */
  balance_paise: number;
  /** Cash back out of the drawer, against the cash *tender*, never the bill:
   *  a ₹1,000 note handed over on a bill half paid by card is change on the
   *  cash half only. */
  change_paise: number;
  /** Notes this counter cannot stand behind, and so needs a manager for. */
  unverified: string[];
}

export function emptyPayment(): Payment {
  return { cash_paise: null, card_paise: 0, upi_paise: 0, notes: [], cash_received_paise: 0 };
}

let noteKeys = 0;

export function newNote(): NoteTender {
  noteKeys += 1;
  return { key: `n${noteKeys}`, number: "", amount_paise: 0 };
}

/**
 * Resolve a payment against the bill it is paying and the notes this counter holds.
 *
 * `day` is the till's own date: a credit note dies because a date passed, with
 * nothing written anywhere (Rule 11), so the counter judges expiry on its own
 * clock exactly as it starts and stops offers on its own clock.
 */
export function splitOf(
  payment: Payment,
  netPaise: number,
  cached: TillCreditNote[],
  day: string,
): TenderSplit {
  const notes = payment.notes.map((note) => standingOf(note, cached, day));
  const others =
    payment.card_paise + payment.upi_paise + notes.reduce((n, s) => n + s.note.amount_paise, 0);
  const cash = payment.cash_paise ?? Math.max(0, netPaise - others);
  const total = cash + others;
  return {
    cash_paise: cash,
    card_paise: payment.card_paise,
    upi_paise: payment.upi_paise,
    notes,
    total_paise: total,
    balance_paise: netPaise - total,
    change_paise: Math.max(0, payment.cash_received_paise - cash),
    unverified: notes.filter((s) => s.doubt).map((s) => s.note.number),
  };
}

/**
 * What this counter knows about one note the customer handed over.
 *
 * Anything other than "we hold this note, it is open, and it has that much left"
 * is a doubt, and a doubt is a manager's to settle - never the till's to settle
 * quietly in either direction. Refusing outright would send away a customer
 * holding a genuine note the counter has not synced yet; accepting quietly would
 * be the till writing itself a credit.
 */
export function standingOf(
  note: NoteTender,
  cached: TillCreditNote[],
  day: string,
): NoteStanding {
  const number = note.number.trim();
  const held = cached.find((row) => row.number === number) ?? null;
  return { note: { ...note, number }, cached: held, doubt: doubtAbout(note, held, day) };
}

function doubtAbout(note: NoteTender, held: TillCreditNote | null, day: string): string {
  const number = note.number.trim();
  if (!number) return "";
  if (!held) return `${number} is not a note this counter has been sent.`;
  if (held.expires_on < day) return `${number} ran out on ${held.expires_on}.`;
  if (note.amount_paise > held.remaining_paise) {
    return `${number} has less left on it than that.`;
  }
  return "";
}

/**
 * Why this bill cannot be paid for, in a sentence for the counter - or "".
 *
 * Every one of these is a bill the server would refuse, or a note the server
 * would refuse: `TENDER_MISMATCH` for the arithmetic, `CREDIT_NOTE_INVALID` for
 * a note nobody authorised. Catching them here is the difference between a
 * cashier fixing a figure and a store person unpicking a printed bill days later.
 */
export function whyPaymentCannotClose(split: TenderSplit, authorised: boolean): string {
  // The bill's own total is deliberately **not** a parameter any more (#184).
  // Everything below is about the *split* against a bill `splitOf` was already
  // given, and the one thing the total used to decide - "this bill owes the
  // customer money" - is no longer this function's question: an exchange whose
  // returns outweigh its sales takes nothing at all and hands the difference over
  // as a credit note (grill Q7), so the caller asks about `max(net, 0)` and there
  // is no payment here to collect at all.
  const blank = split.notes.find((standing) => !standing.note.number);
  if (blank) return "Type the number of the credit note, or take the row off the bill.";
  const duplicate = duplicateNote(split.notes);
  if (duplicate) {
    return `Credit note ${duplicate} is on this bill twice. Put its amounts together on one row.`;
  }
  const emptyNote = split.notes.find((standing) => standing.note.amount_paise <= 0);
  if (emptyNote) {
    return `Say how much of ${emptyNote.note.number} the customer is spending.`;
  }
  if (split.unverified.length && !authorised) {
    return `${split.notes.find((s) => s.doubt)?.doubt} A manager of this store has to approve taking it.`;
  }
  if (split.balance_paise > 0) return "The payment does not cover the whole bill yet.";
  if (split.balance_paise < 0) {
    return "The payment comes to more than the bill. Cash handed over goes in Cash received.";
  }
  return "";
}

function duplicateNote(notes: NoteStanding[]): string {
  const seen = new Set<string>();
  for (const { note } of notes) {
    if (!note.number) continue;
    if (seen.has(note.number)) return note.number;
    seen.add(note.number);
  }
  return "";
}

/** The tenders as the bill carries them: every mode that took money, once.
 *
 *  A row of nought is not a tender and is left out - the server's own serializer
 *  drops them, and a `SaleTender` may not be written at zero (`ck_saletender_
 *  amount_positive`). */
export function toTenders(split: TenderSplit): BillTender[] {
  const rows: BillTender[] = [
    { mode: "cash", amount_paise: split.cash_paise },
    { mode: "card", amount_paise: split.card_paise },
    { mode: "upi", amount_paise: split.upi_paise },
    ...split.notes.map(
      (standing): BillTender => ({
        mode: "credit_note",
        amount_paise: standing.note.amount_paise,
        credit_note: standing.note.number,
      }),
    ),
  ];
  return stampManualUpi(rows.filter((row) => row.amount_paise > 0));
}

/**
 * Stamp `manual` on every UPI row missing a stamp, and leave everything else
 * alone - a row already stamped (once `confirmed` exists, #248) and every
 * non-UPI row.
 *
 * Two callers, both at the wire boundary (#241): `toTenders` stamps a bill as
 * it is built, and `transport.billBody` runs this over a bill already sitting
 * in the queue from before this build, which would otherwise halt on the
 * server's new refusal (Rule 5, flag never block) - a queued bill is a printed
 * bill, and a halted queue stays halted until a human clears it.
 */
export function stampManualUpi(tenders: BillTender[]): BillTender[] {
  return tenders.map((tender) =>
    tender.mode === "upi" && !tender.upi_state ? { ...tender, upi_state: "manual" } : tender,
  );
}

/**
 * How much of each credit note a bill spends, keyed by note number.
 *
 * Read off the bill's own tender rows rather than off the panel, because both
 * readers are working from bills that have already been committed: the commit
 * that draws the counter's copy down (`numbering.moveNotes`), and the sync that
 * has to take those draw-downs off a balance the server has just re-stated
 * (`sync.replayQueuedNotes`). A note the counter does not hold is simply not
 * found by either of them - it is a number the server will decide about, and
 * inventing a local row for it would be inventing money.
 */
export function notesSpentBy(tenders: BillTender[]): Map<string, number> {
  const spent = new Map<string, number>();
  for (const tender of tenders) {
    const number = (tender.credit_note ?? "").trim();
    if (tender.mode !== "credit_note" || !number || tender.amount_paise <= 0) continue;
    spent.set(number, (spent.get(number) ?? 0) + tender.amount_paise);
  }
  return spent;
}
