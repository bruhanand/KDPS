// What travels between the counter and the server (#180, D10 step 3).
//
// Written by hand rather than generated: `src/lib/api-schema.ts` is produced from
// the API's OpenAPI document, and these two payloads are the till's, which means
// the *till* has to keep working when it has not spoken to a server for a week.
// The shapes here are the contract's (`docs/features/pos-store-front/
// api-contract.md`, step 3, including its 30 Jul amendment), and the fields the
// amendment made nullable are nullable here.

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

export interface BillTender {
  mode: string;
  amount_paise: number;
  credit_note?: string;
}

export interface BillTotals {
  gross_paise: number;
  discount_paise: number;
  net_paise: number;
  gst_paise: number;
  round_paise: number;
}

/** A bill as the screen hands it to the till: everything except its identity.
 *  The number, the financial year and the idempotency key are the till layer's
 *  to assign, and assigning them is the commit (see `numbering.ts`). */
export interface BillDraft {
  billed_at: string;
  origin?: "offline" | "online" | "paper";
  customer?: { name?: string; mobile?: string; gstin?: string };
  lines: BillLine[];
  tenders: BillTender[];
  totals: BillTotals;
  exchange?: Record<string, unknown>;
  override?: { user_id: number; kind: string };
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
