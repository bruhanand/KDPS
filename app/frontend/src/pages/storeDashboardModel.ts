// The store Dashboard's payload, and the pure part of drawing it (#174, D10 §2).
//
// Split out of the component so it can be tested: this suite renders nothing, so
// anything worth asserting has to be a function that takes the payload and
// returns what the screen will say. What lives here is the two things most
// likely to go quietly wrong - which screen each action-queue row opens, and how
// a sparkline of all-noughts is scaled.

/** `GET /api/store/dashboard`. `manager` is *absent*, not null, for a cashier. */
export interface DashboardPayload {
  store: string;
  /** False until the Sale document and the till land (#177/#181). Tells "no
   *  bills yet today" apart from "this store cannot bill at all". */
  sales_live: boolean;
  today: {
    net_sales_paise: number;
    bills: number;
    avg_bill_paise: number;
    pieces: number;
    collections: { cash: number; card: number; upi: number; credit_note: number };
    vs_yesterday_pct: number | null;
  };
  action_queue: { key: string; count: number }[];
  live: {
    offers: { id: number; brand: string; one_liner: string }[];
    in_transit: { id: number; doc_number: string; pieces: number; expected: string }[];
  };
  last7: { date: string; net_sales_paise: number }[];
  manager?: {
    day_close: { date: string; state: string };
    mtd_net_paise: number;
    target_paise: number;
  };
}

export interface QueueRow {
  key: string;
  count: number;
  /** What the number is, as a person would say it. */
  label: string;
  /** Where clearing it happens. */
  to: string;
}

/** Key → the sentence and the screen. The server decides the order and which
 *  keys exist at all; this side only knows what each one means.
 *
 *  Two of the contract's nine keys read `sell` tables that do not exist yet
 *  (`uncosted_sale_lines`, `continuity_flags`), so they are not here either -
 *  they arrive with the screens that clear them, exactly as `held_bills` did. */
const QUEUE_MEANING: Record<string, { label: string; to: string }> = {
  approvals_pending: { label: "Waiting for your approval", to: "/approvals" },
  // Not `/transfer/in-transit`: that screen is the *sender's*, scoped to the
  // source store, so a receiving store clicked through from "1 carton to
  // receive" and was told nothing was on the road (found in browser QA). The
  // Transfers list carries both directions, and the Receive button lives on the
  // transfer itself - which the live-in-store card links to piece by piece.
  transfers_to_receive: { label: "Cartons to receive", to: "/transfer" },
  grn_pt_pending: { label: "Arrivals awaiting their PT", to: "/receive" },
  // The store's three folded sections are addressed through the Inventory fold
  // (#170), which is the arrangement a store person actually has.
  quarantine_to_confirm: { label: "Damage reports to confirm", to: "/inventory?tab=damage" },
  rtb_windows_closing: { label: "Return windows closing", to: "/alerts" },
  open_count_session: { label: "Stock counts open", to: "/inventory?tab=count" },
  // The hold list lives inside Billing rather than at an address of its own -
  // picking a parked bill up *is* billing - so the row opens the counter with
  // the list already showing (#185).
  held_bills: { label: "Bills on hold", to: "/sell?holds=1" },
};

/** The queue as rows to draw. A key this build has no screen for is dropped
 *  rather than rendered as a dead number - a count you cannot click is a count
 *  nobody can clear. */
export function queueRows(payload: DashboardPayload): QueueRow[] {
  return payload.action_queue.flatMap((row) => {
    const meaning = QUEUE_MEANING[row.key];
    return meaning ? [{ key: row.key, count: row.count, ...meaning }] : [];
  });
}

/** Every key this side can draw - the frontend half of the contract, asserted
 *  in `storeDashboardModel.test.ts` against the six the server sends today. */
export const KNOWN_QUEUE_KEYS = Object.keys(QUEUE_MEANING);

export interface SparkBar {
  date: string;
  paise: number;
  /** Height as a percentage of the tallest day: 0 when nothing sold at all,
   *  and never negative - a day whose returns outran its sales is a bar with
   *  no height, not a bar drawn downwards through the axis. */
  heightPct: number;
}

/** Seven days scaled against their own best day.
 *
 *  A week of noughts scales to nought rather than to a flat full-height row:
 *  dividing by the maximum would make every bar 100% of nothing, which reads as
 *  a week of identical trade. The bars keep their dates either way, so the strip
 *  has an axis before it has any values. */
export function sparkBars(last7: DashboardPayload["last7"]): SparkBar[] {
  const peak = Math.max(0, ...last7.map((d) => d.net_sales_paise));
  return last7.map((d) => ({
    date: d.date,
    paise: d.net_sales_paise,
    heightPct: peak > 0 ? Math.max(0, Math.round((d.net_sales_paise / peak) * 100)) : 0,
  }));
}

/** How far through the month's number this store is, clamped to 0-100 for the
 *  bar's width - the figure beside the bar is never clamped, so a store past its
 *  target still reads what it actually did.
 *
 *  A month with no target set returns `null`: no target is not 0% of a target,
 *  and a bar drawn at zero against nothing would read as failure. */
export function targetProgressPct(mtdPaise: number, targetPaise: number): number | null {
  if (targetPaise <= 0) return null;
  return Math.min(100, Math.max(0, Math.round((mtdPaise / targetPaise) * 100)));
}

/** "30 Jul" - the sparkline's tick. Built from the ISO parts rather than
 *  `new Date(iso)`, which parses a bare date as UTC and can shift it a day. */
export function shortDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
