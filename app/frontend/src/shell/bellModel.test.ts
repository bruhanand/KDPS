// The three rules behind the bell (#226), away from the popup that draws them.
//
// They are worth pinning on their own because each one has already been got
// wrong somewhere in this codebase: a count computed twice drifts, a date
// computed in UTC moves at half past six in the evening, and a day grouping
// that reads the ISO string instead of the local calendar puts an evening's
// alerts under tomorrow.
import { describe, expect, it } from "vitest";

import {
  RANGE_KEYS,
  RANGE_LABELS,
  dayHeading,
  groupResolvedByDay,
  sinceFor,
  unreadAlerts,
} from "./bellModel";
import type { AlertT } from "../components/alert";

function alert(id: number, created_at: string, resolved_at: string | null = null): AlertT {
  return {
    id,
    kind: "in_transit_aging",
    kind_label: "Transfer stuck in transit",
    title: `alert ${id}`,
    object_id: null,
    store: null,
    store_code: "",
    store_name: "",
    brand: "",
    due_date: null,
    days_left: null,
    threshold_days: null,
    status: resolved_at ? "resolved" : "open",
    created_at,
    resolved_at,
  };
}

describe("unreadAlerts", () => {
  const feed = [
    alert(1, "2026-07-31T10:00:00Z"),
    alert(2, "2026-07-31T09:00:00Z"),
    alert(3, "2026-07-30T09:00:00Z"),
  ];

  it("counts everything for a person who has never opened the tab", () => {
    // No stamp is not "nothing unread" — it is a new person meeting a feed
    // that has been filling up without them.
    expect(unreadAlerts(feed, null)).toBe(3);
  });

  it("counts only what was raised after the stamp", () => {
    expect(unreadAlerts(feed, "2026-07-31T09:30:00Z")).toBe(1);
  });

  it("treats an alert raised on the stamp itself as read", () => {
    // The stamp is taken when the tab opens, so an alert bearing exactly that
    // moment was on screen. Strictly-after keeps the badge from re-lighting on
    // the alert the person just looked at.
    expect(unreadAlerts(feed, "2026-07-31T10:00:00Z")).toBe(0);
  });

  it("is zero on an empty feed however old the stamp", () => {
    expect(unreadAlerts([], null)).toBe(0);
  });
});

describe("sinceFor", () => {
  // Half past eleven at night in Deoghar — the hour that catches a UTC date.
  const evening = new Date(2026, 6, 31, 23, 30);

  it("maps every range to a day on the counter's own calendar", () => {
    expect(sinceFor("today", evening)).toBe("2026-07-31");
    expect(sinceFor("7d", evening)).toBe("2026-07-24");
    expect(sinceFor("30d", evening)).toBe("2026-07-01");
    expect(sinceFor("1y", evening)).toBe("2025-07-31");
  });

  it("does not slip a day late in the evening", () => {
    // `new Date().toISOString()` would already say 1 August here.
    expect(sinceFor("today", evening)).toBe(sinceFor("today", new Date(2026, 6, 31, 9, 0)));
  });

  it("steps back over a month and a year boundary", () => {
    expect(sinceFor("7d", new Date(2026, 0, 3))).toBe("2025-12-27");
  });

  it("offers exactly the four ranges the popup draws, defaulting to 7 days", () => {
    expect(RANGE_KEYS).toEqual(["today", "7d", "30d", "1y"]);
    expect(RANGE_KEYS[1]).toBe("7d");
    expect(Object.keys(RANGE_LABELS).sort()).toEqual([...RANGE_KEYS].sort());
  });
});

describe("groupResolvedByDay", () => {
  it("groups by the local calendar day, newest day first", () => {
    const rows = [
      alert(1, "2026-07-31T04:00:00Z", "2026-07-31T12:00:00Z"),
      alert(2, "2026-07-31T04:00:00Z", "2026-07-31T03:00:00Z"),
      alert(3, "2026-07-29T04:00:00Z", "2026-07-29T05:00:00Z"),
    ];
    const groups = groupResolvedByDay(rows);
    expect(groups.map((g) => g.day)).toEqual(["2026-07-31", "2026-07-29"]);
    expect(groups[0].alerts.map((a) => a.id)).toEqual([1, 2]);
  });

  it("keeps an evening resolution on the day it happened locally", () => {
    // 19:00 IST on 31 July is 13:30 UTC — the same day either way. 00:30 IST on
    // 1 August is 19:00 UTC on 31 July, and reading the ISO string would file it
    // under July.
    const groups = groupResolvedByDay([alert(1, "2026-07-31T04:00:00Z", "2026-07-31T19:00:00Z")]);
    expect(groups[0].day).toBe(
      new Date("2026-07-31T19:00:00Z").toLocaleDateString("en-CA"),
    );
  });

  it("drops a row with no resolution moment rather than inventing a day for it", () => {
    expect(groupResolvedByDay([alert(1, "2026-07-31T04:00:00Z", null)])).toEqual([]);
  });

  it("says nothing about an empty history", () => {
    expect(groupResolvedByDay([])).toEqual([]);
  });
});

describe("dayHeading", () => {
  const now = new Date(2026, 6, 31, 23, 30);

  it("names the two days a person thinks of by name", () => {
    expect(dayHeading("2026-07-31", now)).toBe("Today");
    expect(dayHeading("2026-07-30", now)).toBe("Yesterday");
  });

  it("dates everything older", () => {
    expect(dayHeading("2026-07-24", now)).toBe("24 Jul 2026");
  });

  it("crosses a month boundary without arithmetic of its own", () => {
    expect(dayHeading("2026-06-30", new Date(2026, 6, 1, 10, 0))).toBe("Yesterday");
  });
});
