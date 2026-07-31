import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  FileText,
  Gift,
  KeyRound,
  PauseCircle,
  Plus,
  Printer,
  Search,
  Undo2,
  X,
} from "lucide-react";

import { PageHeader } from "../../components/PageHeader";
import { useAuth } from "../../auth/AuthContext";
import { Money, paiseToRupees, rupeesToPaise } from "../../lib/format";
import { SyncLight } from "../../till/SyncLight";
import { useTill } from "../../till/TillProvider";
import {
  addManualPiece,
  addPiece,
  emptyCart,
  priceCart,
  qtyFrom,
  toDraft,
  whyItCannotClose,
} from "../../till/cart";
import type { Cart, CartLine, PricedLine } from "../../till/cart";
import type { HeldBill } from "../../till/db";
import { takeParkedExchange } from "../../till/exchange";
import type { Exchange } from "../../till/exchange";
import { heldPayload, holdsToReview, restoreHold } from "../../till/held";
import { tillToday } from "../../till/pricing";
import { describeGstin, storeStateCodeOf, TAX_KIND_WORDS, taxKindFor } from "../../till/gstin";
import { describePiece, resolveScan, searchPieces } from "../../till/lookup";
import type { Ask } from "../../till/pin";
import { browserPrintAdapter } from "../../till/print";
import { receiptHtml } from "../../till/receipt";
import { newNote } from "../../till/tender";
import type { NoteStanding, Payment } from "../../till/tender";
import type { TillSnapshot } from "../../till/engine";
import type { QueuedBill, TillCustomer, TillItem } from "../../till/types";
import { useScanBox } from "../../till/useScanBox";
import { useTillWorld } from "../../till/useTillWorld";
// The house modal (`.modal-backdrop` / `.modal` / `.modal-head`), which every
// screen with a dialog on it borrows from the same place.
import "../Booking.css";
import { newUuid } from "../../till/uuid";
import { HeldBills } from "./HeldBills";
import { ManagerPin, useWrongPins } from "./ManagerPin";
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
// **A piece coming back rides on the bill** (#184, grill Q7). The Return &
// Exchange screen picks which lines of an old bill are being given back and parks
// them; this screen picks them up and nets them against whatever is being bought
// instead. The refund is what the customer *paid*, never today's price, and a
// bill that ends up owing them money takes no payment at all - the difference
// leaves as a credit note, and cash never comes out of the drawer.
//
// **A scan that finds nothing never sends the customer away** (#186, grill Q5).
// The tag is in their hand, so the counter offers to bill it off the tag: a line
// with a typed description and a typed price, no cohort behind it, and no cost of
// record. The server takes the bill, posts the money, and parks the cost event
// until the PT prices the piece - which is the only way Rule 5 (nothing at
// nought) and Rule 8 (nothing blocked) can both hold at once.

/** A fresh bill's customer strip. Spelled once because it is cleared from four
 *  places - New Bill, Hold, Save & Print, and the reset after a hold is parked -
 *  and a literal in one of them that forgot a field would leave the last
 *  customer's GSTIN on the next customer's tax invoice. */
const NO_CUSTOMER: TillCustomer = { name: "", mobile: "", gstin: "" };

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
  const [params, setParams] = useSearchParams();
  const [cart, setCart] = useState<Cart>(emptyCart);
  const [customer, setCustomer] = useState<TillCustomer>(NO_CUSTOMER);
  const [saving, setSaving] = useState(false);
  const [holding, setHolding] = useState(false);
  const [note, setNote] = useState("");
  const [printProblem, setPrintProblem] = useState("");
  const [lastBill, setLastBill] = useState<{ bill: QueuedBill; receipt: string } | null>(null);
  const [typed, setTyped] = useState("");
  /** A barcode this counter could not place, waiting on the cashier to say
   *  whether it is a mistyped tag or a piece that arrived before its paperwork
   *  (#186). Empty means nothing is being asked. */
  const [unknown, setUnknown] = useState("");
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
  /** Wrong PINs at this counter, and the pause they earn (`useWrongPins`). Only
   *  a speed bump: the hash is on this device by design (grill Q1), so what it
   *  buys is somebody guessing having to stand at the counter visibly doing
   *  nothing. */
  const pins = useWrongPins();
  // The hold list opens on demand, and opens itself when the Dashboard's "bills
  // on hold" row sent somebody here to clear them (`/sell?holds=1`). Read once,
  // into state: after that the panel is the cashier's to open and close, and a
  // value that kept re-reading the address bar would spring open again on every
  // render behind their back.
  const [showHolds, setShowHolds] = useState(() => params.has("holds"));

  const world = useTillWorld(engine?.db ?? null, `${till?.syncedAt ?? ""}#${commits}`);
  const scan = useScanBox(world.loaded);

  /**
   * Pick up an exchange the Return & Exchange screen parked (#184).
   *
   * Taken exactly once, from the counter's own database rather than from router
   * state: each Sell route mounts its own `TillProvider`, so there is no shared
   * React between the two screens - and a customer standing at the counter
   * mid-exchange should survive a reload with their pieces still on the bill.
   *
   * It lands on whatever is already on screen rather than replacing it, because
   * that is the flow: the cashier picks the pieces coming back, then scans what
   * the customer is taking instead - or the other way round.
   */
  useEffect(() => {
    if (!engine) return;
    let taken = true;
    void takeParkedExchange(engine.db).then((parked) => {
      if (taken && parked) {
        setCart((current) => ({ ...current, exchange: parked }));
        setNote(`Exchange against ${parked.original.doc_number} is on this bill.`);
      }
    });
    return () => {
      taken = false;
    };
  }, [engine]);

  /**
   * Re-entering a printed bill from the machine this counter replaced (#189).
   *
   * The number comes off the paper, from the list on Till & Sync, and so does the
   * date: a bill printed last Tuesday belongs in last Tuesday's books, and
   * stamping it with today's clock would put it in the wrong day's takings and
   * price its tax off the wrong slab.
   *
   * **Derived from the address and the counter's live state, never held in
   * state.** Each Sell route mounts its own `TillProvider`, so arriving here
   * from the handover list means a brand-new engine whose first snapshot knows
   * nothing yet - no register, no handover, no counter. A mode resolved once at
   * mount would therefore resolve to "not a paper bill" every single time, and
   * the screen would quietly hand the cashier an ordinary counter: Save & Print
   * would take a *new* number, print a second receipt, and leave the hole
   * exactly where it was. So the address bar is the request and the snapshot is
   * the answer, and leaving paper mode means taking the request away.
   *
   * Only a number the counter still regards as outstanding is honoured. The link
   * that gets somebody here is on the handover list, so a number from anywhere
   * else is a hand-typed address, and letting one through would offer to bill a
   * second time under a number head office already holds - which halts the whole
   * store's queue when it lands (`BILL_NO_TAKEN` is terminal).
   */
  const paper = useMemo(() => outstandingPaperSeq(params, till), [params, till]);
  const [paperAt, setPaperAt] = useState(() => localNow());

  const leavePaperMode = useCallback(() => {
    if (!params.has("paper")) return;
    const next = new URLSearchParams(params);
    next.delete("paper");
    setParams(next, { replace: true });
  }, [params, setParams]);

  const today = useMemo(() => tillToday(), []);
  // Which state this shop is registered in - the other half of every B2B tax
  // split. Null until the counter's identity has synced, and null is *not* a
  // state code: see `storeStateCodeOf` and `toDraft`.
  const storeState = storeStateCodeOf(world.store);
  const bill = useMemo(
    () =>
      priceCart(cart, world, today, {
        capPercent: world.policy.manual_discount_cap_percent,
      }),
    [cart, world, today],
  );
  // The counter's own refusals come first (#189): "this till does not know which
  // number it is on" is not something a cashier can fix by editing the cart, and
  // showing them a line-level complaint instead would send them looking at the
  // wrong thing.
  const blocked = till?.blocked || whyItCannotClose(bill);

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

  /** Empty the scan box and put down whatever it was asking about.
   *
   *  The two always move together: `unknown` is a question *about* what is in the
   *  box, so a box that has been cleared and a question still on the screen is a
   *  cashier being asked about a barcode they can no longer see. */
  const clearScan = useCallback(() => {
    setTyped("");
    setUnknown("");
  }, []);

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
      // Picking a real piece answers the "was that tag mistyped?" ask - it was.
      clearScan();
    },
    [clearScan, defaultSalesman],
  );

  /**
   * A garment the counter has never heard of, onto the bill anyway (#186).
   *
   * Grill Q5's whole point: the customer is holding it, so the scan finding
   * nothing is a thing the *shop* has to sort out, not a reason to send them
   * away. The line carries what the cashier types and what the tag says, and the
   * server parks its cost event until the paperwork lands.
   */
  const takeUnknown = useCallback(
    (code: string) => {
      setCart((current) => ({
        ...current,
        lines: [...current.lines, { ...addManualPiece(code), salesman: defaultSalesman }],
      }));
      setNote("");
      clearScan();
      scan.focus();
    },
    [clearScan, defaultSalesman, scan],
  );

  const applyScan = useCallback(
    (code: string) => {
      const found = resolveScan(code, world);
      if (!found.barcode) return;
      if (!found.chosen) {
        // A2 / grill Q5: the customer is holding the garment, so this is a
        // sentence and an offer rather than a refusal. The suggestion list is
        // still worth a look first - the commonest reason a tag does not
        // resolve is that it was mistyped, not that the piece is new.
        setUnknown(found.barcode);
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

  /** Take a piece back off the bill - the customer changed their mind about
   *  giving it back, or the wrong line was picked. */
  function removeLeg(key: string) {
    setCart((current) => {
      const legs = (current.exchange?.lines ?? []).filter((leg) => leg.key !== key);
      return {
        ...current,
        // An exchange with no legs left is not an exchange: keeping the empty
        // shell would leave the bill pointing at an original it gives nothing
        // back against, and refusing to close (`whyExchangeCannotClose`).
        exchange: legs.length && current.exchange ? { ...current.exchange, lines: legs } : null,
      };
    });
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
    setCustomer(NO_CUSTOMER);
    setNote("");
    setPrintProblem("");
    clearScan();
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
      setCustomer(NO_CUSTOMER);
      clearScan();
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
   *
   * A paper re-entry takes the same path and stops before the printer (#189).
   * The receipt for that bill is already in a customer's hand, and printing a
   * second copy of a bill that is being keyed in from the first is how one sale
   * ends up looking like two on a shop floor.
   */
  async function save() {
    if (!engine || blocked || saving) return;
    setSaving(true);
    setPrintProblem("");
    try {
      const billedAt = paper === null ? new Date().toISOString() : new Date(paperAt).toISOString();
      const draft = toDraft(bill, { billedAt, customer, storeStateCode: storeState });
      const queued =
        paper === null
          ? await engine.commit(draft)
          : await engine.reenterFromPaper(draft, paper);
      setCommits((n) => n + 1);
      const receipt = receiptHtml(queued, world.store ?? FALLBACK_STORE, {
        storeName,
        cashReceivedPaise: cart.payment.cash_received_paise,
        describe: describeFrom(bill.lines),
      });
      setLastBill({ bill: queued, receipt });
      setCart(emptyCart());
      setCustomer(NO_CUSTOMER);
      clearScan();
      if (paper === null) {
        setNote(`Bill ${queued.doc_number} saved.`);
        await print(receipt);
      } else {
        leavePaperMode();
        setNote(
          `Bill ${queued.doc_number} entered from its printed copy. ` +
            "It is on the list to sync, and the customer keeps the receipt they have.",
        );
      }
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

      {/* The counter itself cannot bill (#189): its data was cleared, or this is
          the second window on one till. Above everything else on the page,
          because nothing below it can be acted on until this is dealt with. */}
      {till?.blocked && (
        <p className="bill-alert bill-alert-stop" data-testid="bill-counter-blocked">
          <AlertTriangle size={15} />
          {till.blocked}{" "}
          <Link className="btn" to="/sell/till">
            Open Till &amp; Sync
          </Link>
        </p>
      )}

      {paper !== null && (
        <div className="bill-paper" data-testid="bill-paper">
          <div>
            <strong>Entering printed bill {paper}</strong> - this one was rung up on the machine
            this counter replaced and never reached head office. Enter it exactly as the printed
            copy reads. It keeps its own number, and nothing prints.
          </div>
          <div className="field">
            <label htmlFor="bill-paper-at">Date and time on the printed copy</label>
            <input
              id="bill-paper-at"
              className="input"
              data-testid="bill-paper-at"
              type="datetime-local"
              disabled={locked}
              value={paperAt}
              onChange={(e) => setPaperAt(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="btn"
            data-testid="bill-paper-cancel"
            disabled={locked}
            onClick={leavePaperMode}
          >
            <X size={15} /> Not this one
          </button>
        </div>
      )}

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

      {unknown && (
        <NotInSystem
          barcode={unknown}
          hasSuggestions={suggestions.length > 0}
          locked={locked}
          onBill={() => takeUnknown(unknown)}
          onDismiss={() => {
            clearScan();
            scan.focus();
          }}
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

      {bill.exchange && (
        <ExchangeBack
          exchange={bill.exchange}
          refundPaise={bill.refund_paise}
          locked={locked}
          onRemove={removeLeg}
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
          <CustomerStrip
            value={customer}
            storeStateCode={storeState}
            locked={locked}
            onChange={setCustomer}
          />
        </aside>
      </div>

      {asking && (
        <ManagerPin
          managers={world.managers}
          asks={asking}
          wrong={pins.wrong}
          onWrong={pins.wasWrong}
          onClose={() => {
            setAsking(null);
            scan.focus();
          }}
          onAuthorised={(authorisation) => {
            setCart((current) => ({ ...current, authorisation }));
            pins.clear();
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
            {saving ? "Saving…" : paper === null ? "Save & Print" : `Save bill ${paper}`}
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

/**
 * The bill number this screen was sent here to re-enter from paper (#189), or
 * null - which is anything the counter does not still regard as outstanding.
 *
 * Two questions, and the second is the one that matters. A positive whole number
 * only means the address bar is well formed; what makes it a bill to key in is
 * that head office is missing it and this till has not already keyed it in. Both
 * are read from the till's own state:
 *
 *   · `register.holes` is the live list, so a store working through more than the
 *     200 a response carries keeps going as earlier ones close;
 *   · `handover.unsynced_hint` is the frozen list somebody was handed, which
 *     still names a bill after a sync has closed it in the register's eyes but
 *     before the drawer has been worked through;
 *   · `paperEntered` is what this counter has actually keyed in, and it wins over
 *     both.
 *
 * Anything else is somebody's hand-typed address, and honouring one would offer
 * to bill again under a number the server already holds - which halts the whole
 * store's queue when it lands.
 */
export function outstandingPaperSeq(
  params: URLSearchParams,
  till: TillSnapshot | null,
): number | null {
  const asked = Number(params.get("paper"));
  if (!Number.isInteger(asked) || asked < 1 || !till) return null;
  if (till.paperEntered.includes(asked)) return null;
  const missing = [...(till.register?.holes ?? []), ...(till.handover?.unsynced_hint ?? [])];
  return missing.includes(asked) ? asked : null;
}

/** Now, in the shape `<input type="datetime-local">` wants - which is local
 *  time with no zone on it, not an ISO instant. The till's own clock, because a
 *  bill's date is the store's day (see `tillToday`). */
function localNow(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

/** Where the store's own registration has not landed yet. The receipt still
 *  prints - a customer's copy with no GSTIN on it is better than no copy. */
const FALLBACK_STORE = { code: "", gstin: "", state_code: "" };

/** How a line reads on paper, from the cart the counter just billed.
 *
 *  A sold-before-inward line has no brand and no item name, so what the cashier
 *  typed is the only description that exists - and it is the one the customer
 *  needs, because the alternative is a receipt line that is just a barcode. */
function describeFrom(lines: PricedLine[]) {
  const words = new Map(
    lines.map((line) => [line.line_no, describePiece(line) || line.manual_desc.trim()]),
  );
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

/**
 * The scan found nothing: the two things that can mean, as two buttons (#186).
 *
 * Almost always the tag was mistyped, so the suggestion list underneath is the
 * first answer and this says so. The other answer is that the garment really is
 * new - it walked into the shop ahead of its paperwork - and grill Q5 is clear
 * that the customer never waits for that. So the second button bills it off the
 * tag: description and price typed here, cost posted when the PT lands.
 *
 * Not a modal. A dialogue over the line grid at the busiest moment of a sale is
 * the thing D10 §4 keeps off this screen, and there is nothing here a cashier has
 * to answer before they can carry on scanning.
 */
function NotInSystem({
  barcode,
  hasSuggestions,
  locked,
  onBill,
  onDismiss,
}: {
  barcode: string;
  hasSuggestions: boolean;
  locked: boolean;
  onBill: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="card section-card bill-unknown" data-testid="bill-unknown">
      <p className="bill-unknown-note">
        <AlertTriangle size={15} />
        Nothing on this counter is barcode <span className="mono">{barcode}</span>.
        {hasSuggestions
          ? " Check the list below first - a tag is misread far more often than a piece is new."
          : " Check the tag, or search by design number."}
      </p>
      <div className="bill-unknown-actions">
        <button
          type="button"
          className="btn"
          data-testid="bill-unknown-bill"
          disabled={locked}
          onClick={onBill}
        >
          <Plus size={15} />
          Bill it off the tag
        </button>
        <button
          type="button"
          className="btn"
          data-testid="bill-unknown-dismiss"
          onClick={onDismiss}
        >
          Not that
        </button>
      </div>
      <p className="muted-cell">
        The bill prints as usual. What the piece cost us is posted when its paperwork arrives,
        and the store's Dashboard counts it until then.
      </p>
    </div>
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

/**
 * The pieces coming back on this bill (#184, D2).
 *
 * Its own block above the line grid rather than rows inside it, and that is the
 * decision rather than the easy way out. A returned piece is priced at what the
 * customer paid on *another* bill - it has no MRP here, no discount, no offer and
 * no salesman - so seven of the grid's twelve columns would be blank on it, and
 * the two rows a cashier has to keep straight (going out, coming back) would be
 * interleaved in one list with a minus sign as the only thing telling them apart.
 *
 * The reason and the condition are the counter's to set, and the condition is the
 * one that matters: a damaged piece goes to quarantine and never back on the
 * shelf, which is a decision a person makes with the garment in their hand.
 */
function ExchangeBack({
  exchange,
  refundPaise,
  locked,
  onRemove,
}: {
  exchange: Exchange;
  refundPaise: number;
  locked: boolean;
  onRemove: (key: string) => void;
}) {
  return (
    <section className="card section-card bill-exchange" data-testid="bill-exchange">
      <p className="eyebrow">
        <Undo2 size={14} /> Coming back · against {exchange.original.doc_number}
      </p>
      <div className="table-wrap">
        <table className="data" data-testid="bill-exchange-lines">
          <thead>
            <tr>
              <th>Piece</th>
              <th className="num">Qty</th>
              <th>Reason</th>
              <th>Condition</th>
              <th className="num">Back</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {exchange.lines.map((leg) => (
              <tr key={leg.key} data-testid={`bill-exchange-${leg.original_line}`}>
                <td>
                  {leg.description}
                  <br />
                  <span className="mono muted-cell">{leg.barcode}</span>
                </td>
                <td className="num">{leg.qty}</td>
                <td>{leg.reason || "—"}</td>
                <td>
                  {leg.condition === "damaged" ? (
                    <span className="bill-overcap">damaged · quarantine</span>
                  ) : (
                    "good · back on the shelf"
                  )}
                </td>
                <td className="num">
                  <Money paise={leg.refund_paise} />
                </td>
                <td>
                  <button
                    type="button"
                    className="line-del"
                    disabled={locked}
                    data-testid={`bill-exchange-remove-${leg.original_line}`}
                    aria-label={`Take the returned piece on line ${leg.original_line} off this bill`}
                    onClick={() => onRemove(leg.key)}
                  >
                    <X size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted-cell" data-testid="bill-exchange-total">
        Given back: <Money paise={refundPaise} /> - what the customer paid for these pieces, not
        today&rsquo;s price.
      </p>
    </section>
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
  // An exchange whose returns outweigh its sales pays the *customer*, and it pays
  // them in a credit note rather than out of the drawer (#184, grill Q7). The
  // panel closes rather than showing a negative to collect: there is no amount to
  // take, and a cash box a cashier could still type into is a drawer somebody
  // could still open.
  if (bill.credit_note_paise > 0) {
    return (
      <section className="card section-card bill-panel" data-testid="bill-owes-customer">
        <p className="eyebrow">Owed to the customer</p>
        <p className="bill-due" data-testid="bill-credit-note">
          <Money paise={bill.credit_note_paise} />
        </p>
        <p className="muted-cell">
          The pieces coming back are worth more than the ones going out. Save &amp; Print issues a
          credit note for the difference, spendable at this shop - no cash comes out of the
          drawer. Its number prints on the bill.
        </p>
      </section>
    );
  }
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

/**
 * Who the bill is for - and, when they give a GSTIN, what kind of bill it is.
 *
 * A GSTIN turns a retail sale into a full tax invoice (#187, grill Q8): the
 * split printed on the customer's copy is derived here, offline, from the
 * buyer's state against the shop's, because it prints minutes before head office
 * hears about the bill and cannot wait for anybody.
 *
 * The check on what they typed is *soft*, and visibly so. The counter says the
 * registration looks wrong and the bill closes anyway - the customer is standing
 * there holding the garment, and a mistyped character is a tax invoice head
 * office corrects, not a sale to decline. Saying it here is still worth doing,
 * because here is the one moment the customer can read their card out again.
 */
function CustomerStrip({
  value,
  storeStateCode,
  locked,
  onChange,
}: {
  value: TillCustomer;
  /** Null when the counter has not learned which state it is in - see below. */
  storeStateCode: string | null;
  locked: boolean;
  onChange: (v: TillCustomer) => void;
}) {
  // A counter that does not know its own state cannot say which tax a business
  // bill carries, and there is no safe guess: one wrong answer prints IGST on a
  // local buyer's copy while the books post CGST + SGST, and the other does it
  // the other way round. So the field closes and says why, rather than taking a
  // registration it would then charge the wrong tax on.
  const canBillB2b = storeStateCode !== null;
  const kind = canBillB2b ? taxKindFor(value.gstin, storeStateCode) : "none";
  const malformed = canBillB2b ? describeGstin(value.gstin) : "";
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
      <div className="field">
        <label htmlFor="bill-gstin">GSTIN (for a business bill)</label>
        <input
          id="bill-gstin"
          className="input mono"
          data-testid="bill-gstin"
          autoComplete="off"
          maxLength={15}
          spellCheck={false}
          disabled={locked || !canBillB2b}
          value={value.gstin}
          // Upper-cased as it is typed, so what the cashier reads back is what
          // prints and what the server stores - a GSTIN differing from itself by
          // case would flag every second business bill.
          onChange={(e) => onChange({ ...value, gstin: e.target.value.toUpperCase() })}
        />
      </div>
      {!canBillB2b && (
        <p className="bill-alert" data-testid="bill-gstin-unavailable">
          <AlertTriangle size={15} /> This counter has not synced its own registration yet, so it
          cannot say whether a buyer is in this state. Sync from Till &amp; Sync to bill a
          business; a retail bill is unaffected.
        </p>
      )}
      {kind !== "none" && (
        <p className="ok-note" data-testid="bill-tax-kind">
          <FileText size={15} /> Tax invoice · {TAX_KIND_WORDS[kind]}
          {kind === "igst" ? " (buyer is out of state)" : ""}
        </p>
      )}
      {malformed && (
        <p className="bill-alert" data-testid="bill-gstin-warning">
          <AlertTriangle size={15} /> {malformed} The bill will still close - check the card.
        </p>
      )}
      <p className="muted-cell">The bill works without any of these.</p>
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
      {bill.refund_paise > 0 && (
        <Figure
          label="Given back"
          value={<Money paise={bill.refund_paise} />}
          testId="bill-given-back"
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
