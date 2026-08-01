import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject, RefObject } from "react";
import { createPortal } from "react-dom";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  Gift,
  PauseCircle,
  Plus,
  Printer,
  RotateCcw,
  Search,
  Undo2,
  X,
} from "lucide-react";

import { PageHeader } from "../../components/PageHeader";
import { useAuth } from "../../auth/AuthContext";
import { Money } from "../../lib/format";
import { SyncLight } from "../../till/SyncLight";
import { useTill } from "../../till/TillProvider";
import {
  addManualPiece,
  emptyCart,
  priceCart,
  scanPiece,
  toDraft,
  whyItCannotClose,
} from "../../till/cart";
import type { Cart, CartLine, PricedLine } from "../../till/cart";
import type { HeldBill } from "../../till/db";
import { clearDraft, persistDraft, readDraft, restoredCart, restoredCustomer } from "../../till/draft";
import { takeParkedExchange } from "../../till/exchange";
import type { Exchange } from "../../till/exchange";
import { heldPayload, holdsToReview, restoreHold } from "../../till/held";
import { tillToday } from "../../till/pricing";
import { storeStateCodeOf } from "../../till/gstin";
import { describePiece, resolveScan, searchPieces } from "../../till/lookup";
import type { Ask } from "../../till/pin";
import { browserPrintAdapter } from "../../till/print";
import { receiptHtml } from "../../till/receipt";
import type { Payment } from "../../till/tender";
import type { TillSnapshot } from "../../till/engine";
import type { QueuedBill, TillCustomer, TillItem } from "../../till/types";
import { emptyUndo, popUndo, pushUndo } from "../../till/undo";
import type { UndoStack } from "../../till/undo";
import { useScanBox } from "../../till/useScanBox";
import { useTillWorld } from "../../till/useTillWorld";
// The house modal (`.modal-backdrop` / `.modal` / `.modal-head`), which every
// screen with a dialog on it borrows from the same place.
import "../Booking.css";
import { newUuid } from "../../till/uuid";
import { usePositionedPopover } from "../../shell/usePositionedPopover";
import { Lines } from "./billing/BillGrid";
import { CustomerStrip } from "./billing/CustomerStrip";
import { HeldBills } from "./billing/HeldBills";
import { PaymentPanel } from "./billing/PaymentPanel";
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

/** Stand-in width for the scan box's floating prompts, before either has ever
 *  mounted (`usePositionedPopover`'s first clamp). Kept in step with
 *  `.bill-float`'s width in Billing.css. */
const SCAN_FLOAT_WIDTH = 380;

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
  // --- cart safety: autosave and undo (#244) --------------------------------
  /** One snapshot per cart action, oldest first - see `till/undo.ts`. */
  const [undoStack, setUndoStack] = useState<UndoStack>(emptyUndo);
  /** The draft read on mount has landed - whether or not it had anything to
   *  restore. Autosave waits for this: writing the still-pristine cart the
   *  instant this screen mounts would beat the read to the punch and clobber
   *  the very draft it is about to look for. */
  const [restored, setRestored] = useState(false);
  /** Flipped once this screen has deliberately started a fresh bill - New
   *  bill, a commit, or a hold. A restore that lands after that is a screen
   *  the cashier has already moved on from, and must not resurrect it
   *  (binding rule 6, "don't restore over a fresh bill"). */
  const skipRestore = useRef(false);
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
   * Reopening Billing after a crash, a closed tab or a power cut (#244).
   *
   * Read exactly once, guarded the way `useTillWorld` guards its own reload: a
   * read that loses the StrictMode/remount race is dropped rather than
   * applied. `restoredCart`/`restoredCustomer` are the merge - whichever the
   * screen already has by the time the read lands (a piece scanned before it
   * came back, or the exchange hand-off above, in no guaranteed order against
   * this one) wins over the saved draft, so neither can clobber the other.
   * `skipRestore` is the third guard: a New bill, a commit or a hold started
   * before this read landed means the cashier has already moved past what it
   * would restore.
   */
  useEffect(() => {
    if (!engine) return;
    let alive = true;
    void readDraft(engine.db).then((draft) => {
      if (!alive) return;
      if (draft && !skipRestore.current) {
        setCart((current) => restoredCart(current, draft));
        setCustomer((current) => restoredCustomer(current, draft));
      }
      setRestored(true);
    });
    return () => {
      alive = false;
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

  /**
   * Write-through: every cart or customer-field change lands here (#244).
   *
   * Held off until the mount read above has landed - see `restored` - so this
   * never races that read with a write of the still-empty cart this screen
   * starts on. `persistDraft` never throws (flag, never block): a failed
   * write is a console line, and the bill carries on regardless.
   */
  useEffect(() => {
    if (!engine || !restored) return;
    void persistDraft(engine.db, cart, customer, paper);
  }, [engine, restored, cart, customer, paper]);

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

  // Quiet, and only once there is a bill on screen worth saving - an empty
  // counter has nothing autosave is protecting yet.
  const draftSaved = restored && (cart.lines.length > 0 || Boolean(cart.exchange));

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

  /** Both alert channels start over at each of the three "next bill starts"
   *  moments - a piece scanned, an unknown taken onto the bill, or New bill
   *  pressed - so neither an old confirmation nor a stale print failure can
   *  outlive the bill it belonged to (see `pickBillAlert`'s note,
   *  Billing.tsx:1013). One named site, so a fourth such moment does not
   *  have to remember to copy the pair by hand (round-3 finding).
   *  `resumeHold` needs its own message rather than a blank `note`, so it
   *  keeps clearing `printProblem` on its own instead of calling this. */
  const startingANewBill = useCallback(() => {
    setNote("");
    setPrintProblem("");
  }, []);

  /** Remember the cart as it stood before a mutator lands - one step for the
   *  Undo button (#244). */
  const pushCartUndo = useCallback((snapshot: Cart) => {
    setUndoStack((stack) => pushUndo(stack, snapshot));
  }, []);

  const takePiece = useCallback(
    (piece: TillItem, alternatives: TillItem[], stock: number) => {
      pushCartUndo(cart);
      // `scanPiece`, not a bare append: scanning a tag already on the bill
      // bumps that line's quantity instead of laying a duplicate beside it
      // (#244).
      setCart((current) => scanPiece(current, piece, { stock, alternatives }, defaultSalesman));
      startingANewBill();
      // Picking a real piece answers the "was that tag mistyped?" ask - it was.
      clearScan();
    },
    [cart, clearScan, defaultSalesman, pushCartUndo, startingANewBill],
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
      pushCartUndo(cart);
      setCart((current) => ({
        ...current,
        lines: [...current.lines, { ...addManualPiece(code), salesman: defaultSalesman }],
      }));
      startingANewBill();
      clearScan();
      scan.focus();
    },
    [cart, clearScan, defaultSalesman, pushCartUndo, scan, startingANewBill],
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
    pushCartUndo(cart);
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
    pushCartUndo(cart);
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
    pushCartUndo(cart);
    setCart((current) => ({ ...current, lines: current.lines.filter((l) => l.key !== key) }));
    scan.focus();
  }

  /** Step the bill back one action (#244). Nothing here touches stock or
   *  money - the whole safety of it is that this bill is not real until Save
   *  & Print. */
  function undo() {
    const popped = popUndo(undoStack);
    if (!popped) return;
    setUndoStack(popped.stack);
    setCart(popped.cart);
    scan.focus();
  }

  function editPayment(patch: Partial<Payment>) {
    setCart((current) => ({ ...current, payment: { ...current.payment, ...patch } }));
  }

  function newBill() {
    skipRestore.current = true;
    setCart(emptyCart());
    setCustomer(NO_CUSTOMER);
    setUndoStack(emptyUndo());
    startingANewBill();
    clearScan();
    if (engine) void clearDraft(engine.db);
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
      skipRestore.current = true;
      setCart(emptyCart());
      setCustomer(NO_CUSTOMER);
      setUndoStack(emptyUndo());
      clearScan();
      await clearDraft(engine.db);
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
    // A held bill can carry lines of its own, so it can put the cart into a
    // state `holdBill` will happily hold again without a scan ever running
    // `takePiece`/`takeUnknown` - this is the other "next bill starts" moment
    // a stale print problem must not survive (round-2 finding: Billing.tsx:1013).
    setPrintProblem("");
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
      skipRestore.current = true;
      setCart(emptyCart());
      setCustomer(NO_CUSTOMER);
      setUndoStack(emptyUndo());
      clearScan();
      await clearDraft(engine.db);
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

  // Which one banner the frame's alert strip shows (#243) - see `pickBillAlert`.
  // `blocked` never wins a line here: a blocked counter takes over the whole
  // work area below instead, which is the stronger treatment Rule 5 asks for.
  // `paper` is not a flag here either, for the same reason: see the block
  // below, which renders off `paper !== null` directly.
  const alert = pickBillAlert({
    blocked: Boolean(till?.blocked),
    loading: !world.loaded,
    noPriceList: world.loaded && !world.items.length,
    printProblem: Boolean(printProblem),
    note: Boolean(note),
    gift: bill.entitlements.length > 0,
    holdsDue: toReview.length > 0,
  });

  // Shared by the three lifecycle buttons below - one call site instead of
  // three identical ones, mirroring `alert`'s own `blocked: Boolean(till?.blocked)`
  // just above.
  const counterBlocked = Boolean(till?.blocked);

  /** Dismissing the scan box's floating prompts (G-4) is the same act as
   *  answering "not that" by hand: put down the question and give the cursor
   *  back, whether the counter did it by clicking outside, pressing Escape, or
   *  the button inside `NotInSystem`. */
  const closeScanFloat = useCallback(() => {
    clearScan();
    scan.focus();
  }, [clearScan, scan]);

  // "Did you mean" and "bill it off the tag" both hang off the scan box as one
  // floating panel (G-4: "nothing pushes the layout"), portaled out of the
  // work area so neither can push the rail or the footer. `usePositionedPopover`
  // already does measure/re-measure/clamp/outside-click - the scan box just
  // needed the hook to accept an `<input>` and to hang the panel below rather
  // than beside it, which is what the `<HTMLInputElement>` and `"below"` here
  // are for.
  const scanFloat = usePositionedPopover<HTMLInputElement>(
    unknown || suggestions.length > 0 ? "scan" : null,
    closeScanFloat,
    SCAN_FLOAT_WIDTH,
    "below",
  );

  return (
    <div className="page-pad bill-page">
      {/* Top strip: bill identity and the "which bill am I on" actions (D10
          §4's placement, regrouped per #243). Wrapped with the one-line alert
          below rather than left as PageHeader's own sibling, because a
          stripped-section persona has `PageHeader` draw a tab row above its
          toolbar (`HostedPageContext`) - two elements for one conceptual
          band. Wrapping them keeps `.bill-page`'s row template honest at
          `auto` however many elements PageHeader itself renders. */}
      <div className="bill-top">
        <PageHeader
          lead={
            <>
              {`Next bill ${till?.nextNumber ?? ""}`}
              {draftSaved && (
                <span className="bill-draft-saved muted-cell" data-testid="bill-draft-saved">
                  {" "}
                  · Draft · saved
                </span>
              )}
            </>
          }
          actions={
            <div className="bill-head">
              <SyncLight />
              <ScanBox
                boxRef={mergeRefs(scan.ref, scanFloat.triggerRef)}
                value={typed}
                disabled={locked || counterBlocked}
                onChange={setTyped}
                onSubmit={applyScan}
              />
              <div className="bill-lifecycle">
                {/* Finding an old bill is a different job with a different
                    screen (#185, E1/E2), and it is read-only: nothing over
                    there can change what was billed. */}
                <Link className="btn" data-testid="bill-find" to="/sell/customers">
                  <Search size={15} />
                  Find a bill
                </Link>
                <button
                  type="button"
                  className="btn"
                  data-testid="bill-holds-open"
                  aria-expanded={showHolds}
                  // `HeldBills` lives inside `.bill-lines` (#243), which the
                  // blocked-counter takeover replaces entirely - toggling this
                  // while blocked would flip the label with nothing to show
                  // for it, so it is disabled along with the actions below.
                  disabled={counterBlocked}
                  onClick={() => setShowHolds((open) => !open)}
                >
                  {showHolds ? "Hide held bills" : `Held bills (${holds.length})`}
                </button>
                {/* Undo lives in the lifecycle row rather than on the grid it
                    steps back (#244): under #243's fixed frame `.bill-lines`
                    is the band that scrolls, so a header inside it would
                    scroll away exactly as the bill got long enough to want
                    undoing. */}
                <button
                  type="button"
                  className="btn"
                  data-testid="bill-undo"
                  disabled={counterBlocked || !undoStack.length || locked}
                  onClick={undo}
                >
                  <RotateCcw size={15} />
                  Undo
                </button>
                <button
                  type="button"
                  className="btn"
                  data-testid="bill-hold"
                  disabled={counterBlocked || !cart.lines.length || saving}
                  onClick={() => void holdBill()}
                >
                  <PauseCircle size={15} />
                  Hold bill
                </button>
                <button
                  type="button"
                  className="btn"
                  data-testid="bill-new"
                  disabled={counterBlocked || saving}
                  onClick={newBill}
                >
                  New bill
                </button>
              </div>
            </div>
          }
        />

        {paper !== null && (
          <div className="bill-paper" data-testid="bill-paper">
            <div>
              <strong>Entering printed bill {paper}</strong> - this one was rung up on the
              machine this counter replaced and never reached head office. Enter it exactly as
              the printed copy reads. It keeps its own number, and nothing prints.
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

        {alert === "loading" && <p className="warn-note">Opening the counter…</p>}
        {alert === "no-price-list" && (
          <p className="warn-note" data-testid="bill-no-price-list">
            This counter has no local price list yet. Sync from Till &amp; Sync before billing.
          </p>
        )}
        {alert === "print-problem" && (
          <p className="bill-alert" data-testid="bill-print-problem">
            <AlertTriangle size={15} />
            {printProblem}
          </p>
        )}
        {alert === "note" && (
          <p className="ok-note" data-testid="bill-note">
            {note}
          </p>
        )}
        {/* A gift is earned, not deducted: it takes nothing off any line, so
            without this row the counter has no way of knowing the customer is
            owed a trolley - and D5 Q11 is clear that it "only counts if it was
            actually handed to the customer". Scanning it puts it on the bill
            at its token price like any other piece. The out-of-stock fallback
            the engine also supports has no control here yet; that needs a
            decline gesture and a re-price, and it is its own ticket. */}
        {alert === "gift" &&
          bill.entitlements.map((gift) => (
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
        {/* Day close, until store open/close (I3) defines one properly: a
            bill parked before today is put to the store, and stays parked
            until somebody answers. Nothing expires on a timer (grill Q13). */}
        {alert === "holds-due" && (
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
      </div>

      {/* Work area: only `.bill-lines` scrolls (G-2/G-4). The counter itself
          cannot bill (#189) - its data was cleared, or this is the second
          window on one till - and Rule 5 says collapsing alerts to one line
          must not soften that: rather than a thin banner above a bill nobody
          can act on, a blocked counter takes over this whole band. */}
      <div className="bill-work">
        {till?.blocked ? (
          <p
            className="bill-alert bill-alert-stop bill-blocked-area"
            data-testid="bill-counter-blocked"
          >
            <AlertTriangle size={18} />
            {till.blocked}{" "}
            <Link className="btn" to="/sell/till">
              Open Till &amp; Sync
            </Link>
          </p>
        ) : (
          <>
            <section className="bill-lines">
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
              {bill.exchange && (
                <ExchangeBack
                  exchange={bill.exchange}
                  refundPaise={bill.refund_paise}
                  locked={locked}
                  onRemove={removeLeg}
                />
              )}
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
          </>
        )}
      </div>

      {/* "Did you mean" and "bill it off the tag" (G-4): portaled to
          `document.body` and placed by `usePositionedPopover`, so neither can
          push the rail or the footer a pixel - they float over the grid
          instead. The portal also escapes the blocked-counter takeover (AC5:
          the block replaces the work area entirely), so it must gate on
          `counterBlocked` itself - otherwise it can append lines to a cart
          nobody can see. */}
      {!counterBlocked &&
        scanFloat.at &&
        createPortal(
          <div
            ref={scanFloat.popoverRef}
            className="bill-float"
            style={{
              top: scanFloat.at.top,
              left: scanFloat.at.left,
              maxHeight: scanFloat.at.maxHeight,
            }}
          >
            {unknown && (
              <NotInSystem
                barcode={unknown}
                hasSuggestions={suggestions.length > 0}
                locked={locked}
                onBill={() => takeUnknown(unknown)}
                onDismiss={closeScanFloat}
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
          </div>,
          document.body,
        )}

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

      {/* Footer: pinned, visible from the first scan to the last. Reprint,
          then Save & Print - the one visually primary button on the screen. */}
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
            className="btn btn-cta btn-lg"
            data-testid="bill-save"
            disabled={Boolean(blocked) || saving}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : paper === null ? "Save & Print" : `Save bill ${paper}`}
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

/** Which one of the counter's seven possible banners to show (#243).
 *
 *  Every one of these used to be its own paragraph, stacking - a bill with a
 *  gift earned, a note from an exchange, and holds waiting review could carry
 *  three banners at once, each pushing the totals further down the page. The
 *  frame gives them one line, so something has to decide which one wins when
 *  several are true at once.
 *
 *  `paper` is not one of the seven: keying in a printed bill needs its date
 *  field and its "Not this one" exit live the whole time it is active, not
 *  only when it happens to win this line (round-2 finding - a failed save in
 *  paper mode set `note`, which hid both controls with only "start a new
 *  bill" left to escape by). It renders from its own always-on band
 *  (`paper !== null`, see `Counter`) instead, the same way `blocked` renders
 *  from the work area instead of this line. */
export type BillAlertKind =
  | "blocked"
  | "loading"
  | "no-price-list"
  | "print-problem"
  | "note"
  | "gift"
  | "holds-due";

export interface BillAlertFlags {
  blocked: boolean;
  loading: boolean;
  noPriceList: boolean;
  printProblem: boolean;
  note: boolean;
  gift: boolean;
  holdsDue: boolean;
}

/**
 * Precedence, not a boolean OR: the order these banners used to stack in, top
 * to bottom, becomes the order they take turns in now that only one may show.
 *
 * `blocked` is first and wins outright over everything, including a print
 * problem that is also true - Rule 5 says collapsing alerts to one line must
 * not soften the second-window hard block, so it never shares this line with
 * a lesser alert. It does not render *from* this line at all, in fact: the
 * blocked counter takes over the whole work area instead (see `Counter`),
 * which is the stronger treatment the rule asks for.
 *
 * `print-problem` is second, ahead of `note`: `save()` sets both in the same
 * order every time printing fails after a successful commit (`setNote` then
 * `await print(receipt)`, which is the only place `printProblem` is ever set
 * true), so letting `note` win here would bury the one thing on this screen
 * that tells the cashier the receipt did not print and Reprint is what to
 * press (round-2 finding). That only stays a safe trade because `printProblem`
 * cannot outlive the bill it belongs to: `takePiece`/`takeUnknown` clear it on
 * the next scan and `resumeHold` clears it before swapping the cart for a held
 * bill's, so `holdBill`'s and `resumeHold`'s own failure notes are never a
 * *stale* print problem's casualty (round-2 finding, second pass). A live,
 * still-relevant print problem can still outrank `answerHold`'s note - that is
 * a genuine conflict between two unrelated live alerts sharing one line, not
 * staleness, and is left as a residual (see `deviations.md`).
 *
 * `note` is third, ahead of `loading`/`no-price-list`, because it is the one
 * channel every failure on this screen reports through (`save`, `holdBill`,
 * `resumeHold`, `answerHold` all funnel their catch block into it). Before the
 * collapse these banners stacked, so an error note was never hidden behind a
 * mode banner - a mode is a lesser alert than an error, not the other way
 * round, and a cashier who does not see why Save failed either re-submits a
 * bill that already went through or walks away thinking one never did.
 */
export function pickBillAlert(flags: BillAlertFlags): BillAlertKind | null {
  if (flags.blocked) return "blocked";
  if (flags.printProblem) return "print-problem";
  if (flags.note) return "note";
  if (flags.loading) return "loading";
  if (flags.noPriceList) return "no-price-list";
  if (flags.gift) return "gift";
  if (flags.holdsDue) return "holds-due";
  return null;
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

/** One DOM node into two refs that each need it for a different reason: the
 *  focus patrol's own ref (`useScanBox`) and the scan-box float's trigger ref
 *  (`usePositionedPopover`), which cannot share a single `useRef` because they
 *  come from two different hooks that each own theirs. */
function mergeRefs<T>(...refs: RefObject<T>[]): (node: T | null) => void {
  return (node) => {
    refs.forEach((ref) => {
      (ref as MutableRefObject<T | null>).current = node;
    });
  };
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
  boxRef: (node: HTMLInputElement | null) => void;
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
        <span>
          Nothing on this counter is barcode <span className="mono">{barcode}</span>.
          {hasSuggestions
            ? " Check the list below first - a tag is misread far more often than a piece is new."
            : " Check the tag, or search by design number."}
        </span>
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
                <td>{leg.reason || <span className="muted-cell">not said</span>}</td>
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
