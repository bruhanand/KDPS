// What travels between the counter and the server (#180, D10 step 3).
//
// Written by hand rather than generated: `src/lib/api-schema.ts` is produced from
// the API's OpenAPI document, and these two payloads are the till's, which means
// the *till* has to keep working when it has not spoken to a server for a week.
// The shapes here are the contract's (`docs/features/pos-store-front/
// api-contract.md`, step 3, including its 30 Jul amendment), and the fields the
// amendment made nullable are nullable here.

import type { B2bTaxKind } from "./gstin";

/** One piece as the counter knows it: a barcode in a season, at a ticket price. */
export interface TillItem {
  barcode: string;
  season: string;
  design: string;
  brand: string;
  item: string;
  size: string;
  color: string;
  hsn: string;
  /** Null - never nought - when nobody has recorded an MRP for this lot. The
   *  contract is explicit: a zero here would bill a garment at nothing and post
   *  no revenue or tax against it, so a screen must ask a human for the price
   *  rather than treat this as free. */
  mrp_paise: number | null;
  no_discount: boolean;
}

export interface TillStock {
  barcode: string;
  qty: number;
}

export interface TillGstSlab {
  hsn_prefix: string;
  threshold_paise: number;
  /** Two-decimal strings, so the till's back-calculation out of an MRP-inclusive
   *  price cannot drift a paise from the server's. */
  rate_below: string;
  rate_above: string;
  effective_from: string;
}

export interface TillOffer {
  id: number;
  /** What the counter calls it - the chip on the line and the "you saved" line
   *  read this, so it is the one field here a customer ever hears out loud. */
  name: string;
  layer: string;
  brand?: string;
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  reward_type: string;
  reward_config: Record<string, unknown>;
  item_scope: Record<string, unknown>;
  starts_on: string;
  ends_on: string | null;
  combinable: boolean;
  priority: number;
}

/** One rule this line's discount was chosen over, and by how much. */
export interface OfferCredit {
  offer_id: number;
  offer_name: string;
  saved_paise: number;
}

export interface StackedCredit extends OfferCredit {
  layer: string;
}

/**
 * Why a line cost what it cost - what rides to `SaleLine.offer_evidence` (B3).
 *
 * A wire shape rather than an engine one, which is why it lives here: it is
 * written at the counter, sent up with the bill, stored on the line, and read
 * months later by the daily applied-versus-rulebook check when the rule itself
 * may have been ended and replaced twice over.
 */
export interface OfferEvidence {
  offer_id: number | null;
  offer_name: string;
  layer: string;
  saved_paise: number;
  beat: OfferCredit[];
  stack: StackedCredit[];
}

/** Nothing applied. Written as `{}`, exactly as the server writes it. */
export type NoOffer = Record<string, never>;

export interface TillCreditNote {
  number: string;
  remaining_paise: number;
  expires_on: string;
}

export interface TillSalesman {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
}

export interface TillManager {
  user_id: number;
  name: string;
  till_pin_hash: string;
}

/** A selling period, with the master's own ordering. Seasons are named, never
 *  dated, so "older" is `sort_order` and nothing else - and a closed season sorts
 *  behind every open one however old it is. */
export interface TillSeason {
  code: string;
  name: string;
  status: string;
  sort_order: number;
}

/** Somebody KDPS has billed before, as the last dataset pull left them (#245).
 *
 *  Deliberately a different type from `TillCustomer` even though the three fields
 *  match today, because they are answers to different questions: `TillCustomer`
 *  is who *this bill* is for and is snapshotted onto it, this is a row in the
 *  shared phone book the typeahead searches. Only one of the two can grow a
 *  field - a customer's last visit belongs on the master, never on a printed
 *  bill - and collapsing them now is what would make that addition silently
 *  change what every cart carries.
 *
 *  All-KDPS, not this store's: a Deoghar regular must be recognised in Ranchi
 *  (grill Q6). No purchase history rides down with it. */
export interface TillKnownCustomer {
  mobile: string;
  name: string;
  gstin: string;
}

/** The shop floor's money dials. One today; the shape is here so a second is a
 *  field rather than a section. */
export interface TillPolicy {
  /** How much of a line's MRP a cashier may knock off on their own, as a
   *  two-decimal string. Above it the bill needs a manager (B2), which the till
   *  cannot yet obtain - so above it the till does not let the bill close. */
  manual_discount_cap_percent: string;
}

export interface TillStoreIdentity {
  code: string;
  gstin: string;
  state_code: string;
}

/** `GET /api/sell/dataset`. */
export interface DatasetPayload {
  cursor: string;
  full: boolean;
  store: TillStoreIdentity;
  items: TillItem[];
  stock: TillStock[];
  gst_slabs: TillGstSlab[];
  offers: TillOffer[];
  credit_notes: TillCreditNote[];
  salesmen: TillSalesman[];
  managers: TillManager[];
  seasons: TillSeason[];
  policy: TillPolicy;
  /** Everybody the business has billed, deltaed by the same cursor as the items.
   *  No `deleted` sibling: a customer row is never removed in v1. */
  customers: TillKnownCustomer[];
  deleted: {
    items: string[];
    offers: number[];
    credit_notes: string[];
  };
}

/** `GET /api/sell/register` - what the server has accepted from this counter. */
export interface RegisterPayload {
  fy: string;
  last_accepted_seq: number;
  holes: number[];
  hole_count: number;
  series_open: boolean;
}

/** `POST /api/sell/register/handover` - what a new machine is told when it takes
 *  over a store's counter (#189).
 *
 *  `unsynced_hint` is bounded at 200 and `hole_count` is not, deliberately: a
 *  machine that died at bill 5,000 leaves more receipts than a response should
 *  carry, and a screen listing 200 without saying so would tell somebody they
 *  had finished when they had not. */
export interface HandoverPayload {
  resume_from_seq: number;
  unsynced_hint: number[];
  hole_count: number;
}

/** A handover as the counter remembers it - the job list a store works down. */
export interface HandoverState extends HandoverPayload {
  /** When the handover was done, ISO, by the till's own clock. */
  at: string;
}

/**
 * Numbers this counter has keyed back in from their printed copies.
 *
 * Kept apart from the handover, and kept for the *year* rather than for the
 * handover, because it is what makes "exactly once" true rather than what makes
 * a screen tick a box. Three things would each defeat a weaker home for it: a
 * re-entered bill leaves the queue as soon as the server takes it, the handover
 * list is something a store puts away when it is finished, and a page reload
 * with the same address in the bar would happily do the whole thing again.
 *
 * `fy` scopes it because the counter restarts at 1 every April, so last year's
 * bill 61 and this year's are two different bills.
 */
export interface PaperEntered {
  fy: string;
  seqs: number[];
}

export interface BillLine {
  line_no: number;
  direction: "sale" | "return";
  barcode: string;
  season?: string;
  qty: number;
  mrp_paise: number;
  disc_paise: number;
  net_paise: number;
  gst_rate: string;
  gst_paise: number;
  salesman?: number | null;
  offer_id?: number | null;
  offer_evidence?: OfferEvidence | NoOffer;
  manual_desc?: string;
  override_by?: number | null;
}

/** One piece coming back on a bill, as the wire carries it (#184).
 *
 *  Everything money-shaped on it is what the *original* bill charged, not what
 *  today's price list says: `refund_paise` is what the customer actually paid for
 *  that quantity (D2) and `gst_rate`/`gst_paise` are the tax inside it at the
 *  rate that bill was raised under. The server recomputes both and refuses the
 *  whole bill where either is a paisa out. */
export interface BillExchangeLine {
  line_no: number;
  barcode: string;
  season?: string;
  qty: number;
  refund_paise: number;
  gst_rate: string;
  gst_paise: number;
  reason: string;
  /** Good goes back on the shelf; damaged goes to quarantine and never becomes
   *  sellable again without somebody looking at it (D3). */
  condition: "good" | "damaged";
  /** Which line of the original bill this gives back. */
  original_line: number;
}

/** The exchange block on a bill: which bill is being given back against, and
 *  which of its lines. The server resolves the original from `(fy, till_seq)`
 *  pinned to the billing store, so the pair is the whole reference. */
export interface BillExchange {
  original: { fy: string; till_seq: number };
  lines: BillExchangeLine[];
}

export interface BillTender {
  /** The four trimmed modes and no others - `SaleTender.Mode` on the server, and
   *  a `ChoiceField` there, so a fifth string is a bill the queue halts on. */
  mode: "cash" | "card" | "upi" | "credit_note";
  amount_paise: number;
  credit_note?: string;
  /** How the money was proven - required by the server on a UPI row, forbidden
   *  on every other mode (#241). The till only ever sends `manual` until the QR
   *  charge card (#248) lands. */
  upi_state?: "confirmed" | "manual";
  /** The acquirer's transaction reference. Only ever set alongside `confirmed`. */
  upi_reference?: string;
}

export interface BillTotals {
  gross_paise: number;
  discount_paise: number;
  net_paise: number;
  gst_paise: number;
  round_paise: number;
}

/** Who the bill is for, as the counter has them.
 *
 *  All three are optional to a *sale* and none is asked for: the mobile is for
 *  finding the bill again, the name reads on the paper, and a GSTIN is what
 *  turns a retail bill into a B2B tax invoice with a thirty-day clock on head
 *  office behind it (#187, grill Q8). Spelled once because the cart, the hold
 *  and the wire all carry the same three fields, and a fourth added to two of
 *  the three would be a hold that quietly lost it. */
export interface TillCustomer {
  name: string;
  mobile: string;
  gstin: string;
}

/** A bill as the screen hands it to the till: everything except its identity.
 *  The number, the financial year and the idempotency key are the till layer's
 *  to assign, and assigning them is the commit (see `numbering.ts`). */
export interface BillDraft {
  billed_at: string;
  origin?: "offline" | "online" | "paper";
  customer?: TillCustomer;
  /** The split the customer's copy was printed with. The server derives its own
   *  from the same GSTIN and flags a disagreement rather than preferring either
   *  (contract step 11) - so this is evidence about the paper, not an
   *  instruction. "none" on every B2C bill. */
  b2b_tax_kind?: B2bTaxKind;
  lines: BillLine[];
  tenders: BillTender[];
  totals: BillTotals;
  /** A piece coming back on this same bill (#184). Absent on an ordinary sale,
   *  which is almost all of them. */
  exchange?: BillExchange;
  /** The manager's tap: who authorised the exceptions on this bill, what they
   *  were shown, and when they typed the PIN (which is not Save & Print). */
  override?: { user_id: number; kind: string; at: string };
}

/** A bill after the commit: numbered, keyed, and in the queue. This is the exact
 *  body `POST /api/sell/sales` takes, plus the queue's own bookkeeping. */
export interface QueuedBill extends BillDraft {
  /** Dexie's insertion order, and therefore the FIFO the queue drains in. */
  id?: number;
  idempotency_uuid: string;
  store: string;
  fy: string;
  till_seq: number;
  origin: "offline" | "online" | "paper";
  /** What the customer's copy says, rendered at the till so the counter can
   *  name the bill before the server has ever seen it. */
  doc_number: string;
  /** How many times this bill has been offered to the server. Evidence for the
   *  exception card, and the input to the backoff. */
  attempts: number;
  last_error?: string;
}

/** What the server answered for a bill the queue drained. */
export interface AcceptedBill {
  doc_number: string;
  id: number;
  flags: string[];
}

/** A bill the server refused for a reason retrying cannot mend. */
export interface QueueHalt {
  doc_number: string;
  idempotency_uuid: string;
  code: string;
  message: string;
  at: string;
}
