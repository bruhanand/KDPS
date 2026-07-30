import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { AlertTriangle, Printer, X } from "lucide-react";

import { PageHeader } from "../../components/PageHeader";
import { useAuth } from "../../auth/AuthContext";
import { Money, paiseToRupees, rupeesToPaise } from "../../lib/format";
import { SyncLight } from "../../till/SyncLight";
import { useTill } from "../../till/TillProvider";
import { addPiece, priceCart, qtyFrom, toDraft, whyItCannotClose } from "../../till/cart";
import type { Cart, CartLine, PricedLine } from "../../till/cart";
import { tillToday } from "../../till/pricing";
import { describePiece, resolveScan, searchPieces } from "../../till/lookup";
import { browserPrintAdapter } from "../../till/print";
import { receiptHtml } from "../../till/receipt";
import type { QueuedBill, TillItem } from "../../till/types";
import { useScanBox } from "../../till/useScanBox";
import { useTillWorld } from "../../till/useTillWorld";
import "./Billing.css";

// ---------------------------------------------------------------------------
// Billing - the counter (#181, D10 §4)
// ---------------------------------------------------------------------------
//
// The most important screen in the store, on the placement staff already know:
// scan box top right and always focused, the line grid in the middle, the
// payment panel on the right, the customer strip under it, totals, and a row of
// plain buttons. RetailJI contributes that placement and nothing else.
//
// Three things about it are decisions rather than taste.
//
// **Every action is a visible button.** No F-keys, no shortcuts, no key handlers
// anywhere on this page beyond Enter in the scan box (Anand's Phase-3 ruling,
// 31 Jul). The browser's own function keys are left alone.
//
// **Save & Print is the commit point, and it commits locally.** The number, the
// shelf and the queue move in one IndexedDB transaction (`commitBill`), the
// receipt prints afterwards, and the server hears about it whenever it can. A
// printer that is off is a banner and a Reprint button - never a lost sale, and
// never a bill number spent on nothing (G2).
//
// **Nothing here shows cost or margin** (H2), and nothing here asks the server
// anything: every price, every tax rate and every stock figure comes from the
// counter's own copy, so the screen behaves identically with the line up or down.
//
// What this slice does not do yet, by ticket: split tender, credit notes and the
// manager PIN are #182, offers are #183, Hold Bill and customer search are #185,
// the sold-before-inward manual line is #186. Each is absent rather than faked.

export default function BillingPage() {
  const { user } = useAuth();
  const { engine, till } = useTill();

  if (!engine || !till) return <NoCounter />;

  return (
    <Counter
      key={engine.storeCode}
      storeName={user?.stores?.find((s) => s.code === engine.storeCode)?.name}
    />
  );
}

function Counter({ storeName }: { storeName?: string }) {
  const { engine, till } = useTill();
  const [cart, setCart] = useState<Cart>({ lines: [], tenderedPaise: 0 });
  const [customer, setCustomer] = useState({ name: "", mobile: "" });
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState("");
  const [printProblem, setPrintProblem] = useState("");
  const [lastBill, setLastBill] = useState<{ bill: QueuedBill; receipt: string } | null>(null);
  const [typed, setTyped] = useState("");
  // The last salesman *picked*, which is not the same as the last one saved: a
  // bill often runs several lines before it closes, and the second piece should
  // land on the person who sold the first (D10 §4), not on whoever sold the
  // previous customer. Nought until somebody picks, and then the counter's copy
  // takes over from what the dataset remembered across the session.
  const [lastPicked, setLastPicked] = useState<number | null>(null);
  // Bumped by every commit so the in-memory copy re-reads the shelf the sale
  // just moved. The sync time covers the other direction.
  const [commits, setCommits] = useState(0);

  const world = useTillWorld(engine?.db ?? null, `${till?.syncedAt ?? ""}#${commits}`);
  const scan = useScanBox(world.loaded);

  const today = useMemo(() => tillToday(), []);
  const bill = useMemo(
    () =>
      priceCart(cart, world, today, {
        capPercent: world.policy.manual_discount_cap_percent,
      }),
    [cart, world, today],
  );
  const blocked = whyItCannotClose(bill);

  // Nothing may be typed into a bill while it is being committed: the cart is
  // read once inside `save`, and a line arriving after that read would be a
  // piece the customer paid for and the queue never heard of.
  const locked = saving;

  const suggestions = useMemo(
    () =>
      typed.trim().length >= 2
        ? searchPieces(world.items, typed).map((piece) => ({
            piece,
            stock: world.stock.find((s) => s.barcode === piece.barcode)?.qty ?? 0,
          }))
        : [],
    [typed, world.items, world.stock],
  );

  const defaultSalesman = lastPicked ?? world.lastSalesman;

  const takePiece = useCallback(
    (piece: TillItem, alternatives: TillItem[], stock: number) => {
      setCart((current) => ({
        ...current,
        lines: [
          ...current.lines,
          { ...addPiece(piece, { stock, alternatives }), salesman: defaultSalesman },
        ],
      }));
      setNote("");
      setTyped("");
    },
    [defaultSalesman],
  );

  const applyScan = useCallback(
    (code: string) => {
      const found = resolveScan(code, world);
      if (!found.barcode) return;
      if (!found.chosen) {
        // A2 / grill Q5: the customer is holding the garment, so this is a
        // sentence rather than a refusal. Billing it as a manual line is #186.
        setNote(
          `Nothing on this counter is barcode ${found.barcode}. ` +
            "Check the tag, or search by design number.",
        );
        setTyped(code.trim());
        return;
      }
      takePiece(found.chosen, found.candidates, found.stock);
    },
    [takePiece, world],
  );

  function editLine(key: string, patch: Partial<CartLine>) {
    setCart((current) => ({
      ...current,
      lines: current.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    }));
  }

  /**
   * Crediting the sale, and the cursor going home afterwards.
   *
   * Picking from a `<select>` leaves the keyboard inside it, so the next scan
   * would type the barcode into the dropdown. The focus patrol deliberately
   * will not take focus off anything a person can type into, so the screen has
   * to hand it back at the moment the picking is done (AC 2).
   */
  function pickSalesman(key: string, salesman: number | null) {
    editLine(key, { salesman });
    setLastPicked(salesman);
    if (salesman != null) void engine?.rememberSalesman(salesman);
    scan.focus();
  }

  function removeLine(key: string) {
    setCart((current) => ({ ...current, lines: current.lines.filter((l) => l.key !== key) }));
    scan.focus();
  }

  function newBill() {
    setCart({ lines: [], tenderedPaise: 0 });
    setCustomer({ name: "", mobile: "" });
    setNote("");
    setPrintProblem("");
    setTyped("");
    scan.focus();
  }

  async function print(receipt: string): Promise<void> {
    const outcome = await browserPrintAdapter.print(receipt);
    setPrintProblem(
      outcome.ok
        ? ""
        : `${outcome.reason} The bill is saved - press Reprint when the printer is ready.`,
    );
  }

  /**
   * Save & Print.
   *
   * The order is the whole of grill Q2: commit first, print second. If printing
   * throws, the sale is already a numbered row in a durable queue and the
   * customer's money is accounted for; if it were the other way round a printer
   * fault would leave a printed receipt with no bill behind it.
   */
  async function save() {
    if (!engine || blocked || saving) return;
    setSaving(true);
    setPrintProblem("");
    try {
      const queued = await engine.commit(
        toDraft(bill, { billedAt: new Date().toISOString(), customer }),
      );
      setCommits((n) => n + 1);
      const receipt = receiptHtml(queued, world.store ?? FALLBACK_STORE, {
        storeName,
        tenderedPaise: bill.tenderedPaise,
        describe: describeFrom(bill.lines),
      });
      setLastBill({ bill: queued, receipt });
      setCart({ lines: [], tenderedPaise: 0 });
      setCustomer({ name: "", mobile: "" });
      setTyped("");
      setNote(`Bill ${queued.doc_number} saved.`);
      await print(receipt);
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
      scan.focus();
    }
  }

  return (
    <div className="page-pad bill-page">
      <PageHeader
        lead={`Next bill ${till?.nextNumber ?? ""}`}
        actions={
          <div className="bill-head">
            <SyncLight />
            <ScanBox
              boxRef={scan.ref}
              value={typed}
              disabled={locked}
              onChange={setTyped}
              onSubmit={applyScan}
            />
          </div>
        }
      />

      {!world.loaded && <p className="warn-note">Opening the counter…</p>}
      {world.loaded && !world.items.length && (
        <p className="warn-note" data-testid="bill-no-price-list">
          This counter has no local price list yet. Sync from Till &amp; Sync before billing.
        </p>
      )}
      {printProblem && (
        <p className="bill-alert" data-testid="bill-print-problem">
          <AlertTriangle size={15} />
          {printProblem}
        </p>
      )}
      {note && (
        <p className="ok-note" data-testid="bill-note">
          {note}
        </p>
      )}

      {suggestions.length > 0 && (
        <Suggestions
          pieces={suggestions}
          onPick={(piece) => {
            const found = resolveScan(piece.barcode, world);
            takePiece(piece, found.candidates, found.stock);
            scan.focus();
          }}
        />
      )}

      <div className="bill-body">
        <section className="bill-lines">
          <Lines
            lines={bill.lines}
            salesmen={world.salesmen}
            locked={locked}
            onEdit={editLine}
            onSalesman={pickSalesman}
            onPicked={scan.focus}
            onRemove={removeLine}
          />
        </section>

        <aside className="bill-pay">
          <Payment
            bill={bill}
            locked={locked}
            onTendered={(paise) => setCart((c) => ({ ...c, tenderedPaise: paise }))}
          />
          <CustomerStrip value={customer} locked={locked} onChange={setCustomer} />
        </aside>
      </div>

      <div className="bill-foot">
        <Totals bill={bill} />
        <div className="bill-actions">
          {blocked && (
            <span className="bill-blocked" data-testid="bill-blocked">
              {blocked}
            </span>
          )}
          <button
            type="button"
            className="btn btn-cta btn-lg"
            data-testid="bill-save"
            disabled={Boolean(blocked) || saving}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : "Save & Print"}
          </button>
          <button
            type="button"
            className="btn"
            data-testid="bill-reprint"
            disabled={!lastBill || saving}
            onClick={() => lastBill && void print(lastBill.receipt)}
          >
            <Printer size={15} />
            {lastBill ? `Reprint ${lastBill.bill.doc_number}` : "Reprint"}
          </button>
          <button
            type="button"
            className="btn"
            data-testid="bill-new"
            disabled={saving}
            onClick={newBill}
          >
            New bill
          </button>
        </div>
      </div>
    </div>
  );
}

/** Where the store's own registration has not landed yet. The receipt still
 *  prints - a customer's copy with no GSTIN on it is better than no copy. */
const FALLBACK_STORE = { code: "", gstin: "", state_code: "" };

/** How a line reads on paper, from the cart the counter just billed. */
function describeFrom(lines: PricedLine[]) {
  const words = new Map(lines.map((line) => [line.line_no, describePiece(line)]));
  return (line: { line_no: number; barcode: string }) => words.get(line.line_no) || line.barcode;
}

// --- the scan box ----------------------------------------------------------

/**
 * One box, two jobs (D10 §4).
 *
 * A wedge scanner types a barcode into it and sends Enter; a person types a name
 * or a design number into it for the tag that will not scan. Which happened is
 * not a mode anybody picks - a code that resolves is a scan, and anything else
 * offers what it could have meant.
 *
 * The only key this page handles is Enter, and it handles it here.
 */
function ScanBox({
  boxRef,
  value,
  disabled,
  onChange,
  onSubmit,
}: {
  boxRef: RefObject<HTMLInputElement>;
  value: string;
  disabled: boolean;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
}) {
  return (
    <input
      ref={boxRef}
      className="input bill-scan"
      data-testid="bill-scan"
      autoComplete="off"
      disabled={disabled}
      placeholder="Scan a tag, or type a design number"
      aria-label="Scan a tag, or type a design number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        onSubmit(value);
      }}
    />
  );
}

function Suggestions({
  pieces,
  onPick,
}: {
  pieces: { piece: TillItem; stock: number }[];
  onPick: (piece: TillItem) => void;
}) {
  return (
    <div className="card section-card bill-suggest" data-testid="bill-suggestions">
      <p className="eyebrow">Did you mean</p>
      <div className="bill-suggest-rows">
        {pieces.map(({ piece, stock }) => (
          <button
            key={`${piece.barcode}/${piece.season}`}
            type="button"
            className="btn bill-suggest-row"
            data-testid={`bill-suggest-${piece.barcode}`}
            onClick={() => onPick(piece)}
          >
            <span>{describePiece(piece)}</span>
            <span className="muted-cell">
              {piece.season} · {stock} in stock
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// --- the line grid ---------------------------------------------------------

/** Item · Brand · Barcode · Design · Size · Qty · Rate · Disc ₹ · GST ·
 *  Salesman · Net · remove. */
const COLUMN_WIDTHS = [
  "11%",
  "8%",
  "12%",
  "8%",
  "5%",
  "7%",
  "8%",
  "8%",
  "8%",
  "12%",
  "9%",
  "4%",
] as const;

/** The columns staff read today (D10 §4), in the order they read them. */
function Lines({
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
    <div className="table-wrap">
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
            <tr key={line.key} data-testid={`bill-line-${line.line_no}`}>
              <td>
                {line.item}
                <br />
                <SeasonCell line={line} locked={locked} onEdit={onEdit} onPicked={onPicked} />
              </td>
              <td>{line.brand}</td>
              <td>
                <span className="mono bill-barcode">{line.barcode}</span>
                <br />
                {/* The "Total Stock" readout staff use today (A3), against the
                    barcode it is a count of rather than against the price. */}
                <span className="muted-cell" data-testid={`bill-stock-${line.line_no}`}>
                  {line.stock} in stock
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
                {line.gst_rate}%
                <br />
                <span className="muted-cell">
                  <Money paise={line.gst_paise} />
                </span>
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
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What every editable cell in the line grid needs, and nothing more. */
interface CellProps {
  line: PricedLine;
  locked: boolean;
  onEdit: (key: string, patch: Partial<CartLine>) => void;
}

/**
 * The season, and the one-tap ask when there is a choice (A2).
 *
 * Never a modal and never a blocker: the line is already on the bill at the
 * oldest live season, and this is how a person changes their mind. It is the
 * only question this screen is allowed to ask mid-sale.
 */
function SeasonCell({ line, locked, onEdit, onPicked }: CellProps & { onPicked: () => void }) {
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
      onChange={(paise) => onEdit(line.key, { mrp_paise: paise })}
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
        onChange={(paise) => onEdit(line.key, { disc_paise: paise })}
      />
      {line.offer_paise > 0 && (
        <span
          className="bill-offer"
          data-testid={`bill-offer-${line.line_no}`}
          title={line.offer_label}
        >
          {line.offer_label || "Offer"} · <Money paise={line.offer_paise} />
        </span>
      )}
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

/**
 * An amount in rupees, held as integer paise.
 *
 * The typed text is state of its own so a half-written "12." survives the
 * keystroke that made it: parsing on every change and writing the parse back
 * would delete the decimal point as the cashier types it. Only text that is
 * actually an amount reaches the cart (`rupeesToPaise`, ADR-0004 - never
 * `Number(x) * 100`).
 */
function RupeeInput({
  testId,
  label,
  paise,
  locked,
  placeholder,
  onChange,
}: {
  testId: string;
  label: string;
  paise: number;
  locked: boolean;
  placeholder: string;
  onChange: (paise: number) => void;
}) {
  const [text, setText] = useState(paise ? paiseToRupees(paise) : "");
  const shown = useRef(paise);

  useEffect(() => {
    // Follow the cart when something other than this box moved the number - a
    // season swap changing the ticket price, or a new bill clearing it.
    if (paise === shown.current) return;
    shown.current = paise;
    setText(paise ? paiseToRupees(paise) : "");
  }, [paise]);

  return (
    <input
      className="input bill-cell"
      inputMode="decimal"
      data-testid={testId}
      aria-label={label}
      disabled={locked}
      placeholder={placeholder}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        const parsed = e.target.value.trim() === "" ? 0 : rupeesToPaise(e.target.value);
        if (parsed === null) return;
        shown.current = parsed;
        onChange(parsed);
      }}
    />
  );
}

// --- the payment panel -----------------------------------------------------

/** Cash only in this slice; card, UPI and credit notes are #182. */
function Payment({
  bill,
  locked,
  onTendered,
}: {
  bill: ReturnType<typeof priceCart>;
  locked: boolean;
  onTendered: (paise: number) => void;
}) {
  return (
    <section className="card section-card bill-panel">
      <p className="eyebrow">To pay</p>
      <p className="bill-due" data-testid="bill-due">
        <Money paise={bill.net_paise} />
      </p>
      <div className="field">
        <label htmlFor="bill-cash">Cash taken</label>
        <RupeeInput
          testId="bill-cash"
          label="Cash taken"
          paise={bill.tenderedPaise}
          locked={locked}
          placeholder="0"
          onChange={onTendered}
        />
      </div>
      <div className="bill-row">
        <span>Change</span>
        <span data-testid="bill-change">
          <Money paise={bill.changePaise} />
        </span>
      </div>
      <p className="muted-cell">
        Card, UPI and credit notes arrive with split tender; this counter takes cash.
      </p>
    </section>
  );
}

function CustomerStrip({
  value,
  locked,
  onChange,
}: {
  value: { name: string; mobile: string };
  locked: boolean;
  onChange: (v: { name: string; mobile: string }) => void;
}) {
  return (
    <section className="card section-card bill-panel">
      <p className="eyebrow">Customer</p>
      <div className="field">
        <label htmlFor="bill-mobile">Mobile</label>
        <input
          id="bill-mobile"
          className="input"
          data-testid="bill-mobile"
          autoComplete="off"
          disabled={locked}
          value={value.mobile}
          onChange={(e) => onChange({ ...value, mobile: e.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor="bill-customer-name">Name</label>
        <input
          id="bill-customer-name"
          className="input"
          data-testid="bill-customer-name"
          autoComplete="off"
          disabled={locked}
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
        />
      </div>
      <p className="muted-cell">The bill works without either.</p>
    </section>
  );
}

function Totals({ bill }: { bill: ReturnType<typeof priceCart> }) {
  return (
    <div className="bill-totals" data-testid="bill-totals">
      <Figure label="Pieces" value={String(bill.pieces)} />
      <Figure label="Gross" value={<Money paise={bill.gross_paise} />} />
      {bill.saved_paise > 0 && (
        <Figure
          label="You saved"
          value={<Money paise={bill.saved_paise} />}
          testId="bill-saved"
        />
      )}
      {bill.round_paise !== 0 && (
        <Figure label="Rounding" value={<Money paise={bill.round_paise} />} />
      )}
      <Figure label="Tax included" value={<Money paise={bill.gst_paise} />} />
      <Figure label="Net" value={<Money paise={bill.net_paise} />} testId="bill-net" strong />
    </div>
  );
}

function Figure({
  label,
  value,
  testId,
  strong,
}: {
  label: string;
  value: React.ReactNode;
  testId?: string;
  strong?: boolean;
}) {
  return (
    <div className={strong ? "bill-figure bill-figure-strong" : "bill-figure"}>
      <span className="bill-figure-label">{label}</span>
      <span data-testid={testId}>{value}</span>
    </div>
  );
}

function NoCounter() {
  return (
    <div className="page-pad">
      <PageHeader lead="The counter." />
      <p className="warn-note" data-testid="bill-no-counter">
        This login is not a counter. A till signs in as one store: the local price list, the
        credit notes and the manager authorisations all belong to a single shop, so a login
        that can see several has no counter to bill from.
      </p>
    </div>
  );
}
