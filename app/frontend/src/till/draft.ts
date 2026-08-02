// The bill that survives a crash (#244, grill ruling 30 Jul 2026).
//
// The in-progress bill is not money and it is not a fact - it is what the
// screen currently shows, and it autosaves continuously so that a dead line, a
// closed tab or a power cut hands it straight back rather than making the
// cashier re-scan everything a customer already stood through once. One row,
// at a fixed key, written through on every cart or customer-field change and
// read back once on mount.
//
// Flag, never block (Rule 8): a failed write is a safety net that missed, not
// a reason to stop the bill. It logs and the counter carries on - the till's
// blocked banner is for something else entirely, and this file never raises
// one.

import { newKey } from "./cart";
import type { Cart } from "./cart";
import type { TillDb } from "./db";
import { newLegKey } from "./exchange";
import type { TillCustomer } from "./types";

/** The one row this table ever holds - an outbound key, so nothing on the
 *  payload itself has to name it. */
const DRAFT_KEY = "current";

/** Everything needed to restore mid-scan - the cart (lines, exchange and
 *  payment together), the customer strip, and which printed bill this counter
 *  was re-entering, if any.
 *
 *  `paper` rides along because the row would not be the whole screen without
 *  it, but restoring it is not this file's job: paper mode is deliberately
 *  never held in React state (`Billing.tsx`'s `outstandingPaperSeq`), always
 *  re-derived from the address bar, and a restore that pushed it back into the
 *  URL would fight that design rather than lean on it. */
export interface DraftPayload {
  cart: Cart;
  customer: TillCustomer;
  paper: number | null;
  savedAt: string;
}

/** Write the draft through. Never throws: a draft write standing between a
 *  cashier and the next scan would turn a safety net into a gate. */
export async function persistDraft(
  db: TillDb,
  cart: Cart,
  customer: TillCustomer,
  paper: number | null,
): Promise<void> {
  try {
    await db.draft.put({ cart, customer, paper, savedAt: new Date().toISOString() }, DRAFT_KEY);
  } catch (error) {
    console.error("persistDraft failed - the bill continues without a safety net", error);
  }
}

/** The draft as it last stood, or null when there is nothing parked. Never
 *  throws, the same as `persistDraft`: a blocked or corrupt read must not
 *  stop the bill from starting - it just starts without a restore. */
export async function readDraft(db: TillDb): Promise<DraftPayload | null> {
  try {
    return (await db.draft.get(DRAFT_KEY)) ?? null;
  } catch (error) {
    console.error("readDraft failed - starting the bill without a restore", error);
    return null;
  }
}

/** Cleared on commit success, New bill, and Hold - the three moments the
 *  screen in front of the cashier stops being the bill this row remembers.
 *
 *  Never throws, the same as `persistDraft`: the bill this call follows has
 *  already committed, held, or been deliberately cleared on screen, and a
 *  storage error here must not turn into an error note on a sale that already
 *  went through. */
export async function clearDraft(db: TillDb): Promise<void> {
  try {
    await db.draft.delete(DRAFT_KEY);
  } catch (error) {
    console.error("clearDraft failed - the bill continues without a safety net", error);
  }
}

// --- landing the read back on screen (the mount race, #244 binding rule 6) --
//
// The read is issued at mount and IndexedDB answers whenever it answers, so by
// the time it lands the screen may already have moved on - a piece scanned
// before the read came back, or the exchange hand-off `Billing.tsx` takes on
// mount landing first or second, in either order. Whichever is on screen by
// then is realer than a saved draft, so these never overwrite it; they only
// fill in what is still empty. Pure, so the race's outcome is a value to
// assert on rather than a timing a test has to win.

/** The cart to show once the read lands - `onScreen` if anything is already on
 *  it, else the draft. */
export function restoredCart(onScreen: Cart, draft: DraftPayload): Cart {
  return onScreen.lines.length || onScreen.exchange ? onScreen : draft.cart;
}

/** Same rule for the customer strip: a name, mobile or GSTIN already typed
 *  wins over what was parked. */
export function restoredCustomer(onScreen: TillCustomer, draft: DraftPayload): TillCustomer {
  return onScreen.name || onScreen.mobile || onScreen.gstin ? onScreen : draft.customer;
}

// --- crash-restore line identity (ruled, 2 Aug 2026) ------------------------
//
// `newKey`/`newLegKey` restart their counters at l1/x1 on every page load, so a
// draft's saved keys can collide with the very next scan's - and a shared key
// means an edit or a removal hits both lines, and worse, a PIN authorisation
// keyed by `line.key` (`pin.ts`'s `covers`) silently covers a line nobody
// approved. So every line and leg a draft restores gets a brand-new key, minted
// from the same two generators a fresh scan uses rather than a third one of
// this file's own - the collision this issue exists to close.

/** Every restored line and leg, rekeyed, with every reference to an old key
 *  inside the same draft remapped in the same pass - a PIN authorisation's
 *  `ref` most of all, since that is what binds one manager's approval to
 *  exactly one line (binding rule 0a).
 *
 *  Called once in the mount effect, before `setCart` - never inside a state
 *  updater, which React 18 StrictMode double-invokes in dev, and minting keys
 *  there would run the generators twice and split the mapping between the
 *  lines and the refs that point at them. */
export function rekeyDraft(draft: DraftPayload): DraftPayload {
  const map = new Map<string, string>();
  const lines = draft.cart.lines.map((line) => {
    const key = newKey();
    map.set(line.key, key);
    return { ...line, key };
  });
  const exchange = draft.cart.exchange
    ? {
        ...draft.cart.exchange,
        lines: draft.cart.exchange.lines.map((leg) => {
          const key = newLegKey();
          map.set(leg.key, key);
          return { ...leg, key };
        }),
      }
    : null;
  const authorisation = draft.cart.authorisation
    ? {
        ...draft.cart.authorisation,
        // `Ask.ref` is either a line key or a credit-note number (`pin.ts`) -
        // a lookup with a fallback, never an unconditional rewrite, so a note
        // number is left exactly as it stood.
        asks: draft.cart.authorisation.asks.map((ask) => ({
          ...ask,
          ref: map.get(ask.ref) ?? ask.ref,
        })),
      }
    : null;
  return { ...draft, cart: { ...draft.cart, lines, exchange, authorisation } };
}
