// Which printed bill this screen was sent here to key back in (#189).
//
// The billing screen is driven in a browser rather than in a renderer here, so
// what this file holds is the one decision on it that is a rule rather than a
// layout: given an address and a counter, is this a paper re-entry, and which
// bill. Getting it wrong is not a cosmetic failure - a screen that decides "no"
// hands the cashier an ordinary counter, and Save & Print then takes a *new*
// number and prints a second receipt for a bill that is already in a customer's
// hand, leaving the hole exactly where it was.

// @ts-expect-error Vitest runs in Node, while the production frontend deliberately excludes Node types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { TillSnapshot } from "../../till/engine";

import { outstandingPaperSeq, paperConsistent, pickBillAlert } from "./Billing";
import type { BillAlertFlags } from "./Billing";

const billingSource = readFileSync(new URL("./Billing.tsx", import.meta.url), "utf8");
const billingCss = readFileSync(new URL("./Billing.css", import.meta.url), "utf8");
const billingRules = billingCss.replace(/\/\*[\s\S]*?\*\//g, "");

describe("the counter frame", () => {
  it("owns the full content width instead of inheriting the generic page cap", () => {
    expect(billingSource).toContain('<div className="bill-page" data-mode={mode}>');
    expect(billingSource).not.toContain('className="page-pad bill-page"');
    expect(billingRules).toMatch(/\.bill-page\s*{[^}]*max-width:\s*none;/s);
  });

  it("reserves the rail width and pins the rail flush to the content edge", () => {
    expect(billingRules).toMatch(/\.bill-page\s*{[^}]*padding:\s*0 368px 16px 16px;/s);
    expect(billingRules).toMatch(/\.bill-pay\s*{[^}]*right:\s*0;[^}]*bottom:\s*0;/s);
  });
});

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
      pickBillAlert(noAlerts({ blocked: true, printProblem: true, holdsDue: true })),
    ).toBe("blocked");
  });

  it("a print problem outranks the save confirmation note", () => {
    // `save()` sets both in this order every time printing fails after a
    // successful commit - `note` is always that save's own "Bill saved" line
    // when this coincides, never an unrelated error, so it must not bury the
    // one thing that tells the cashier the receipt did not print (round-2
    // finding: Billing.tsx:993).
    expect(pickBillAlert(noAlerts({ printProblem: true, note: true }))).toBe(
      "print-problem",
    );
  });

  it("an error note outranks a stale price list", () => {
    // save/holdBill/resumeHold/answerHold all report their failure through
    // `note` - it must not go silent just because the till is between other
    // states too.
    expect(pickBillAlert(noAlerts({ noPriceList: true, note: true }))).toBe("note");
  });

  it("follows the counter's own stacking order end to end", () => {
    // blocked > print problem > note > loading > no price list > gift > holds
    // due. `paper` is not in this list at all - see the doc comment on
    // `BillAlertKind`; it renders from its own always-on band instead of
    // taking turns on this line.
    const order: (keyof BillAlertFlags)[] = [
      "blocked",
      "printProblem",
      "note",
      "loading",
      "noPriceList",
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

// Whether a crashed draft's paper claim may be restored (#244). The same class
// of rule as `outstandingPaperSeq` above, and the same cost of getting it
// wrong: a re-entry restored as an ordinary bill takes a new number and prints
// a second receipt, and an ordinary cart restored onto a re-entry keys the
// wrong lines in under a number head office is waiting on.
describe("whether a draft's paper claim is safe to restore", () => {
  it("restores an ordinary draft onto an ordinary counter", () => {
    expect(paperConsistent(null, asked(""), counter())).toBe(true);
  });

  it("refuses an ordinary draft while the address bar is mid a re-entry", () => {
    // The cashier navigated here to key in bill 61. Landing an unrelated
    // crashed cart on it is the mixed-halves failure the atomic ruling names.
    expect(paperConsistent(null, asked("61"), counter())).toBe(false);
  });

  it("restores a paper draft onto the same re-entry", () => {
    expect(paperConsistent(61, asked("61"), counter())).toBe(true);
  });

  it("restores a paper draft onto a bare counter, since it carries its own number", () => {
    expect(paperConsistent(61, asked(""), counter())).toBe(true);
  });

  it("refuses a paper draft that contradicts the number in the address bar", () => {
    expect(paperConsistent(61, asked("62"), counter())).toBe(false);
  });

  it("refuses a paper draft whose number has since been keyed in", () => {
    expect(paperConsistent(61, asked(""), counter({ paperEntered: [61] }))).toBe(false);
  });

  it("refuses a paper draft whose number has since synced", () => {
    // 61 is no longer a hole - somebody else's bill closed it.
    const synced = counter({
      register: {
        fy: "26-27",
        last_accepted_seq: 73,
        holes: [62],
        hole_count: 1,
        series_open: true,
      },
    } as Partial<TillSnapshot>);
    expect(paperConsistent(61, asked(""), synced)).toBe(false);
  });
});
