// Which printed bill this screen was sent here to key back in (#189).
//
// The billing screen is driven in a browser rather than in a renderer here, so
// what this file holds is the one decision on it that is a rule rather than a
// layout: given an address and a counter, is this a paper re-entry, and which
// bill. Getting it wrong is not a cosmetic failure - a screen that decides "no"
// hands the cashier an ordinary counter, and Save & Print then takes a *new*
// number and prints a second receipt for a bill that is already in a customer's
// hand, leaving the hole exactly where it was.

import { describe, expect, it } from "vitest";

import type { TillSnapshot } from "../../till/engine";

import { outstandingPaperSeq } from "./Billing";

/** Only the four fields this rule reads; the snapshot has two dozen. */
function counter(over: Partial<TillSnapshot> = {}): TillSnapshot {
  return {
    register: {
      fy: "26-27",
      last_accepted_seq: 73,
      holes: [61, 62],
      hole_count: 2,
      series_open: true,
    },
    handover: null,
    paperEntered: [],
    ...over,
  } as TillSnapshot;
}

const asked = (paper: string) => new URLSearchParams(paper ? { paper } : {});

describe("which printed bill this screen is entering", () => {
  it("takes a number head office is missing", () => {
    expect(outstandingPaperSeq(asked("61"), counter())).toBe(61);
  });

  it("is nothing at all when the address does not ask", () => {
    expect(outstandingPaperSeq(asked(""), counter())).toBe(null);
  });

  it("ignores anything that is not a bill number", () => {
    for (const nonsense of ["0", "-4", "2.5", "abc", " "]) {
      expect(outstandingPaperSeq(asked(nonsense), counter()), nonsense).toBe(null);
    }
  });

  it("refuses a number head office already holds", () => {
    // A hand-typed address. Billing under it would print a second bill for a
    // number the server has, and the server's refusal is terminal - it halts
    // the store's whole sync queue behind it.
    expect(outstandingPaperSeq(asked("40"), counter())).toBe(null);
  });

  it("refuses one this counter has already keyed in", () => {
    // The reload case: the address still names the bill after it has been
    // entered and synced.
    expect(outstandingPaperSeq(asked("61"), counter({ paperEntered: [61] }))).toBe(null);
  });

  it("still honours a number the handover named after the register has moved on", () => {
    // The frozen list somebody was handed is the job. A sync that closed some of
    // it must not take the rest of the drawer off the list.
    const till = counter({
      register: {
        fy: "26-27",
        last_accepted_seq: 73,
        holes: [],
        hole_count: 0,
        series_open: true,
      },
      handover: { resume_from_seq: 74, unsynced_hint: [61, 62], hole_count: 2, at: "" },
    });

    expect(outstandingPaperSeq(asked("62"), till)).toBe(62);
  });

  it("says no while the counter still knows nothing - which is why it is asked again", () => {
    // The trap this rule was got wrong on once. Each Sell route mounts its own
    // TillProvider, so arriving here from the handover list means a brand-new
    // engine whose first snapshot has no register and no handover in it. Read
    // once at mount, the answer is always this one; the screen has to re-ask as
    // the counter comes up, and the caller does.
    expect(outstandingPaperSeq(asked("61"), null)).toBe(null);
    expect(
      outstandingPaperSeq(asked("61"), counter({ register: null, handover: null })),
    ).toBe(null);
  });
});
