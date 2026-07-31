import { describe, expect, it } from "vitest";

import { NAV_ITEMS, itemPath } from "../shell/navConfig";
import { PLANNED_PAGES, REPORT_MODULES } from "./plannedPages";

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
      // counter screen — scan, bill, take the money." Word count, not exact
      // punctuation — copy edits should not have to come back here.
      expect(page.summary.trim().split(/\s+/).length, path).toBeGreaterThan(5);
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
      for (const path of under) expect(PLANNED_PAGES[path].module.name, path).toBe(module);
    }
    // A prefix with nothing under it is not a mistake and is no longer asserted
    // against: it is a module that has been *built out*, which is what happened
    // to Sell when #184 landed the last of its four screens. The strip itself is
    // checked whole below, so finishing a module cannot silently drop it from
    // the client's report either.
  });
});

describe("the report's own sequence", () => {
  it("gives each module the position the report gives it", () => {
    // The report's strip reads: Done (Core Platform · Goods Receipt) → Now
    // (Purchase Orders · Transfers & Returns) → Next (POS & Billing) → Then
    // (Accounts & Payments) → Later (HRMS · Promotions · Analytics).
    //
    // The two "already moving" modules are the trap. Their in-build column names
    // dispatch/receive, IGST, RTV and adjustments — not Stock Request,
    // Distribution or In-Transit. So those screens are *not* in build, and must
    // carry the report's third column ("Planned") rather than a chip that
    // promises motion nobody has started. (Goods Receipt keeps its place on the
    // strip with nothing planned left under it, since #228 deleted the Upload
    // Bill stub - the same case as POS & Billing below.)
    const expected: Record<string, string> = {
      "POS & Billing": "next",
      "Accounts & Payments": "then",
      "Promotions & EOSS": "later",
      "HRMS & Payroll": "later",
      "Reports & Analytics": "later",
      "Goods Receipt": "unscheduled",
      "Transfers & Returns": "unscheduled",
      "Inventory Management": "unscheduled",
      Administration: "unscheduled",
    };
    // The strip itself, whole - including a module with nothing planned left
    // under it. POS & Billing is that module since #184 finished Sell, and it is
    // still on the client's report.
    expect(Object.fromEntries(REPORT_MODULES.map((m) => [m.name, m.stage]))).toEqual(expected);
    for (const path of plannedPaths) {
      const { name, stage } = PLANNED_PAGES[path].module;
      expect(Object.keys(expected), `${path} → ${name}`).toContain(name);
      expect(stage, `${path} → ${name}`).toBe(expected[name]);
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
  });

  it("says plainly that no biometric device is integrated yet", () => {
    expect(copy).toContain("biometric");
    expect(copy).toMatch(/no device is integrated|not integrated/);
  });

  it("keeps payroll as a later, separate screen", () => {
    // Payroll is the last part of the deferred module, not the first.
    expect(copyAt("/staff/payroll")).toMatch(/attendance/);
    expect(PLANNED_PAGES["/staff/payroll"].module.stage).toBe("later");
  });
});

describe("Reports", () => {
  it("quotes the stores' own five report names, in their order", () => {
    // The 25 July note lists them: stock, sales, member-wise, item-wise,
    // date-range. Stock is its own page; the other four are Sales Reports, and
    // the page says out loud that they are in the stores' order — so they are.
    expect(PLANNED_PAGES["/reports/stock"].contains).toContain("Stock report");
    expect(PLANNED_PAGES["/reports/sales"].contains).toEqual([
      "Sales report",
      "Member-wise report",
      "Item-wise report",
      "Date-range sales report",
    ]);
  });

  it("does not pretend member-wise sales is only waiting on a screen", () => {
    // It needs every bill to record who sold it — undecided, unbuilt.
    expect(copyAt("/reports/sales")).toContain("who sold it");
  });
});
