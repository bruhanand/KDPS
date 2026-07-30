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

import type { BillLine, QueuedBill, TillStoreIdentity } from "./types";

export interface ReceiptOptions {
  /** Cash the customer handed over, so the paper can show the change. */
  tenderedPaise?: number;
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
  const change = Math.max(0, (options.tenderedPaise ?? 0) - bill.totals.net_paise);
  const pieces = bill.lines.reduce((n, line) => n + line.qty, 0);
  const customer = bill.customer ?? {};

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

  const totals = [
    ["Pieces", String(pieces)],
    ["Gross", money(bill.totals.gross_paise)],
    ...(bill.totals.discount_paise ? [["You saved", money(bill.totals.discount_paise)]] : []),
    ...(bill.totals.round_paise ? [["Rounding", money(bill.totals.round_paise)]] : []),
    ["Tax included", money(bill.totals.gst_paise)],
  ]
    .map(([label, value]) => `<div class="row"><span>${label}</span><span>${value}</span></div>`)
    .join("");

  const tendered = options.tenderedPaise
    ? `<div class="row"><span>Cash</span><span>${money(options.tenderedPaise)}</span></div>`
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
  <table><thead><tr><th>Item</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Amount</th></tr></thead>
  <tbody>${rows}</tbody></table>
  <hr>
  ${totals}
  <div class="row due"><span>To pay</span><span>${money(bill.totals.net_paise)}</span></div>
  ${tendered}${changeRow}
  <footer class="mid dim">
    ${bill.origin === "offline" ? "Billed offline &middot; will reach head office when the line is back<br>" : ""}
    Exchange within the store's policy, with this bill.<br>Thank you.
  </footer>
</body></html>`;
}
