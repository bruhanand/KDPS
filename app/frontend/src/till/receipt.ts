// The customer's copy (#181, D10 §4, requirement G2).
//
// A whole HTML document rather than a React tree, because what prints is not the
// screen: it goes into an isolated frame that carries none of the app's styles,
// and the hardware spike (#190) may later hand the same string to an ESC/POS
// agent instead of to a browser. Building it as text keeps the one thing the
// customer walks out with independent of how the till happens to render today.
//
// Sized for a 80mm thermal roll, and readable on A4 if that is all a store has.
//
// It carries no cost and no margin (H2), and it says out loud when a bill was
// written with no line to head office - the origin tag is evidence for the daily
// check, and a store person seeing it on the paper knows why head office may not
// have this bill yet.

import { changeFor } from "./cart";
import { splitTax, taxKindFor } from "./gstin";
import type { B2bTaxKind } from "./gstin";
import { describePiece } from "./lookup";
import type {
  BillLine,
  BillTender,
  QueuedBill,
  TillCustomer,
  TillStoreIdentity,
} from "./types";

export interface ReceiptOptions {
  /** Cash the customer physically handed over, so the paper can show the change.
   *  Not what the bill *took* in cash - that is on the bill's own tender rows. */
  cashReceivedPaise?: number;
  storeName?: string;
  /** How a line reads to a customer - "MUFTI Shirt · M · Navy".
   *
   *  Supplied by the screen rather than read off the line, because the bill's
   *  lines carry no description: the wire payload is the contract's, and the
   *  brand, size and colour of a piece are the *server's* to write from the
   *  cohort. The counter has them in the cart it just billed, so it lends them
   *  to the paper. A reprint keeps the finished string rather than re-deriving
   *  one (A7: reprint only, never re-render). */
  describe?: (line: BillLine) => string;
  /** The e-invoice reference, once head office has raised one (#187).
   *
   *  Only ever present on a *reprint*, and that is not a gap: a counter's copy
   *  is printed offline the moment the sale closes, thirty days before anybody
   *  at head office goes near the government portal, so the original always says
   *  "IRN to follow" and always will. A reprint pulled off the posted document
   *  can do better, and should. */
  irn?: string;
}

/**
 * Money for a printed line, always to the paise.
 *
 * Deliberately not `formatINR`, which drops the decimals on a whole rupee: that
 * is right on a screen and wrong in a column of figures somebody adds up by eye.
 */
function money(paise: number): string {
  const grouped = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(paise / 100);
  return `₹${grouped}`;
}

/** Everything a customer typed goes through here. A name is free text on a
 *  document we build by concatenation, and that is the whole recipe for markup
 *  injection if it is not escaped once, in one place. */
function esc(text: string): string {
  return text.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );
}

/** How each tender mode reads to a customer. */
const TENDER_WORDS: Record<string, string> = {
  cash: "Cash",
  card: "Card",
  upi: "UPI",
  credit_note: "Credit note",
};

function when(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleString("en-IN");
}

/** The bill, as paper. */
export function receiptHtml(
  bill: QueuedBill,
  store: TillStoreIdentity,
  options: ReceiptOptions = {},
): string {
  // The same function the screen quoted the customer, not a second copy of the
  // sum: the printed change and the change on the display have to agree. Change
  // is against the *cash* the bill took, never the bill - a ₹1,000 note handed
  // over on a half-carded bill is change on the cash half only.
  const cashTaken = bill.tenders
    .filter((tender) => tender.mode === "cash")
    .reduce((n, tender) => n + tender.amount_paise, 0);
  const change = changeFor(options.cashReceivedPaise ?? 0, cashTaken);
  const pieces = bill.lines.reduce((n, line) => n + line.qty, 0);
  const customer: TillCustomer = bill.customer ?? { name: "", mobile: "", gstin: "" };

  const describe = options.describe ?? ((line: BillLine) => line.manual_desc || line.barcode);
  const rows = bill.lines
    .map(
      (line) => `<tr>
        <td>${esc(describe(line))}<br>
          <span class="dim">${esc(line.barcode)}${line.season ? ` · ${esc(line.season)}` : ""}</span></td>
        <td class="n">${line.qty}</td>
        <td class="n">${money(line.mrp_paise)}</td>
        <td class="n">${money(line.net_paise)}</td>
      </tr>`,
    )
    .join("");

  // What kind of bill this is (#187). Read off the bill, because that is what
  // the counter derived at Save & Print and the customer's two copies must not
  // disagree; derived only as a fallback, for a bill queued before the field
  // existed. A GSTIN with no split beside it is a bill nobody can claim credit
  // on, so this is not a field to leave blank quietly.
  const buyerGstin = customer.gstin ?? "";
  const taxKind: B2bTaxKind = bill.b2b_tax_kind ?? taxKindFor(buyerGstin, store.state_code);
  const taxRows =
    taxKind === "none"
      ? [["Tax included", money(bill.totals.gst_paise)]]
      : splitTax(bill.totals.gst_paise, taxKind).map(
          (part) => [`${part.label} included`, money(part.paise)] as [string, string],
        );

  const totals = [
    ["Pieces", String(pieces)],
    ["Gross", money(bill.totals.gross_paise)],
    ...(bill.totals.discount_paise ? [["You saved", money(bill.totals.discount_paise)]] : []),
    ...(bill.totals.round_paise ? [["Rounding", money(bill.totals.round_paise)]] : []),
    ...taxRows,
  ]
    .map(([label, value]) => `<div class="row"><span>${label}</span><span>${value}</span></div>`)
    .join("");

  // The buyer's own registration, on the paper, above the lines. Without it the
  // document is not a tax invoice and the customer cannot claim the credit the
  // GSTIN was given for - which is the entire reason they handed it over.
  const buyerBlock = buyerGstin
    ? `<p class="dim buyer">Buyer${customer.name ? ` ${esc(customer.name)}` : ""}<br>
        GSTIN ${esc(buyerGstin)}<br>
        ${options.irn ? `IRN ${esc(options.irn)}` : "IRN to follow"}</p>`
    : "";

  // How it was paid, mode by mode. A split bill's customer copy has to say which
  // card was charged what, because that is the line they will query - and a
  // credit note names itself so the paper shows what was spent off which note.
  const tendered = bill.tenders
    .map(
      (tender) =>
        `<div class="row"><span>${TENDER_WORDS[tender.mode] ?? esc(tender.mode)}${
          tender.credit_note ? ` <span class="dim">${esc(tender.credit_note)}</span>` : ""
        }</span><span>${money(tender.amount_paise)}</span></div>`,
    )
    .join("");
  const received =
    options.cashReceivedPaise && options.cashReceivedPaise !== cashTaken
      ? `<div class="row"><span>Cash received</span><span>${money(options.cashReceivedPaise)}</span></div>`
      : "";
  const changeRow = change
    ? `<div class="row"><span>Change</span><span>${money(change)}</span></div>`
    : "";

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>${esc(bill.doc_number)}</title>
<style>
  @page { size: 80mm auto; }
  body { font: 12px/1.45 "Helvetica Neue", Arial, sans-serif; width: 76mm; padding: 4mm; }
  h1 { font-size: 15px; text-align: center; }
  .dim { color: #666; font-size: 10px; }
  .mid { text-align: center; }
  hr { border: 0; border-top: 1px dashed #999; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 2px 0; vertical-align: top; }
  th { font-size: 10px; text-transform: uppercase; border-bottom: 1px solid #000; }
  .n { text-align: right; white-space: nowrap; }
  .row { display: flex; justify-content: space-between; padding: 1px 0; }
  .due { font-weight: 700; font-size: 15px; border-top: 1px solid #000; padding-top: 4px; }
  .buyer { border: 1px solid #999; padding: 3px 4px; }
  footer { padding-top: 6px; }
</style></head>
<body>
  <h1>${esc(options.storeName || store.code)}</h1>
  <p class="mid dim">GSTIN ${esc(store.gstin)}<br>Tax invoice</p>
  <hr>
  <p class="dim">Bill ${esc(bill.doc_number)}<br>${esc(when(bill.billed_at))}${
    customer.name || customer.mobile
      ? `<br>${esc([customer.name, customer.mobile].filter(Boolean).join(" · "))}`
      : ""
  }</p>
  ${buyerBlock}
  <table><thead><tr><th>Item</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Amount</th></tr></thead>
  <tbody>${rows}</tbody></table>
  <hr>
  ${totals}
  <div class="row due"><span>To pay</span><span>${money(bill.totals.net_paise)}</span></div>
  ${tendered}${received}${changeRow}
  <footer class="mid dim">
    ${bill.origin === "offline" ? "Billed offline &middot; will reach head office when the line is back<br>" : ""}
    Exchange within the store's policy, with this bill.<br>Thank you.
  </footer>
</body></html>`;
}

/** One line of a posted bill, as the read serializer sends it.
 *
 *  The money fields are all here, and none of them is optional: a reprint that
 *  filled a column it had not been given would print a nought against a garment
 *  that was discounted or taxed, and the customer's two copies would disagree. */
export interface PostedLine {
  line_no: number;
  direction: string;
  barcode: string;
  season: string;
  brand: string;
  item: string;
  design: string;
  size: string;
  color: string;
  manual_desc: string;
  salesman_code: string;
  salesman_name: string;
  qty: number;
  mrp_paise: number;
  disc_paise: number;
  net_paise: number;
  gst_rate: string;
  gst_paise: number;
}

/** A bill as the *server* has it - `GET /api/sell/sales/{doc_number}`. */
export interface PostedBill {
  doc_number: string;
  billed_at: string;
  origin: string;
  store_code: string;
  store_name: string;
  store_gstin: string;
  customer_name: string;
  customer_mobile: string;
  /** The buyer's registration and the split the bill was raised under (#187).
   *  Both come off the posted document rather than being re-derived: the shop's
   *  registration can change hands and a state code cannot be looked up for a
   *  bill from two years ago, but what this bill charged is a fact it carries. */
  buyer_gstin: string;
  b2b_tax_kind: B2bTaxKind;
  /** Blank until head office has raised one - which is most of a B2B bill's
   *  first month. Blank prints "IRN to follow", exactly as the original did. */
  irn: string;
  lines: PostedLine[];
  tenders: BillTender[];
  gross_paise: number;
  discount_paise: number;
  net_paise: number;
  gst_paise: number;
  round_paise: number;
}

/**
 * A bill found by customer search, as paper (#185, E2).
 *
 * The same template as the till's own reprint, deliberately: a customer holding
 * two copies of one bill should not be able to tell which screen printed them.
 * What differs is where the facts come from - the counter that billed it may be
 * another machine, or last month's - so this reads the posted document and
 * nothing else.
 *
 * It re-renders rather than replaying a stored string, which is the one place the
 * note above ("a reprint keeps the finished string") has to bend: there is no
 * stored string for a bill this device never billed. It is safe for the reason
 * the note exists - the source is the posted document itself, so the paper says
 * what the books say, and A7 is untouched because nothing here can write.
 */
export function postedReceiptHtml(bill: PostedBill): string {
  const cash = bill.tenders.find((tender) => tender.mode === "cash");
  return receiptHtml(
    {
      idempotency_uuid: "",
      store: bill.store_code,
      fy: "",
      till_seq: 0,
      attempts: 0,
      doc_number: bill.doc_number,
      billed_at: bill.billed_at,
      // Anything but "offline" simply drops the offline footnote; a reprint of a
      // bill written offline still says so, because that is a fact about the bill.
      origin: bill.origin === "offline" ? "offline" : "online",
      customer: {
        name: bill.customer_name,
        mobile: bill.customer_mobile,
        gstin: bill.buyer_gstin,
      },
      b2b_tax_kind: bill.b2b_tax_kind,
      lines: bill.lines.map((line) => ({
        line_no: line.line_no,
        direction: line.direction === "return" ? "return" : "sale",
        barcode: line.barcode,
        season: line.season,
        qty: line.qty,
        mrp_paise: line.mrp_paise,
        disc_paise: line.disc_paise,
        net_paise: line.net_paise,
        gst_rate: line.gst_rate,
        gst_paise: line.gst_paise,
        manual_desc: line.manual_desc,
      })),
      tenders: bill.tenders,
      totals: {
        gross_paise: bill.gross_paise,
        discount_paise: bill.discount_paise,
        net_paise: bill.net_paise,
        gst_paise: bill.gst_paise,
        round_paise: bill.round_paise,
      },
    },
    { code: bill.store_code, gstin: bill.store_gstin, state_code: "" },
    {
      storeName: bill.store_name,
      cashReceivedPaise: cash?.amount_paise ?? 0,
      irn: bill.irn,
      // The server writes the brand, item and size onto every line at billing
      // (Rule 3), so unlike the till's own receipt this one is not lent a
      // description - it has the snapshot the bill was printed from.
      describe: (line) => {
        const posted = bill.lines.find((row) => row.line_no === line.line_no);
        if (!posted) return line.barcode;
        return posted.manual_desc || describePiece(posted) || posted.barcode;
      },
    },
  );
}
