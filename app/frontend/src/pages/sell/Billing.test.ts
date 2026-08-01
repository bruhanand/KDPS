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

import { outstandingPaperSeq, pickBillAlert } from "./Billing";
import type { BillAlertFlags } from "./Billing";

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

// The frame's alert strip (#243): every banner this screen can raise used to
// stack, each pushing the totals further down the page. The frame gives them
// one line, so something has to decide which one wins when several are true
// at once - this is that rule, tested the way `outstandingPaperSeq` is: the
// layout itself is browser QA, but which banner is chosen is not a layout
// question at all.

/** Every flag false - the caller sets only the ones under test. */
function noAlerts(over: Partial<BillAlertFlags> = {}): BillAlertFlags {
  return {
    blocked: false,
    paper: false,
    loading: false,
    noPriceList: false,
    printProblem: false,
    note: false,
    gift: false,
    holdsDue: false,
    ...over,
  };
}

describe("which one banner the counter shows", () => {
  it("shows nothing when nothing is true", () => {
    expect(pickBillAlert(noAlerts())).toBe(null);
  });

  it("shows the single true reason", () => {
    expect(pickBillAlert(noAlerts({ holdsDue: true }))).toBe("holds-due");
    expect(pickBillAlert(noAlerts({ gift: true }))).toBe("gift");
    expect(pickBillAlert(noAlerts({ note: true }))).toBe("note");
  });

  it("a blocked counter outranks everything else, print problem included", () => {
    // Rule 5: collapsing to one line must not soften the second-window hard
    // block - it wins outright rather than taking turns with a lesser alert.
    expect(
      pickBillAlert(
        noAlerts({ blocked: true, paper: true, printProblem: true, holdsDue: true }),
      ),
    ).toBe("blocked");
  });

  it("keys in from paper outranks a stale price list or a note", () => {
    expect(pickBillAlert(noAlerts({ paper: true, noPriceList: true, note: true }))).toBe(
      "paper",
    );
  });

  it("follows the counter's own stacking order end to end", () => {
    // blocked > paper > loading > no price list > print problem > note > gift
    // > holds due - the order these banners used to stack in, top to bottom.
    const order: (keyof BillAlertFlags)[] = [
      "blocked",
      "paper",
      "loading",
      "noPriceList",
      "printProblem",
      "note",
      "gift",
      "holdsDue",
    ];
    for (let i = 0; i < order.length; i++) {
      const flags = noAlerts();
      for (let j = i; j < order.length; j++) flags[order[j]] = true;
      expect(pickBillAlert(flags), order[i]).toBe(kebabOf(order[i]));
    }
  });
});

function kebabOf(key: keyof BillAlertFlags): string {
  return key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
}
