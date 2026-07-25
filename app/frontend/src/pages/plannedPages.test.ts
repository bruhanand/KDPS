import { describe, expect, it } from "vitest";

import { NAV_ITEMS, itemPath } from "../shell/navConfig";
import { PLANNED_PAGES } from "./plannedPages";

const plannedItems = NAV_ITEMS.filter((i) => i.planned && !i.deepLink);
const plannedPaths = plannedItems.map(itemPath);

/** Everything the entry puts in front of a reader, as one lowercase string. */
function copyAt(path: string): string {
  const page = PLANNED_PAGES[path];
  return [page.summary, ...page.contains, ...(page.notes ?? [])].join(" ").toLowerCase();
}

describe("the planned pages", () => {
  it("cover every unbuilt subsection, and nothing else", () => {
    // Both halves matter. A planned item with no entry renders a bare page; an
    // entry with no item is copy nobody can reach — and would go stale unseen.
    expect(Object.keys(PLANNED_PAGES).sort()).toEqual([...plannedPaths].sort());
  });

  it("leave the built screens alone", () => {
    for (const item of NAV_ITEMS.filter((i) => !i.planned)) {
      expect(PLANNED_PAGES[itemPath(item)], item.to).toBeUndefined();
    }
  });

  it("say what will live there, not that something is coming soon", () => {
    // The whole point of #89: a page that promises nothing specific tells the
    // client less than the report they are already holding.
    for (const path of plannedPaths) {
      const page = PLANNED_PAGES[path];
      // A sentence, not a label: a stub reads "Billing", a promise reads "the
      // counter screen — scan, bill, take the money."
      expect(page.summary, path).toMatch(/\.$/);
      expect(page.contains.length, path).toBeGreaterThanOrEqual(2);
      expect(copyAt(path), path).not.toContain("coming soon");
    }
  });

  it("place each screen in the module the client report gives it", () => {
    // The report is module-wise, so a screen under Sell that claimed to be part
    // of, say, Administration would make the demo and the report disagree.
    const byPrefix: [string, string][] = [
      ["/sell", "POS & Billing"],
      ["/money", "Accounts & Payments"],
      ["/offers", "Promotions & EOSS"],
      ["/staff", "HRMS & Payroll"],
      ["/transfer", "Transfers & Returns"],
      ["/setup", "Administration"],
    ];
    for (const [prefix, module] of byPrefix) {
      const under = plannedPaths.filter((p) => p === prefix || p.startsWith(prefix + "/"));
      expect(under.length, prefix).toBeGreaterThan(0);
      for (const path of under) expect(PLANNED_PAGES[path].module.name, path).toBe(module);
    }
  });
});

describe("Members", () => {
  const copy = copyAt("/staff/members");

  it("describes staff scorecards — the manager's own people", () => {
    for (const promise of ["staff", "bank details", "target", "growth"]) {
      expect(copy).toContain(promise);
    }
  });

  it("never says the staff-versus-customer question is still open", () => {
    // It was settled on 25 July 2026 (#96, shipped in #97). Copy that reopens it
    // would tell the client, inside the product, that we had not decided
    // something we had.
    for (const stale of ["pending", "undecided", "not yet decided", "to be confirmed", "or customer"]) {
      expect(copy, stale).not.toContain(stale);
    }
  });

  it("promises no loyalty or customer feature", () => {
    // Checked against the promises only, not the notes: the notes are where we
    // rule loyalty *out*, and a note saying "not a customer loyalty scheme" must
    // not read as a promise of one.
    for (const promise of PLANNED_PAGES["/staff/members"].contains) {
      expect(promise.toLowerCase(), promise).not.toMatch(/loyalty|customer|points|membership/);
    }
  });

  it("says it belongs to the deferred Attendance & Payroll module", () => {
    expect(copy).toContain("deferred");
    expect(PLANNED_PAGES["/staff/members"].module.name).toBe("HRMS & Payroll");
  });
});

describe("Attendance", () => {
  const copy = copyAt("/staff/attendance");

  it("is the store's daily surface — mark in, mark out, see the month", () => {
    expect(copy).toContain("check-in");
    expect(copy).toContain("leaves");
  });

  it("says plainly that no biometric device is integrated yet", () => {
    expect(copy).toContain("biometric");
    expect(copy).toContain("no device is integrated yet");
  });

  it("keeps payroll as a later, separate screen", () => {
    expect(copyAt("/staff/payroll")).toContain("after attendance");
  });
});

describe("Reports", () => {
  it("quotes the stores' own five report names", () => {
    const reports = copyAt("/reports/sales") + copyAt("/reports/stock");
    for (const asked of [
      "stock report",
      "sales report",
      "member-wise report",
      "item-wise report",
      "date-range sales report",
    ]) {
      expect(reports, asked).toContain(asked);
    }
  });

  it("does not pretend member-wise sales is only waiting on a screen", () => {
    // It needs every bill to record who sold it — undecided, unbuilt.
    expect(copyAt("/reports/sales")).toContain("who sold it");
  });
});
