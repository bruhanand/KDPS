import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, Gift, KeyRound, PauseCircle, Plus, Printer, Search, X } from "lucide-react";

import { PageHeader } from "../../components/PageHeader";
import { useAuth } from "../../auth/AuthContext";
import { Money, paiseToRupees, rupeesToPaise } from "../../lib/format";
import { SyncLight } from "../../till/SyncLight";
import { useTill } from "../../till/TillProvider";
import {
  addPiece,
  emptyCart,
  priceCart,
  qtyFrom,
  toDraft,
  whyItCannotClose,
} from "../../till/cart";
import type { Cart, CartLine, PricedLine } from "../../till/cart";
import type { HeldBill } from "../../till/db";
import { heldPayload, holdsToReview, restoreHold } from "../../till/held";
import { tillToday } from "../../till/pricing";
import { describePiece, resolveScan, searchPieces } from "../../till/lookup";
import { whoAuthorised, OVER_CAP_DISCOUNT, UNVERIFIED_NOTE } from "../../till/pin";
import type { Ask, Authorisation, AuthorisationKind } from "../../till/pin";
import { browserPrintAdapter } from "../../till/print";
import { receiptHtml } from "../../till/receipt";
import { newNote } from "../../till/tender";
import type { NoteStanding, Payment } from "../../till/tender";
import type { QueuedBill, TillItem, TillManager } from "../../till/types";
import { useScanBox } from "../../till/useScanBox";
import { useTillWorld } from "../../till/useTillWorld";
// The house modal (`.modal-backdrop` / `.modal` / `.modal-head`), which every
// screen with a dialog on it borrows from the same place.
import "../Booking.css";
import { newUuid } from "../../till/uuid";
import { HeldBills } from "./HeldBills";
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
// The payment panel is the four trimmed modes and a manager's PIN (#182). Three
// things about it are also decisions.
//
// **Cash is the balance until somebody types in it.** An ordinary all-cash sale
// should not need the total keyed into a box to say so, and a split should be
// exactly as explicit as it is. `tender.ts` holds that rule.
//
// **A credit note is checked against this counter's own cached list**, offline,
// same-store only (grill Q4). A note it does not recognise may still be genuine
// and simply unsynced, with the customer standing there - so it takes a manager
// and goes up flagged, which is what the server does with it too.
//
// **The manager types a PIN, not a name.** The PIN establishes who they are, and
// the bill records it - and an authorisation only covers what the manager was
// shown, so an exception keyed in after they walked away asks again.
//
// **A hold is not a bill** (#185, grill Q13). Parking a cart writes one row in
// one local table: no number is taken, no piece leaves the shelf, nothing is
// queued. Picking one up prices it again from today's world, because a bill kept
// overnight is sold at tomorrow's prices and offers, not at the ones it happened
// to be parked under.
//
// What this slice does not do yet, by ticket: the sold-before-inward manual line
// is #186. Absent rather than faked.

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
  const [params] = useSearchParams();
  const [cart, setCart] = useState<Cart>(emptyCart);
  const [customer, setCustomer] = useState({ name: "", mobile: "" });
  const [saving, setSaving] = useState(false);
  const [holding, setHolding] = useState(false);
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
  // just moved - and, since #182, the credit notes it just spent. The sync time
  // covers the other direction.
  const [commits, setCommits] = useState(0);
  /** Open when a manager is being asked for their PIN, carrying exactly what
   *  they are being shown - which is also what their approval will cover. */
  const [asking, setAsking] = useState<Ask[] | null>(null);
  /**
   * Wrong PINs at this counter, and when the pause they earned runs out.
   *
   * Held here rather than inside the modal, which is the whole point: a count
   * that lived in the modal would be cleared by closing it, and closing it is
   * one click - so three tries per half minute would become three tries per
   * click, which is no limit at all. It is still only a speed bump; the hash is
   * on this device by design (grill Q1), so what it buys is somebody guessing
   * having to stand at the counter visibly doing nothing.
   */
  const [wrongPins, setWrongPins] = useState(0);
  // The hold list opens on demand, and opens itself when the Dashboard's "bills
  // on hold" row sent somebody here to clear them (`/sell?holds=1`). Read once,
  // into state: after that the panel is the cashier's to open and close, and a
  // value that kept re-reading the address bar would spring open again on every
  // render behind their back.
  const [showHolds, setShowHolds] = useState(() => params.has("holds"));

  const world = useTillWorld(engine?.db ?? null, `${till?.syncedAt ?? ""}#${commits}`);
  const scan = useScanBox(world.loaded);

  // The pause runs down on its own, whether or not the modal is open.
  useEffect(() => {
    if (wrongPins < WRONG_PINS_BEFORE_A_PAUSE) return;
    const timer = setTimeout(() => setWrongPins(0), PAUSE_MS);
    return () => clearTimeout(timer);
  }, [wrongPins]);

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
  // piece the customer paid for and the queue never heard of. Parking one is the
  // same read and the same hazard, one table down.
  const locked = saving || holding;

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

  function editPayment(patch: Partial<Payment>) {
    setCart((current) => ({ ...current, payment: { ...current.payment, ...patch } }));
  }

  function newBill() {
    setCart(emptyCart());
    setCustomer({ name: "", mobile: "" });
    setNote("");
    setPrintProblem("");
    setTyped("");
    scan.focus();
  }

  // --- bills on hold (#185, grill Q13) --------------------------------------

  const holds = till?.held ?? [];
  // Recomputed against the list rather than stored: "before today" is a fact
  // about the clock, and a flag written at park time would be wrong by morning.
  const toReview = useMemo(() => holdsToReview(holds), [holds]);
  // Two reasons a parked bill may not be picked up yet, and both would be silent
  // damage rather than an error:
  //
  //   · an open cart would be thrown away by the one that replaces it;
  //   · a counter whose copy has not loaded would reprice every line against an
  //     empty world - which is to say against the prices the hold was parked at -
  //     while the hold itself disappeared. That is the exact thing grill Q13's
  //     "reprices at that day's offers" forbids, and it is reachable: the
  //     Dashboard's `?holds=1` opens this list at mount, before the world lands.
  const holdsBlocked = !world.loaded
    ? "Opening the counter… a parked bill is priced at today's rates, so it waits for the price list."
    : cart.lines.length
      ? "Save, hold or clear the bill on screen before picking up another."
      : "";

  /**
   * Park the bill and clear the counter for the next customer.
   *
   * One tap, and the customer's name is the label when the strip has one -
   * "label optional" (grill Q13) with nothing extra for a cashier to fill in. A
   * hold with no name identifies itself by what is in it.
   *
   * The screen locks while it writes, for the same reason Save & Print does: the
   * cart is read once, and a piece scanned after that read is a piece that is
   * neither on the hold nor on the screen.
   */
  async function holdBill() {
    if (!engine || !cart.lines.length || locked) return;
    setHolding(true);
    try {
      await engine.hold({
        held_uuid: newUuid(),
        label: customer.name.trim(),
        payload: heldPayload(cart, customer, {
          net_paise: bill.net_paise,
          pieces: bill.pieces,
        }),
      });
      setCart(emptyCart());
      setCustomer({ name: "", mobile: "" });
      setTyped("");
      setNote("Bill held. Scan the next customer's first piece.");
      setShowHolds(false);
    } catch (error) {
      setNote(messageOf(error));
    } finally {
      setHolding(false);
      scan.focus();
    }
  }

  /** Pick a parked bill back up, at today's prices. */
  async function resumeHold(hold: HeldBill) {
    if (!engine || holdsBlocked) return;
    const restored = restoreHold(hold, world);
    setCart(restored.cart);
    setCustomer(restored.customer);
    setShowHolds(false);
    setNote(
      restored.staleLines
        ? "Bill picked up. Priced at today's rates - check the lines the counter no longer stocks."
        : "Bill picked up, priced at today's rates.",
    );
    try {
      // The hold goes only after the cart is on screen: if this throws, the cart
      // is in front of the cashier and the hold is still in the list, which is a
      // duplicate somebody can see rather than a bill nobody has.
      await engine.releaseHold(hold.held_uuid);
    } catch (error) {
      setNote(`Bill picked up, but it is still on the hold list: ${messageOf(error)}`);
    }
    scan.focus();
  }

  /** A hold answered at day close - kept for tomorrow, or let go. */
  async function answerHold(work: Promise<void>) {
    try {
      await work;
    } catch (error) {
      setNote(messageOf(error));
    }
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
        cashReceivedPaise: cart.payment.cash_received_paise,
        describe: describeFrom(bill.lines),
      });
      setLastBill({ bill: queued, receipt });
      setCart(emptyCart());
      setCustomer({ name: "", mobile: "" });
      setTyped("");
      setNote(`Bill ${queued.doc_number} saved.`);
      await print(receipt);
    } catch (error) {
      setNote(messageOf(error));
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
      {/* A gift is earned, not deducted: it takes nothing off any line, so
          without this row the counter has no way of knowing the customer is owed
          a trolley - and D5 Q11 is clear that it "only counts if it was actually
          handed to the customer". Scanning it puts it on the bill at its token
          price like any other piece. The out-of-stock fallback the engine also
          supports has no control here yet; that needs a decline gesture and a
          re-price, and it is its own ticket. */}
      {bill.entitlements.map((gift) => (
        <p className="ok-note" data-testid={`bill-gift-${gift.offer_id}`} key={gift.offer_id}>
          <Gift size={15} /> This bill earns a gift: {gift.offer_name}. Scan it onto the bill
          {gift.token_price_paise > 0 ? (
            <>
              {" "}
              at its token price of <Money paise={gift.token_price_paise} />
            </>
          ) : (
            " free of charge"
          )}
          , and hand it over.
        </p>
      ))}

      {/* Day close, until store open/close (I3) defines one properly: a bill
          parked before today is put to the store, and stays parked until
          somebody answers. Nothing expires on a timer (grill Q13). */}
      {toReview.length > 0 && (
        <p className="bill-alert" data-testid="bill-holds-due">
          <AlertTriangle size={15} />
          {toReview.length === 1
            ? "1 bill has been on hold since before today."
            : `${toReview.length} bills have been on hold since before today.`}{" "}
          Keep each one for tomorrow or let it go.
          <button type="button" className="btn" onClick={() => setShowHolds(true)}>
            Review them
          </button>
        </p>
      )}

      {showHolds && (
        <HeldBills
          holds={holds}
          toReview={toReview}
          blocked={holdsBlocked}
          onResume={(hold) => void resumeHold(hold)}
          onKeep={(hold) => engine && void answerHold(engine.keepHold(hold.held_uuid))}
          onLetGo={(hold) => engine && void answerHold(engine.releaseHold(hold.held_uuid))}
        />
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
          <PaymentPanel
            bill={bill}
            payment={cart.payment}
            locked={locked}
            onChange={editPayment}
            // Everything the bill asks for, not only the part still unapproved:
            // a manager looking at a second exception should see the first one
            // they agreed to as well, and the fresh authorisation replaces the
            // old one whole.
            onAsk={() => setAsking(bill.asks)}
          />
          <CustomerStrip value={customer} locked={locked} onChange={setCustomer} />
        </aside>
      </div>

      {asking && (
        <ManagerPin
          managers={world.managers}
          asks={asking}
          wrong={wrongPins}
          onWrong={() => setWrongPins((n) => n + 1)}
          onClose={() => {
            setAsking(null);
            scan.focus();
          }}
          onAuthorised={(authorisation) => {
            setCart((current) => ({ ...current, authorisation }));
            setWrongPins(0);
            setAsking(null);
            setNote(`${authorisation.name} approved what this bill needed approving.`);
            scan.focus();
          }}
        />
      )}

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
            data-testid="bill-hold"
            disabled={!cart.lines.length || saving}
            onClick={() => void holdBill()}
          >
            <PauseCircle size={15} />
            Hold bill
          </button>
          <button
            type="button"
            className="btn"
            data-testid="bill-holds-open"
            aria-expanded={showHolds}
            onClick={() => setShowHolds((open) => !open)}
          >
            {showHolds ? "Hide held bills" : `Held bills (${holds.length})`}
          </button>
          {/* The one navigation on this page. Finding an old bill is a different
              job with a different screen (#185, E1/E2), and it is read-only:
              nothing over there can change what was billed. */}
          <Link className="btn" data-testid="bill-find" to="/sell/customers">
            <Search size={15} />
            Find a bill
          </Link>
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

/** Whatever went wrong, as a sentence for the counter. */
function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
            <Fragment key={line.key}>
            <tr data-testid={`bill-line-${line.line_no}`}>
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

/**
 * An amount in rupees, held as integer paise.
 *
 * The typed text is state of its own so a half-written "12." survives the
 * keystroke that made it: parsing on every change and writing the parse back
 * would delete the decimal point as the cashier types it. Only text that is
 * actually an amount reaches the cart (`rupeesToPaise`, ADR-0004 - never
 * `Number(x) * 100`).
 *
 * An emptied box answers `null` rather than nought, and the caller says which it
 * means. For most boxes they are the same thing; for the cash tender they are
 * not - nought is "this bill takes no cash" and empty is "cash takes whatever is
 * left", and a cashier who clears the box to undo a split means the second.
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
  onChange: (paise: number | null) => void;
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
        if (e.target.value.trim() === "") {
          shown.current = 0;
          onChange(null);
          return;
        }
        // Text that is not an amount yet ("12.") is held on screen and kept off
        // the cart until it is one.
        const parsed = rupeesToPaise(e.target.value);
        if (parsed === null) return;
        shown.current = parsed;
        onChange(parsed);
      }}
    />
  );
}

// --- the payment panel -----------------------------------------------------

/**
 * The four trimmed modes, the notes among them, and what is still unpaid (#182).
 *
 * The cash box is deliberately not a controlled copy of the derived figure: the
 * cash tender is `null` until somebody types in it, meaning "whatever is left of
 * the bill", so an all-cash sale needs no keystrokes and a split says out loud
 * that it is one. Clearing the box hands the row back to the balance.
 */
function PaymentPanel({
  bill,
  payment,
  locked,
  onChange,
  onAsk,
}: {
  bill: ReturnType<typeof priceCart>;
  payment: Payment;
  locked: boolean;
  onChange: (patch: Partial<Payment>) => void;
  onAsk: () => void;
}) {
  const { split } = bill;
  return (
    <section className="card section-card bill-panel">
      <p className="eyebrow">To pay</p>
      <p className="bill-due" data-testid="bill-due">
        <Money paise={bill.net_paise} />
      </p>

      <div className="bill-tenders">
        <TenderRow
          testId="bill-cash"
          label="Cash"
          paise={split.cash_paise}
          derived={payment.cash_paise === null}
          locked={locked}
          onChange={(paise) => onChange({ cash_paise: paise })}
        />
        <TenderRow
          testId="bill-card"
          label="Card"
          paise={payment.card_paise}
          locked={locked}
          onChange={(paise) => onChange({ card_paise: paise ?? 0 })}
        />
        <TenderRow
          testId="bill-upi"
          label="UPI"
          paise={payment.upi_paise}
          locked={locked}
          onChange={(paise) => onChange({ upi_paise: paise ?? 0 })}
        />
      </div>

      <Notes
        notes={split.notes}
        locked={locked}
        onChange={(index, patch) =>
          onChange({
            notes: payment.notes.map((note, i) => (i === index ? { ...note, ...patch } : note)),
          })
        }
        onAdd={() => onChange({ notes: [...payment.notes, newNote()] })}
        onRemove={(index) =>
          onChange({ notes: payment.notes.filter((_, i) => i !== index) })
        }
      />

      <div className="bill-row">
        <span>Still to pay</span>
        <span
          data-testid="bill-balance"
          className={split.balance_paise === 0 ? "" : "bill-unpaid"}
        >
          <Money paise={split.balance_paise} />
        </span>
      </div>

      <div className="field">
        <label htmlFor="bill-cash-received">Cash received</label>
        <RupeeInput
          testId="bill-cash-received"
          label="Cash received"
          paise={payment.cash_received_paise}
          locked={locked}
          placeholder="0"
          onChange={(paise) => onChange({ cash_received_paise: paise ?? 0 })}
        />
      </div>
      <div className="bill-row">
        <span>Change</span>
        <span data-testid="bill-change">
          <Money paise={split.change_paise} />
        </span>
      </div>

      <Authorised bill={bill} locked={locked} onAsk={onAsk} />
    </section>
  );
}

/** One mode's amount. `derived` is the cash row following the balance - it shows
 *  the figure it is about to take without pretending a person typed it. */
function TenderRow({
  testId,
  label,
  paise,
  derived,
  locked,
  onChange,
}: {
  testId: string;
  label: string;
  paise: number;
  derived?: boolean;
  locked: boolean;
  onChange: (paise: number | null) => void;
}) {
  return (
    <div className="bill-tender">
      <label htmlFor={testId}>
        {label}
        {derived && (
          <span className="muted-cell" data-testid={`${testId}-derived`}>
            the rest
          </span>
        )}
      </label>
      <RupeeInput
        testId={testId}
        label={label}
        paise={paise}
        locked={locked}
        placeholder="0"
        onChange={onChange}
      />
    </div>
  );
}

/** The credit notes on this bill, and what the counter knows about each. */
function Notes({
  notes,
  locked,
  onChange,
  onAdd,
  onRemove,
}: {
  notes: NoteStanding[];
  locked: boolean;
  onChange: (index: number, patch: { number?: string; amount_paise?: number }) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div className="bill-notes">
      {notes.map((standing, index) => (
        <div className="bill-note" key={standing.note.key}>
          <div className="bill-note-row">
            <input
              className="input bill-cell"
              data-testid={`bill-note-number-${index}`}
              aria-label={`Credit note number, row ${index + 1}`}
              autoComplete="off"
              placeholder="Credit note number"
              disabled={locked}
              value={standing.note.number}
              onChange={(e) => onChange(index, { number: e.target.value })}
            />
            <RupeeInput
              testId={`bill-note-amount-${index}`}
              label={`Credit note amount, row ${index + 1}`}
              paise={standing.note.amount_paise}
              locked={locked}
              placeholder="0"
              onChange={(paise) => onChange(index, { amount_paise: paise ?? 0 })}
            />
            <button
              type="button"
              className="line-del"
              disabled={locked}
              data-testid={`bill-note-remove-${index}`}
              aria-label={`Take credit note row ${index + 1} off the bill`}
              onClick={() => onRemove(index)}
            >
              <X size={14} />
            </button>
          </div>
          {standing.cached && !standing.doubt && (
            <span className="muted-cell" data-testid={`bill-note-left-${index}`}>
              <Money paise={standing.cached.remaining_paise} /> left · good to{" "}
              {standing.cached.expires_on}
            </span>
          )}
          {standing.doubt && (
            <span className="bill-overcap" data-testid={`bill-note-doubt-${index}`}>
              {standing.doubt}
            </span>
          )}
        </div>
      ))}
      <button
        type="button"
        className="btn bill-note-add"
        data-testid="bill-note-add"
        disabled={locked}
        onClick={onAdd}
      >
        <Plus size={14} />
        Credit note
      </button>
    </div>
  );
}

/** The manager's tap: what this bill needs, and who has agreed to it. */
function Authorised({
  bill,
  locked,
  onAsk,
}: {
  bill: ReturnType<typeof priceCart>;
  locked: boolean;
  onAsk: () => void;
}) {
  const { asks, needsAuthorising, authorisation } = bill;
  if (!asks.length && !authorisation) return null;
  return (
    <div className="bill-authorised" data-testid="bill-authorised">
      {authorisation && (
        <span className="muted-cell" data-testid="bill-authorised-by">
          Approved by {authorisation.name} at {formatClock(authorisation.at)}
        </span>
      )}
      {needsAuthorising.length > 0 && (
        <button
          type="button"
          className="btn"
          data-testid="bill-ask-manager"
          disabled={locked}
          onClick={onAsk}
        >
          <KeyRound size={15} />
          Manager approval
        </button>
      )}
    </div>
  );
}

function formatClock(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? iso
    : at.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

/** How many wrong PINs the modal takes before it makes somebody wait, and how
 *  long it makes them wait. */
const WRONG_PINS_BEFORE_A_PAUSE = 3;
const PAUSE_MS = 30_000;

/** What each authorisation kind is called on the shop floor. */
const KIND_WORDS: Record<AuthorisationKind, string> = {
  [OVER_CAP_DISCOUNT]: "a discount past the cashier's limit",
  [UNVERIFIED_NOTE]: "a credit note this counter cannot check",
};

/**
 * The manager's PIN (#182).
 *
 * Checked here, on the device, against the hash the dataset sent - the counter
 * may have had no line for a week. The manager types a PIN and not a name:
 * whose it is is what the PIN establishes, and it is what the bill records.
 *
 * No `alert`, no `confirm`, and Escape closes it. Everything else on this page
 * is a visible button (Anand's Phase-3 ruling) and so is everything here.
 */
function ManagerPin({
  managers,
  asks,
  wrong,
  onWrong,
  onClose,
  onAuthorised,
}: {
  managers: TillManager[];
  asks: Ask[];
  /** Wrong PINs so far at this counter - held by the screen, not by this modal,
   *  because a modal's own count is cleared by closing it, and closing it is one
   *  click. See `Counter`. */
  wrong: number;
  onWrong: () => void;
  onClose: () => void;
  onAuthorised: (authorisation: Authorisation) => void;
}) {
  const [pin, setPin] = useState("");
  const [checking, setChecking] = useState(false);
  const [refused, setRefused] = useState("");
  const box = useRef<HTMLInputElement>(null);
  const waiting = wrong >= WRONG_PINS_BEFORE_A_PAUSE;

  useEffect(() => {
    box.current?.focus();
  }, []);

  async function check() {
    if (checking || waiting || !pin) return;
    setChecking(true);
    setRefused("");
    try {
      const attempt = await whoAuthorised(managers, pin, asks);
      if (!attempt.authorisation) {
        // A wrong PIN and a PIN belonging to a manager of another store are the
        // same answer here, and telling them apart would be telling whoever is
        // standing there which. A *shared* PIN is not - it is a thing an
        // administrator has to fix, and no amount of retrying will help.
        setRefused(
          attempt.matched > 1
            ? "More than one manager here uses that PIN, so the bill could not say which of them approved it. One of them has to change theirs."
            : "That is not a manager's PIN for this store.",
        );
        onWrong();
        setPin("");
        box.current?.focus();
        return;
      }
      onAuthorised(attempt.authorisation);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="modal-backdrop" data-testid="bill-pin-modal" onClick={onClose}>
      <div
        className="modal bill-pin"
        role="dialog"
        aria-label="Manager approval"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <div className="modal-head">
          <h3 className="h3">
            <KeyRound size={17} style={{ verticalAlign: "-3px", marginRight: 6 }} />
            Manager approval
          </h3>
          <button type="button" className="btn" data-testid="bill-pin-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>

        <p className="lead">This bill needs approving:</p>
        <ul className="bill-asks" data-testid="bill-pin-asks">
          {asks.map((ask) => (
            <li key={`${ask.kind}/${ask.ref}`}>
              {ask.label} · {KIND_WORDS[ask.kind]} · <Money paise={ask.paise} />
            </li>
          ))}
        </ul>

        {managers.length === 0 ? (
          <p className="warn-note" data-testid="bill-pin-nobody">
            No manager of this store has a counter PIN yet. One is set from Till &amp; Sync, by
            the manager themselves - and only somebody who may approve selling here can hold one.
          </p>
        ) : (
          <>
            <div className="field">
              <label htmlFor="bill-pin">Manager PIN</label>
              <input
                ref={box}
                id="bill-pin"
                className="input"
                data-testid="bill-pin"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                disabled={checking || waiting}
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  e.preventDefault();
                  void check();
                }}
              />
            </div>
            {refused && (
              <p className="bill-alert" data-testid="bill-pin-refused">
                <AlertTriangle size={15} />
                {refused}
              </p>
            )}
            {waiting && (
              <p className="warn-note" data-testid="bill-pin-waiting">
                Too many wrong PINs. This waits half a minute before it will take another.
              </p>
            )}
            <p className="muted-cell">
              The manager types it themselves. Their name, the time, and what they approved go
              on the bill.
            </p>
            <button
              type="button"
              className="btn btn-cta"
              data-testid="bill-pin-approve"
              disabled={checking || waiting || !pin}
              onClick={() => void check()}
            >
              {checking ? "Checking…" : "Approve"}
            </button>
          </>
        )}
      </div>
    </div>
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
