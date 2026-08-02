import { Fragment, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { formatINR, Money } from "../../../lib/format";
import { qtyFrom } from "../../../till/cart";
import type { CartLine, PricedLine } from "../../../till/cart";
import { hasSlab, ratePercent } from "../../../till/tax";
import { RupeeInput } from "./RupeeInput";

/** Item · Brand · Barcode · Design · Size · Qty · Rate · Disc ₹ · GST ·
 *  Salesman · Net · remove.
 *
 *  GST was eight per cent of a counter screen for a rate and a rupee figure on
 *  every line - twelve numbers to answer a question that gets asked once a bill,
 *  at the end, about the whole bill. Grill Q7 collapsed it to a badge and moved
 *  the answer behind the footer's figure; the three points it frees go where
 *  the ruling sent them - two to the item name, one to the discount box. */
const COLUMN_WIDTHS = [
  "13%",
  "8%",
  "12%",
  "8%",
  "5%",
  "7%",
  "8%",
  "9%",
  "5%",
  "12%",
  "9%",
  "4%",
] as const;

/** The columns staff read today (D10 §4), in the order they read them. */
export function Lines({
  lines,
  salesmen,
  locked,
  onEdit,
  onSalesman,
  onPicked,
  onRemove,
}: {
  lines: PricedLine[];
  salesmen: { id: number; code: string; name: string }[];
  locked: boolean;
  onEdit: (key: string, patch: Partial<CartLine>) => void;
  onSalesman: (key: string, salesman: number | null) => void;
  onPicked: () => void;
  onRemove: (key: string) => void;
}) {
  if (!lines.length) {
    return (
      <p className="muted-cell bill-empty" data-testid="bill-empty">
        Scan the first piece. The cursor is already in the scan box.
      </p>
    );
  }
  return (
    // `bill-grid-wrap` (not just `.table-wrap`) so Billing.css can scope the
    // sticky-header override to this table alone - the exchange table shares
    // `.bill-lines` and keeps the generic wrap's own scroll/rounded-corner
    // behaviour.
    <div className="table-wrap bill-grid-wrap">
      <table className="data bill-grid" data-testid="bill-lines">
        {/* Fixed widths, not content widths. All twelve columns D10 names have
            to be on the counter's screen at once - a Net column that scrolled
            off the right would be the one number the cashier reads aloud. */}
        <colgroup>
          {COLUMN_WIDTHS.map((width, i) => (
            <col key={i} style={{ width }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            <th>Item</th>
            <th>Brand</th>
            <th>Barcode</th>
            <th>Design</th>
            <th>Size</th>
            <th className="num">Qty</th>
            <th className="num">Rate</th>
            <th className="num">Disc ₹</th>
            <th className="num">GST</th>
            <th>Salesman</th>
            <th className="num">Net</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <Fragment key={line.key}>
            <tr data-testid={`bill-line-${line.line_no}`}>
              <td colSpan={line.sold_before_inward ? 2 : 1}>
                <ItemCell line={line} locked={locked} onEdit={onEdit} />
                <SeasonCell line={line} locked={locked} onEdit={onEdit} onPicked={onPicked} />
              </td>
              {/* A sold-before-inward line has no brand - nothing has ever
                  recorded one - so the description takes that column's width
                  rather than leaving it blank beside a box too narrow to read
                  what the cashier just typed in it (browser QA of #186). */}
              {!line.sold_before_inward && <td>{line.brand}</td>}
              <td>
                <span className="mono bill-barcode">{line.barcode}</span>
                <br />
                {/* The "Total Stock" readout staff use today (A3), against the
                    barcode it is a count of rather than against the price. A
                    piece the books have never heard of has no count to show -
                    "0 in stock" would read as "we have run out" (#186). */}
                <span className="muted-cell" data-testid={`bill-stock-${line.line_no}`}>
                  {line.sold_before_inward ? "no count yet" : `${line.stock} in stock`}
                </span>
              </td>
              <td>{line.design}</td>
              <td>{line.size}</td>
              <td className="num">
                <QtyCell line={line} locked={locked} onEdit={onEdit} />
              </td>
              <td className="num">
                <RateCell line={line} locked={locked} onEdit={onEdit} />
              </td>
              <td className="num">
                <DiscountCell line={line} locked={locked} onEdit={onEdit} />
              </td>
              <td className="num">
                <GstBadge line={line} />
              </td>
              <td>
                <select
                  className="select bill-cell"
                  disabled={locked}
                  data-testid={`bill-salesman-${line.line_no}`}
                  aria-label={`Salesman, line ${line.line_no}`}
                  value={line.salesman ?? ""}
                  onChange={(e) =>
                    onSalesman(line.key, e.target.value ? Number(e.target.value) : null)
                  }
                >
                  <option value="">Nobody</option>
                  {salesmen.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </td>
              <td className="num">
                <Money paise={line.net_paise} />
              </td>
              <td>
                <button
                  type="button"
                  className="line-del"
                  disabled={locked}
                  data-testid={`bill-remove-${line.line_no}`}
                  aria-label={`Remove line ${line.line_no}`}
                  onClick={() => onRemove(line.key)}
                >
                  <X size={14} />
                </button>
              </td>
            </tr>
            {/* The offers on their own row, spanning the grid.
                They sat in the Disc column at first, which is sixty pixels
                wide - it holds "₹1,049.70" and nothing longer, so a rule's
                *name* broke to one syllable a line and stood up as a tall thin
                column. A rule is the one thing on this row a cashier has to
                read aloud to a customer who asks why the shirt is cheaper, so
                it gets the width to be read in. */}
            {line.offer_credits.length > 0 && (
              <tr className="bill-offer-row" data-testid={`bill-offers-${line.line_no}`}>
                <td colSpan={COLUMN_WIDTHS.length}>
                  {line.offer_credits.map((credit) => (
                    <span
                      className="bill-offer"
                      data-testid={`bill-offer-${line.line_no}-${credit.offer_id}`}
                      key={credit.offer_id}
                    >
                      {credit.offer_name || "Offer"} · <Money paise={credit.saved_paise} />
                    </span>
                  ))}
                </td>
              </tr>
            )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Which slab this piece was taxed at, and nothing else (#247, grill Q7).
 *
 * "Enough to catch a wrong slab at a glance" was the ruling, and the rate is the
 * whole of that: a ₹4,999 jacket showing 5% is the mistake worth seeing from
 * across the counter, and the rupee figure beside it never helped anybody see
 * it. The bill's own tax total, and where it came from, is one click away in the
 * footer.
 *
 * A line nothing has priced yet is blank rather than "0%": that piece is not
 * zero-rated, it is unpriced, and the box asking for its price is two columns
 * away saying so.
 */
function GstBadge({ line }: { line: PricedLine }) {
  // `hasSlab`, the same test the breakup panel filters on - two spellings of
  // "this line has no slab" can disagree, and a badge saying 0% beside a panel
  // that left the line out is the counter telling two stories.
  if (!hasSlab(line.gst_rate)) return <span className="muted-cell">-</span>;
  return (
    <span
      className="bill-gst-badge"
      data-testid={`bill-gst-${line.line_no}`}
      // The rupees are still one hover away for anybody who wants them - the
      // ruling took them off the screen, not out of the world.
      title={`GST on this line: ${formatINR(line.gst_paise)}`}
    >
      {ratePercent(line.gst_rate)}
    </span>
  );
}

/** What every editable cell in the line grid needs, and nothing more. */
interface CellProps {
  line: PricedLine;
  locked: boolean;
  onEdit: (key: string, patch: Partial<CartLine>) => void;
}

/**
 * What the piece is: the books' word for it, or the cashier's (#186).
 *
 * A sold-before-inward line has no item name because nothing has ever recorded
 * one, so the cell becomes the box where somebody writes what left the shop. It
 * is not optional and the bill will not close without it (`whyItCannotClose`):
 * the server refuses a barcode it cannot place with no words beside it, and it
 * refuses it *after* the receipt has printed, halting the queue behind it.
 *
 * The description is also the only thing this line will ever say about itself
 * until the PT lands - it is what prints on the customer's copy and what the
 * store reads when it goes looking for the piece.
 */
function ItemCell({ line, locked, onEdit }: CellProps) {
  if (!line.sold_before_inward) {
    return (
      <>
        {line.item}
        <br />
      </>
    );
  }
  return (
    <input
      className="input bill-cell"
      data-testid={`bill-desc-${line.line_no}`}
      aria-label={`What this piece is, line ${line.line_no}`}
      autoComplete="off"
      placeholder="What is it?"
      // The box is still narrower than a sentence, and this line's description is
      // the only record of what left the shop - so it is readable on hover as
      // well as on the receipt.
      title={line.manual_desc}
      disabled={locked}
      value={line.manual_desc}
      onChange={(e) => onEdit(line.key, { manual_desc: e.target.value })}
    />
  );
}

/**
 * The season, and the one-tap ask when there is a choice (A2).
 *
 * Never a modal and never a blocker: the line is already on the bill at the
 * oldest live season, and this is how a person changes their mind. It is the
 * only question this screen is allowed to ask mid-sale.
 */
function SeasonCell({ line, locked, onEdit, onPicked }: CellProps & { onPicked: () => void }) {
  if (line.sold_before_inward) {
    // No season, because no cohort - and saying so is the point. This is the row
    // the Dashboard will be counting until the paperwork arrives (#186).
    return (
      <span className="muted-cell" data-testid={`bill-not-in-system-${line.line_no}`}>
        Not in the system yet
      </span>
    );
  }
  if (line.alternatives.length < 2) {
    return <span className="muted-cell">{line.season}</span>;
  }
  return (
    <select
      className="select bill-cell bill-season"
      disabled={locked}
      data-testid={`bill-season-${line.line_no}`}
      aria-label={`Season, line ${line.line_no}`}
      value={line.season}
      onChange={(e) => {
        const picked = line.alternatives.find((a) => a.season === e.target.value);
        if (!picked) return;
        onEdit(line.key, {
          season: picked.season,
          mrp_paise: picked.mrp_paise ?? 0,
          // The other season may be the one nobody priced, so the answer to
          // "does this line still need a price?" moves with the season.
          needs_price: picked.mrp_paise == null,
        });
        onPicked();
      }}
    >
      {line.alternatives.map((a) => (
        <option key={a.season} value={a.season}>
          {a.season}
        </option>
      ))}
    </select>
  );
}

/** The ticket price. Editable only because a piece can reach a shelf with no
 *  MRP recorded (contract, step 3) - and then a human reads it off the tag.
 *
 *  The test is `needs_price`, never the current amount. Keying off the amount
 *  would unmount the box on the first digit typed - "1" is 100 paise, which is
 *  a price - leaving a ₹1,499 garment stuck at ₹1 with no way back, and a bill
 *  so internally consistent that the server would take it. */
function RateCell({ line, locked, onEdit }: CellProps) {
  if (!line.needs_price) return <Money paise={line.mrp_paise} />;
  return (
    <RupeeInput
      testId={`bill-rate-${line.line_no}`}
      label={`Price from the tag, line ${line.line_no}`}
      paise={line.mrp_paise}
      locked={locked}
      placeholder="Price"
      onChange={(paise) => onEdit(line.key, { mrp_paise: paise ?? 0 })}
    />
  );
}

/**
 * A manual discount, the cap it lives under (B2), and what the rulebook gave.
 *
 * The two discounts share a cell because they share a column in the customer's
 * head - "what came off this shirt" - but they never share a number. The box is
 * the cashier's and the cap measures it; the chip below is head office's and is
 * not editable here at all, because the way to change an offer is to change the
 * offer.
 */
function DiscountCell({ line, locked, onEdit }: CellProps) {
  return (
    <>
      <RupeeInput
        testId={`bill-disc-${line.line_no}`}
        label={`Discount, line ${line.line_no}`}
        paise={line.disc_paise}
        locked={locked || line.cap_paise === 0}
        placeholder="0"
        onChange={(paise) => onEdit(line.key, { disc_paise: paise ?? 0 })}
      />
      {line.over_cap && (
        <span className="bill-overcap" data-testid={`bill-overcap-${line.line_no}`}>
          over the cap
        </span>
      )}
      {/* Information, not a gate - and deliberately so. The rulebook (#183) does
          obey this flag: no offer, of any layer, reaches a no-discount piece.
          But nothing in the corpus says a *cashier's* keyed-in discount is
          barred on such a style, and enforcing one here would be inventing brand
          policy - so the cap governs this line like any other and the cashier is
          told what they are discounting. Whether the flag should also bind a
          manual discount is Anand's to rule on. */}
      {line.no_discount && <span className="muted-cell">no-discount style</span>}
    </>
  );
}

/**
 * How many pieces of this line, as whole pieces.
 *
 * A plain controlled `type="number"` is wrong here, and the way it is wrong is
 * expensive. Typing "1.5" into one goes: "1" is 1; "." makes the value
 * momentarily invalid, so the browser reports it as empty and the controlled
 * value snaps back to "1", eating the dot; then "5" lands beside the 1 and the
 * cashier has silently billed **fifteen** pieces. So the text is held here, the
 * way `RupeeInput` holds a half-written amount, and only `qtyFrom` decides what
 * the cart gets - which truncates, so "1.5" is one piece and never 15 and never
 * a fraction on the write path.
 */
function QtyCell({ line, locked, onEdit }: CellProps) {
  const [text, setText] = useState(String(line.qty));
  const shown = useRef(line.qty);

  useEffect(() => {
    if (line.qty === shown.current) return;
    shown.current = line.qty;
    setText(String(line.qty));
  }, [line.qty]);

  return (
    <input
      className="input bill-cell"
      inputMode="numeric"
      disabled={locked}
      data-testid={`bill-qty-${line.line_no}`}
      aria-label={`Quantity, line ${line.line_no}`}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        const qty = qtyFrom(e.target.value);
        shown.current = qty;
        onEdit(line.key, { qty });
      }}
      // Whatever half-written thing is in the box, the count it actually billed
      // is what the cashier should be looking at once they leave it.
      onBlur={() => setText(String(line.qty))}
    />
  );
}
