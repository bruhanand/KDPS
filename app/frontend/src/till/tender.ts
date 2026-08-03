// How the bill was paid (#182, D10 §4, grill Q4).
//
// The payment panel has three modes - cash, card and UPI - and a
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

import type { UpiCharged } from "./payment";
import type { BillTender } from "./types";

export type TenderMode = "cash" | "card" | "upi";

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

export interface Payment {
  /** `null` = "the rest of the bill" - the ordinary cash sale, untouched. */
  cash_paise: number | null;
  card_paise: number;
  upi_paise: number;
  /** Cash the customer physically handed over. Presentation only: what posts to
   *  CASH is what the bill took, and the difference is change out of the drawer. */
  cash_received_paise: number;
  /** What the bank answered, if the QR charge card got an answer at all (#248).
   *  `null`/absent - which is every bill on the mock adapter - means the cashier
   *  is vouching for the UPI row themselves, and it goes up stamped `manual`. */
  upi_charge?: UpiCharged | null;
}

/** The bill's payment, resolved: what each mode takes and what is still unpaid. */
export interface TenderSplit {
  cash_paise: number;
  card_paise: number;
  upi_paise: number;
  /** Everything the customer has put up. */
  total_paise: number;
  /** Everything somebody actually **typed** - `total_paise` less the cash the
   *  panel is only about to take on its own (#246).
   *
   *  The distinction only matters to the prefill. `cash_paise: null` makes cash
   *  absorb the whole bill silently, so `balance_paise` on an ordinary panel is
   *  already nought and reading "what is still owed" off it would offer nothing
   *  to the first box a cashier taps. What is still owed is the bill less what
   *  has been *said*, and this is that. */
  explicit_paise: number;
  /** The bill this split was resolved against (#246).
   *
   *  Carried rather than asked for again, because the caller cannot be trusted
   *  to reproduce it: `priceCart` resolves the split against `Math.max(net, 0)`,
   *  since a bill that owes the customer takes no tender at all, and a prefill
   *  computed from a raw `net_paise` on that bill would offer a figure the
   *  close-validation then refused. One field here is one fewer thing every
   *  caller has to remember. */
  net_paise: number;
  /** Bill less tendered. Positive = unpaid, negative = over-tendered. */
  balance_paise: number;
  /** Cash back out of the drawer, against the cash *tender*, never the bill:
   *  a ₹1,000 note handed over on a bill half paid by card is change on the
   *  cash half only. */
  change_paise: number;
  /** The acquirer's reference for the UPI row, when the bank confirmed it
   *  through the charge card (#248) - and `null` whenever the cashier is the
   *  only one vouching for it, which is every bill until real hardware lands.
   *  Never blank when it is set; see `confirmedUpiOf`. */
  upi_confirmed: string | null;
}

export function emptyPayment(): Payment {
  return {
    cash_paise: null,
    card_paise: 0,
    upi_paise: 0,
    cash_received_paise: 0,
    upi_charge: null,
  };
}

/**
 * Resolve a payment against the bill it is paying.
 */
export function splitOf(
  payment: Payment,
  netPaise: number,
): TenderSplit {
  const others = payment.card_paise + payment.upi_paise;
  const cash = payment.cash_paise ?? Math.max(0, netPaise - others);
  const total = cash + others;
  return {
    cash_paise: cash,
    card_paise: payment.card_paise,
    upi_paise: payment.upi_paise,
    total_paise: total,
    explicit_paise: others + (payment.cash_paise ?? 0),
    net_paise: netPaise,
    balance_paise: netPaise - total,
    change_paise: Math.max(0, payment.cash_received_paise - cash),
    upi_confirmed: confirmedUpiOf(payment),
  };
}

/**
 * Whether the UPI row on this payment is still one the bank confirmed (#248).
 *
 * A stamp is only good for the figure it was given about. The cashier charges
 * ₹1,499 through the QR, the bank confirms *that*, and then the customer changes
 * their mind and half of it goes on card - the reference now answers about a sum
 * nobody is being asked to pay, and a bill carrying it would tell head office a
 * bank confirmed a figure it has never seen. So the stamp is pinned to its
 * amount and falls away the moment the two disagree, which drops the row back to
 * `manual`: the cashier vouching for it, which is the truth.
 *
 * A blank reference is refused here for the same reason it is refused by the
 * server (`upi_state=confirmed` with no `upi_reference` is a `VALIDATION`): a
 * bill refused at the wire is a receipt already in a customer's hand and a queue
 * that has stopped.
 */
export function confirmedUpiOf(payment: Payment): string | null {
  const charge = payment.upi_charge;
  if (!charge || payment.upi_paise <= 0) return null;
  if (charge.amount_paise !== payment.upi_paise) return null;
  return charge.reference.trim() || null;
}

/**
 * What an empty tender box takes when the cashier taps into it (#246, grill Q4).
 *
 * The panel is built on one rule - what is still owed is always on screen, and
 * tapping a row fills it - so this is that figure: the bill less every row
 * somebody has actually filled in. Typing over what it fills is what makes a
 * split a split; there is no separate mode, and no other arithmetic.
 *
 * Deliberately **not** keyed by mode, unlike `prefillFor(split, mode)` as
 * design.md sketched it. The prefill only ever fires on a box standing empty,
 * an empty box has put up nothing, and so every mode is owed the same figure -
 * a `mode` parameter would advertise a difference that does not exist. The one
 * mode that genuinely differs has its own function below.
 *
 * Nothing here is money moving: the figure is *offered* into a box the cashier
 * can still overtype, and `whyPaymentCannotClose` judges the result exactly as
 * it did before. Cash keeps its `null`-means-the-rest semantics until a person
 * touches it, so the day-close numbers cannot shift.
 */
export function prefillFor(split: TenderSplit): number {
  return Math.max(0, split.net_paise - split.explicit_paise);
}

/** The explicit-tender patch behind the UPI and Card “rest” controls. */
export function restTenderPatch(
  split: TenderSplit,
  mode: "upi" | "card",
): Pick<Payment, "upi_paise"> | Pick<Payment, "card_paise"> {
  // `rest` finishes an already-started row; replacing its entered figure with
  // just the remainder would silently discard the first half of a split.
  const paise = (mode === "upi" ? split.upi_paise : split.card_paise) + prefillFor(split);
  return mode === "upi" ? { upi_paise: paise } : { card_paise: paise };
}

/** A confirmed UPI charge is fixed: the rest must go to another tender. */
export function canFillTenderRest(split: TenderSplit, mode: "upi" | "card"): boolean {
  return prefillFor(split) > 0 && (mode !== "upi" || split.upi_confirmed === null);
}

/** ₹100 and ₹500, in paise - the two notes an Indian counter is handed. */
const CHIP_STEPS = [10000, 50000];

/**
 * The quick-cash chips under the cash row: exact, then the next ₹100 and the
 * next ₹500 (grill Q4).
 *
 * `duePaise` is the **cash tender**, not `TenderSplit.balance_paise`. On the
 * ordinary all-cash sale the balance is nought - cash absorbs the bill - and
 * chips read off it would never appear on the one sale they were asked for.
 * What the customer is handing money against is what the cash row is taking.
 *
 * Exact keeps its paise: it exists to close the change line to nought, and a
 * chip rounded to the rupee would leave a stray fifty paise behind. The round
 * figures are deduped, so a bill that is already ₹5,000 offers one chip rather
 * than the same one three times.
 */
export function cashChips(duePaise: number): number[] {
  if (duePaise <= 0) return [];
  const chips = [duePaise];
  for (const step of CHIP_STEPS) {
    const rounded = Math.ceil(duePaise / step) * step;
    if (!chips.includes(rounded)) chips.push(rounded);
  }
  return chips;
}

/** The five things the payment card's one balance line can be saying (#246). */
export type BalanceTone = "short" | "over" | "stranded" | "change" | "settled";

/** The one balance line, resolved: which of the five, in what words, on what
 *  figure. The figure is always positive - the words carry the direction. */
export interface BalanceStanding {
  tone: BalanceTone;
  says: string;
  paise: number;
}

/**
 * Where the money stands, as the one line under the tenders says it (#246).
 *
 * A rule rather than a rendering detail, and here rather than in the panel,
 * because getting it wrong is not cosmetic: the green line is an *instruction*
 * to open the drawer and hand notes back, and the only thing standing between a
 * cashier and doing that is which branch this picks.
 *
 * The one that is easy to miss is `stranded`. `change_paise` is measured against
 * the **cash tender**, so a bill whose cash row has fallen to nought - the
 * cashier tapped a chip, then put the whole amount on card - still reports the
 * whole `cash_received_paise` as change. Green there would tell a cashier to pay
 * out of a drawer that took nothing. It is a figure to clear, not change to
 * give, so it is red and says so.
 *
 * `over` is red for the same reason and one more: `whyPaymentCannotClose` is
 * about to refuse the bill, and a green line would say the sale is fine.
 */
export function balanceStandingOf(split: TenderSplit): BalanceStanding {
  if (split.balance_paise > 0) {
    return { tone: "short", says: "Still to pay", paise: split.balance_paise };
  }
  if (split.balance_paise < 0) {
    return { tone: "over", says: "Over by", paise: -split.balance_paise };
  }
  if (split.change_paise > 0) {
    return split.cash_paise > 0
      ? { tone: "change", says: "Change to give", paise: split.change_paise }
      : {
          tone: "stranded",
          says: "Cash received, but this bill takes none",
          paise: split.change_paise,
        };
  }
  return { tone: "settled", says: "Nothing left to pay", paise: 0 };
}

/**
 * Why this bill cannot be paid for, in a sentence for the counter - or "".
 *
 * Every one of these is a bill the server would refuse with `TENDER_MISMATCH`.
 * Catching them here is the difference between a
 * cashier fixing a figure and a store person unpicking a printed bill days later.
 */
export function whyPaymentCannotClose(split: TenderSplit): string {
  if (split.balance_paise > 0) return "The payment does not cover the whole bill yet.";
  if (split.balance_paise < 0) {
    return "The payment comes to more than the bill. Cash handed over goes in Cash received.";
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
    {
      mode: "upi",
      amount_paise: split.upi_paise,
      // The bank's word when the charge card got one, and nothing at all
      // otherwise - `stampManualUpi` below fills in the cashier's.
      ...(split.upi_confirmed
        ? { upi_state: "confirmed" as const, upi_reference: split.upi_confirmed }
        : {}),
    },
  ];
  return stampManualUpi(rows.filter((row) => row.amount_paise > 0));
}

/**
 * Stamp `manual` on every UPI row missing a stamp, and leave everything else
 * alone - a row `toTenders` already stamped `confirmed` off a charge the bank
 * answered (#248), and every non-UPI row.
 *
 * Two callers, both at the wire boundary (#241): `toTenders` stamps a bill as
 * it is built, and `transport.billBody` runs this over a bill already sitting
 * in the queue from before this build, which would otherwise halt on the
 * server's new refusal (Rule 5, flag never block) - a queued bill is a printed
 * bill, and a halted queue stays halted until a human clears it.
 */
export function stampManualUpi(tenders: BillTender[]): BillTender[] {
  return tenders.map((tender) =>
    tender.mode === "upi" && !tender.upi_state
      ? // The reference goes with the stamp, always: `upi_reference` without
        // `confirmed` is its own refusal at the server, and this function exists
        // precisely to keep bills it does not control off that cliff.
        { ...tender, upi_state: "manual", upi_reference: undefined }
      : tender,
  );
}
