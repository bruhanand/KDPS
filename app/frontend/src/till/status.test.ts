// The sync light (#180).
//
// A cashier reads this and nothing else about the till all day, so the tests are
// about what each colour is allowed to mean. Red is the only one that asks for an
// action, which is why the ordinary working states have to be provably not red.

import { describe, expect, it } from "vitest";

import { deriveStatus } from "./status";
import type { StatusInput } from "./status";

const HEALTHY: StatusInput = {
  datasetReady: true,
  pending: 0,
  halt: null,
  register: { fy: "26-27", last_accepted_seq: 12, holes: [], hole_count: 0, series_open: true },
  storageLost: false,
  online: true,
};

const HALT = {
  doc_number: "26-27/DEO/SAL/74",
  idempotency_uuid: "c0ffee",
  code: "BILL_NO_TAKEN",
  message: "That bill number is already on another sale.",
  at: "2026-07-30T12:40:00.000Z",
};

describe("the sync light", () => {
  it("is green when the server has everything", () => {
    expect(deriveStatus(HEALTHY)).toMatchObject({ colour: "green", label: "Synced" });
  });

  it("is amber with a count while bills are waiting", () => {
    const status = deriveStatus({ ...HEALTHY, pending: 3 });

    expect(status.colour).toBe("amber");
    expect(status.label).toBe("3 waiting");
    expect(status.reason).toContain("3 bills");
  });

  it("gives the chip a word for every state it can be in", () => {
    // The chip has room for two words and the sentence goes in the tooltip, so a
    // state that produced an empty chip would be a light with no light in it.
    const states: StatusInput[] = [
      HEALTHY,
      { ...HEALTHY, pending: 2 },
      { ...HEALTHY, online: false },
      { ...HEALTHY, halt: HALT },
      { ...HEALTHY, datasetReady: false },
      { ...HEALTHY, storageLost: true },
      { ...HEALTHY, register: { ...HEALTHY.register!, series_open: false } },
    ];
    for (const state of states) {
      const { label, reason } = deriveStatus(state);
      expect(label.trim().length, reason).toBeGreaterThan(0);
      expect(label.split(" ").length, label).toBeLessThanOrEqual(3);
    }
  });

  it("counts one bill in the singular", () => {
    expect(deriveStatus({ ...HEALTHY, pending: 1 }).reason).toContain("1 bill waiting");
  });

  it("is amber, never red, for being offline", () => {
    // Selling with no network is the designed state, not a fault (grill Q5). A
    // red light every time the line drops would teach a store to ignore red.
    expect(deriveStatus({ ...HEALTHY, online: false }).colour).toBe("amber");
  });

  it("is red when a bill was refused, and says which one", () => {
    const status = deriveStatus({ ...HEALTHY, pending: 2, halt: HALT });

    expect(status.colour).toBe("red");
    expect(status.reason).toContain("26-27/DEO/SAL/74");
    expect(status.reason).toContain("already on another sale");
  });

  it("is red before any price list has landed", () => {
    // A till with no local copy cannot price a scan, so this is not a warning.
    expect(deriveStatus({ ...HEALTHY, datasetReady: false }).colour).toBe("red");
  });

  it("is red when the browser threw the local data away", () => {
    const status = deriveStatus({ ...HEALTHY, storageLost: true });

    expect(status.colour).toBe("red");
    expect(status.reason).toContain("bill number");
  });

  it("is red when head office has not opened this year's bill series", () => {
    // Every bill printed today would fail to sync. Better to know at store open
    // than at the first customer.
    const status = deriveStatus({
      ...HEALTHY,
      register: { ...HEALTHY.register!, series_open: false },
    });

    expect(status.colour).toBe("red");
    expect(status.reason).toContain("26-27");
  });

  it("puts the halt ahead of the count", () => {
    // Both are true at once - a halted queue is always a queue with bills in it -
    // and only one of them tells the person what to do.
    expect(deriveStatus({ ...HEALTHY, pending: 5, halt: HALT }).reason).toContain(
      "not accepted",
    );
  });
});
