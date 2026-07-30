import { describe, expect, it } from "vitest";

import { PROTECTED_ROUTES } from "../routes";
import { matchRoutes } from "react-router-dom";
import {
  KNOWN_QUEUE_KEYS,
  queueRows,
  shortDay,
  sparkBars,
  targetProgressPct,
  type DashboardPayload,
} from "./storeDashboardModel";

/** The six keys `storefront/dashboard.py` sends today, in its order. Kept as a
 *  literal on purpose: if the server adds a key this side has never heard of,
 *  the row silently disappears, and this is the test that says so. */
const SERVER_KEYS = [
  "approvals_pending",
  "transfers_to_receive",
  "grn_pt_pending",
  "quarantine_to_confirm",
  "rtb_windows_closing",
  "open_count_session",
];

function payload(over: Partial<DashboardPayload> = {}): DashboardPayload {
  return {
    store: "DEO",
    sales_live: false,
    today: {
      net_sales_paise: 0,
      bills: 0,
      avg_bill_paise: 0,
      pieces: 0,
      collections: { cash: 0, card: 0, upi: 0, credit_note: 0 },
      vs_yesterday_pct: null,
    },
    action_queue: SERVER_KEYS.map((key) => ({ key, count: 0 })),
    live: { offers: [], in_transit: [] },
    last7: ["2026-07-24", "2026-07-25", "2026-07-26"].map((date) => ({
      date,
      net_sales_paise: 0,
    })),
    ...over,
  };
}

describe("the action queue", () => {
  it("knows every key the server can send", () => {
    for (const key of SERVER_KEYS) expect(KNOWN_QUEUE_KEYS).toContain(key);
  });

  it("draws no key it has no screen for", () => {
    // The three `sell` keys land with #177-#186; until then a row would be a
    // number nobody could click through and clear.
    expect(KNOWN_QUEUE_KEYS).not.toContain("held_bills");
    const rows = queueRows(payload({ action_queue: [{ key: "held_bills", count: 4 }] }));
    expect(rows).toEqual([]);
  });

  it("keeps the server's order", () => {
    expect(queueRows(payload()).map((r) => r.key)).toEqual(SERVER_KEYS);
  });

  it("gives every row a sentence and a count", () => {
    for (const row of queueRows(payload())) {
      expect(row.label).not.toBe("");
      expect(typeof row.count).toBe("number");
    }
  });

  it("sends every row somewhere the app can actually go", () => {
    // The acceptance criterion is "linking into the right section/tab" - a row
    // pointing at a URL with no route would be a dead end nobody notices until
    // a store person taps it.
    for (const row of queueRows(payload())) {
      const [path] = row.to.split("?");
      expect(matchRoutes(PROTECTED_ROUTES, path), `${row.key} → ${row.to}`).toBeTruthy();
    }
  });
});

describe("where a queue row goes", () => {
  it("sends the receiving store to Transfers, not to the sender's in-transit screen", () => {
    // Found in browser QA: `/transfer/in-transit` is scoped to the *source*
    // store, so a store reading "1 carton to receive" clicked through and was
    // told nothing was on the road.
    const row = queueRows(payload()).find((r) => r.key === "transfers_to_receive");
    expect(row?.to).toBe("/transfer");
  });
});

describe("the sparkline", () => {
  it("scales a week of nothing to nothing, not to a flat full row", () => {
    expect(sparkBars(payload().last7).map((b) => b.heightPct)).toEqual([0, 0, 0]);
  });

  it("scales every day against the best one", () => {
    const bars = sparkBars([
      { date: "2026-07-24", net_sales_paise: 50_000 },
      { date: "2026-07-25", net_sales_paise: 100_000 },
      { date: "2026-07-26", net_sales_paise: 0 },
    ]);
    expect(bars.map((b) => b.heightPct)).toEqual([50, 100, 0]);
  });

  it("keeps its dates even with no values, so the strip has an axis", () => {
    expect(sparkBars(payload().last7).map((b) => b.date)).toEqual([
      "2026-07-24",
      "2026-07-25",
      "2026-07-26",
    ]);
  });
});

describe("month-to-date against the target", () => {
  it("reads no-target-set as nothing to draw, not as nought per cent", () => {
    expect(targetProgressPct(0, 0)).toBeNull();
    expect(targetProgressPct(1_00_000, 0)).toBeNull();
  });

  it("is a percentage of the target", () => {
    expect(targetProgressPct(50_000_000, 200_000_000)).toBe(25);
  });

  it("caps the bar at full without capping the number behind it", () => {
    expect(targetProgressPct(300_000_000, 200_000_000)).toBe(100);
  });
});

describe("the sparkline's tick", () => {
  it("does not shift a bare date across the day boundary", () => {
    // `new Date("2026-07-30")` is parsed as UTC and reads as the 29th in some
    // zones; the parts are read by hand for exactly that reason.
    expect(shortDay("2026-07-30")).toContain("30");
  });
});
