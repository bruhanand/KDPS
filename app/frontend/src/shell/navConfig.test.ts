import { describe, expect, it } from "vitest";

import {
  INVENTORY_FOLD,
  NAV_ITEMS,
  PERSONA_LAYOUTS,
  SECTIONS,
  applyLayout,
  foldTabs,
  headingOwning,
  isActiveFold,
  isActiveItem,
  itemOwning,
  itemPath,
  resolveFoldTab,
  resolveLegacyPath,
  sectionsIn,
  sidebarRows,
  testId,
  visibleSections,
} from "./navConfig";
import type { NavRow } from "./navConfig";

/** Does any screen in the manifest own `path` (itself or as its parent)? */
function claimed(path: string): boolean {
  return itemOwning(path) !== null;
}

/** The authenticated-user payload for a role holding `caps`, in the server's
 *  order (the catalog order). A section at `none` is simply not sent. */
function user(roleCode: string, caps: Record<string, string>) {
  return {
    role: { code: roleCode },
    is_superuser: false,
    sections: SECTIONS.filter((s) => caps[s.code]).map((s) => ({
      code: s.code,
      label: s.label,
      capability: caps[s.code],
    })),
  };
}

/** Each row named as the person reads it: a section by its label, a fold by its
 *  heading. Both draw as one row - a fold's tabs are inside its page. */
function headings(rows: NavRow[]): string[] {
  return rows.map((r) => (r.kind === "section" ? r.section.label : r.fold.heading));
}

/** The item labels drawn under one section. */
function itemsUnder(rows: NavRow[], sectionCode: string): string[] {
  return sectionsIn(rows).find((s) => s.def.code === sectionCode)?.items.map((i) => i.label) ?? [];
}

describe("the thirteen sections", () => {
  it("are the operations KDPS named, in order", () => {
    expect(SECTIONS.map((s) => s.code)).toEqual([
      "home",
      "sell",
      "booking",
      "receive_goods",
      "transfer",
      "stock_count",
      "return_to_brand",
      "stock",
      "money",
      "offers_price",
      "hrms",
      "reports",
      "setup",
    ]);
  });

  it("carry none of the old layer vocabulary", () => {
    // The groups the redesign dissolved. They must not survive as a section
    // name, an item label, or a URL segment.
    const dead = /store ops|outbound|documents|master data|ledgers|controls|intelligence|edges/i;
    for (const s of SECTIONS) {
      expect(s.label).not.toMatch(dead);
      for (const i of s.items) {
        expect(i.label).not.toMatch(dead);
        expect(itemPath(i)).not.toMatch(dead);
      }
    }
  });

  it("give every screen exactly one URL", () => {
    const owned = NAV_ITEMS.filter((i) => !i.deepLink).map(itemPath);
    expect(new Set(owned).size).toBe(owned.length);
  });

  it("point every deep link at a screen another section owns", () => {
    for (const i of NAV_ITEMS.filter((d) => d.deepLink)) {
      expect(claimed(itemPath(i))).toBe(true);
    }
  });

  it("list the approvals inbox once, inside Home", () => {
    const approvals = NAV_ITEMS.filter((i) => itemPath(i) === "/approvals");
    expect(approvals).toHaveLength(1);
    expect(approvals[0].section).toBe("home");
  });

  it("keep V-flip as an action inside Stock, not a menu item", () => {
    const vflip = NAV_ITEMS.find((i) => itemPath(i) === "/stock/vflips");
    expect(vflip?.section).toBe("stock");
    expect(vflip?.action).toBe(true);
  });
});

describe("the highlighted menu line", () => {
  // One screen has one URL (#87), so one URL lights one line. React Router's
  // own NavLink matching is prefix-based and lit every ancestor too: on
  // /receive/pt both "Receive (GRN)" and "PT Files" were rust, and on
  // /stock/history a *third* line lit in another section — Return to Brand's
  // "Damage / Quarantine", whose /stock?view=quarantine matches on path alone.

  it("is the deepest screen the URL sits under, never its parent as well", () => {
    // Each pair is a child URL and the single item that must own it.
    const cases: [url: string, owner: string][] = [
      ["/receive/pt", "/receive/pt"],
      ["/receive", "/receive"],
      ["/sell/returns", "/sell/returns"],
      ["/booking/new", "/booking/new"],
      ["/transfer/in-transit", "/transfer/in-transit"],
      ["/stock-count/writeoffs", "/stock-count/writeoffs"],
      ["/return-to-brand/new", "/return-to-brand/new"],
      ["/stock/history", "/stock/history"],
      ["/offers/discounts", "/offers/discounts"],
    ];
    for (const [url, owner] of cases) {
      const it = itemOwning(url);
      expect(it && itemPath(it), url).toBe(owner);
    }
  });

  it("stays on the list screen for a document under it", () => {
    // /booking/12 has no menu line of its own, so Bookings keeps the highlight.
    expect(itemOwning("/booking/12") && itemPath(itemOwning("/booking/12")!)).toBe("/booking");
    expect(itemOwning("/receive/pt/review") && itemPath(itemOwning("/receive/pt/review")!)).toBe(
      "/receive/pt",
    );
  });

  it("keeps Stock on Hand lit on V-flip, which has no line of its own", () => {
    // V-flip is an action reached from Stock on Hand, not a menu item — the
    // sidebar must not go dark while you are on it.
    const lit = NAV_ITEMS.filter((i) => isActiveItem(i, "/stock/vflips"));
    expect(lit.map((i) => i.label)).toEqual(["Stock on Hand"]);
    // The guard still resolves that URL to V-flip's own rule, not Stock's.
    expect(itemOwning("/stock/vflips") && itemPath(itemOwning("/stock/vflips")!)).toBe(
      "/stock/vflips",
    );
  });

  it("never lets a deep link claim the URL its host section owns", () => {
    // "Damage / Quarantine" points at /stock?view=quarantine, whose path *is*
    // /stock — so it used to light in Return to Brand on every /stock* URL,
    // alongside Stock's own line in another section.
    for (const url of ["/stock", "/stock/history", "/stock/vflips"]) {
      expect(itemOwning(url)?.section, url).toBe("stock");
      const quarantine = NAV_ITEMS.find((i) => i.deepLink)!;
      expect(isActiveItem(quarantine, url), url).toBe(false);
    }
  });

  it("is exactly one line for every URL in the manifest", () => {
    const menu = NAV_ITEMS.filter((i) => !i.action);
    const urls = [...new Set(menu.map(itemPath))];
    for (const url of urls) {
      const lit = menu.filter((i) => isActiveItem(i, url)).map((i) => `${i.section}:${i.label}`);
      expect(lit.length, `${url} → ${lit.join(" + ")}`).toBe(1);
    }
  });

  it("keeps Home's dashboard off every other screen", () => {
    expect(itemOwning("/") && itemPath(itemOwning("/")!)).toBe("/");
    for (const url of ["/booking", "/stock", "/setup/stores"]) {
      expect(itemOwning(url) && itemPath(itemOwning(url)!), url).not.toBe("/");
    }
  });

  it("lights nothing at an address no screen claims", () => {
    expect(itemOwning("/something-nobody-built")).toBeNull();
  });

  it("answers the same for a mixed-case or trailing-slash URL", () => {
    expect(itemOwning("/Receive/PT") && itemPath(itemOwning("/Receive/PT")!)).toBe("/receive/pt");
    expect(itemOwning("/receive/pt/") && itemPath(itemOwning("/receive/pt/")!)).toBe("/receive/pt");
  });
});

describe("a persona's sidebar shape (#96, folded by #170)", () => {
  // What the server sends today, from `accounts/rbac_matrix.py`: the sheet's
  // "Store Person" row, plus #97's `hrms: manage` for a manager. Written out
  // here rather than imported because the point of these tests is that the
  // *arrangement* obeys whatever the server says - including values an admin
  // retunes later, which is why several tests below change them.
  const STORE_CAPS: Record<string, string> = {
    home: "view",
    sell: "operate",
    booking: "view",
    receive_goods: "operate",
    transfer: "operate",
    stock_count: "operate",
    return_to_brand: "operate",
    stock: "view",
    money: "operate",
    offers_price: "view",
    hrms: "operate",
    reports: "view",
  };
  const MANAGER_CAPS = { ...STORE_CAPS, hrms: "manage" };
  const WAREHOUSE_CAPS: Record<string, string> = {
    home: "view",
    booking: "operate",
    receive_goods: "operate",
    transfer: "operate",
    stock_count: "operate",
    return_to_brand: "operate",
    stock: "manage",
    money: "operate",
    offers_price: "view",
    hrms: "operate",
    reports: "view",
    setup: "operate",
  };

  const rowsFor = (roleCode: string, caps: Record<string, string>) =>
    sidebarRows(user(roleCode, caps));

  // D10's ten, in D10's order.
  const TEN = [
    "Home",
    "Sell",
    "Inventory",
    "Receive Goods",
    "Transfer",
    "Booking",
    "Money",
    "Offers & Price",
    "Reports",
    "HRMS",
  ];

  it("gives a store cashier the ten flat sections D10 decided", () => {
    expect(headings(rowsFor("store_staff", STORE_CAPS))).toEqual(TEN);
  });

  it("gives a store manager the same ten", () => {
    // The manager differs from the cashier in one cell (`hrms: manage`), which
    // adds a line inside HRMS and no row to the sidebar.
    const rows = rowsFor("store_manager", MANAGER_CAPS);
    expect(headings(rows)).toEqual(TEN);
    expect(itemsUnder(rows, "hrms")).toEqual(["Attendance", "Member Details"]);
    expect(itemsUnder(rowsFor("store_staff", STORE_CAPS), "hrms")).toEqual(["Attendance"]);
  });

  it("nests no section under another - no subsections in the sidebar, ever", () => {
    // D10 §1's standing rule: anything that needs dividing divides inside the
    // page, as tabs. A row is a section or a fold; a fold draws one link.
    for (const rows of [rowsFor("store_staff", STORE_CAPS), rowsFor("warehouse", WAREHOUSE_CAPS)]) {
      for (const row of rows) expect(["section", "fold"]).toContain(row.kind);
    }
  });

  it("folds Stock, Stock Count and Return to Brand into Inventory's four tabs", () => {
    const rows = rowsFor("store_staff", STORE_CAPS);
    // The three heads are gone from the sidebar...
    for (const gone of ["Stock", "Stock Count", "Return to Brand"]) {
      expect(headings(rows)).not.toContain(gone);
    }
    // ...and their screens are the tabs of one page instead.
    const fold = rows.find((r) => r.kind === "fold");
    expect(fold?.kind === "fold" && fold.fold.to).toBe("/inventory");
    expect(fold?.kind === "fold" && fold.tabs.map((t) => t.label)).toEqual([
      "Stock on Hand",
      "Damage & Quarantine",
      "Count & Adjust",
      "Return to Brand",
    ]);
  });

  it("shows a store no tab it does not hold the section for", () => {
    // The acceptance criterion of #170: tabs stay gated by their original
    // codes, so revoking one takes its tab and nothing else.
    const { stock_count: _noCount, ...withoutCount } = STORE_CAPS;
    expect(foldTabs(INVENTORY_FOLD, visibleSections(user("store_staff", withoutCount)))
      .map((t) => t.label)).toEqual(["Stock on Hand", "Damage & Quarantine", "Return to Brand"]);

    const { return_to_brand: _noRtv, ...withoutRtv } = STORE_CAPS;
    expect(foldTabs(INVENTORY_FOLD, visibleSections(user("store_staff", withoutRtv)))
      .map((t) => t.label)).toEqual(["Stock on Hand", "Count & Adjust"]);

    // No folded section at all ⇒ no Inventory row: an empty page is not a page.
    const rows = sidebarRows(user("store_staff", { home: "view", sell: "operate" }));
    expect(headings(rows)).toEqual(["Home", "Sell"]);
  });

  it("falls back to the first tab this person can see", () => {
    // A slug that is unknown, or one whose tab they are not shown, must not
    // leave them on a page with nothing on it.
    const tabs = foldTabs(INVENTORY_FOLD, visibleSections(user("store_staff", STORE_CAPS)));
    expect(resolveFoldTab(tabs, "count")?.slug).toBe("count");
    expect(resolveFoldTab(tabs, "nonsense")?.slug).toBe("stock");
    expect(resolveFoldTab(tabs, null)?.slug).toBe("stock");
    expect(resolveFoldTab([], "stock")).toBeNull();
  });

  it("folds without renaming: a store person still reads Transfer", () => {
    // Folding may move a section onto a page; it may not give this persona a
    // private word for one. Every section still standing keeps the name the
    // warehouse and HO use for it.
    const rows = rowsFor("store_staff", STORE_CAPS);
    const byCode = new Map(SECTIONS.map((s) => [s.code, s.label]));
    for (const row of rows) {
      if (row.kind !== "section") continue;
      expect(row.section.label, row.key).toBe(byCode.get(row.key));
    }
    expect(headings(rows)).toContain("Transfer");
  });

  it("keeps the fold out of the section catalog, and its tabs inside it", () => {
    // A fold owns a URL but no section code and no server counterpart; every
    // section it stands for, and every entry it draws, is a real one.
    const codes = new Set(SECTIONS.map((s) => s.code));
    const entries = new Set(NAV_ITEMS.map((i) => i.to));
    for (const layout of Object.values(PERSONA_LAYOUTS)) {
      for (const row of layout) {
        if (typeof row === "string") continue;
        expect(codes.has(row.heading.toLowerCase())).toBe(false);
        expect(claimed(row.to), row.to).toBe(false);
        for (const code of row.sections) expect(codes.has(code), code).toBe(true);
        for (const tab of row.tabs) expect(entries.has(tab.entry), tab.entry).toBe(true);
      }
    }
  });

  it("says which row a screen is drawn under, folded or not", () => {
    // The sidebar must be able to show where you are - including when the
    // screen has been folded onto a page under a different name.
    expect(headingOwning("/inventory", "store_staff")).toBe("fold:/inventory");
    expect(headingOwning("/stock", "store_staff")).toBe("fold:/inventory");
    expect(headingOwning("/stock-count/adjustments", "store_staff")).toBe("fold:/inventory");
    expect(headingOwning("/stock", "warehouse")).toBe("stock");
    expect(headingOwning("/receive/pt", "store_staff")).toBe("receive_goods");
    expect(headingOwning("/staff/attendance", "store_staff")).toBe("hrms");
    expect(headingOwning("/nobody-built-this", "store_staff")).toBeNull();
  });

  it("lights the Inventory row on the screens it folded", () => {
    // A store person who lands on /stock from the global search still sees
    // which row they are on, even though no line points there any more.
    for (const url of ["/inventory", "/stock", "/stock/history", "/return-to-brand/3"]) {
      expect(isActiveFold(INVENTORY_FOLD, url), url).toBe(true);
    }
    for (const url of ["/receive", "/transfer", "/"]) {
      expect(isActiveFold(INVENTORY_FOLD, url), url).toBe(false);
    }
  });

  it("gives every line on a store person's sidebar its own test handle", () => {
    const handles = sectionsIn(rowsFor("store_manager", MANAGER_CAPS)).flatMap((s) =>
      s.items.map((i) => testId(s.def.code, i)),
    );
    expect(new Set(handles).size).toBe(handles.length);
  });

  it("leaves every other persona's sidebar flat and untouched", () => {
    for (const role of ["owner", "warehouse", "accounts", "it_admin", "brand_manager", "ho_ops"]) {
      const sections = visibleSections(user(role, WAREHOUSE_CAPS));
      expect(applyLayout(sections, role), role).toEqual(
        sections.map((s) => ({ kind: "section", key: s.def.code, section: s })),
      );
    }
  });
});

describe("arranging a sidebar can never widen it", () => {
  // The invariant the whole of #96 rests on, and #170 inherits: arranging
  // consumes the output of the access filter, so it can reorder, fold or drop -
  // never add.
  const ROLES = ["store_staff", "store_manager", "warehouse", "owner"];

  function shuffleCaps(seed: number): Record<string, string> {
    const rungs = ["view", "operate", "manage"];
    return Object.fromEntries(
      SECTIONS.map((s, i) => [s.code, rungs[(i + seed) % rungs.length]]).filter(
        (_, i) => (i + seed) % 4 !== 0, // a different section revoked each pass
      ),
    );
  }

  it("draws no section the server did not send, and no item access hid", () => {
    for (const role of ROLES) {
      for (let seed = 0; seed < 8; seed++) {
        const caps = shuffleCaps(seed);
        const granted = visibleSections(user(role, caps));
        const allowed = new Map(granted.map((s) => [s.def.code, new Set(s.items.map((i) => i.to))]));
        const rows = applyLayout(granted, role);
        const drawn = sectionsIn(rows);

        expect(new Set(drawn.map((s) => s.def.code)).size, `${role}/${seed}`).toBe(drawn.length);
        for (const s of drawn) {
          expect(allowed.has(s.def.code), `${role}/${seed}: ${s.def.code}`).toBe(true);
          for (const item of s.items) {
            expect(allowed.get(s.def.code)!.has(item.to), `${role}/${seed}: ${item.to}`).toBe(true);
          }
        }
        // A tab is a menu entry drawn somewhere else, so it answers to the same
        // filter: no tab may show a screen the sidebar would have hidden.
        for (const row of rows) {
          if (row.kind !== "fold") continue;
          for (const tab of row.tabs) {
            const passed = [...allowed.values()].some((set) => set.has(tab.entry));
            expect(passed, `${role}/${seed}: ${tab.entry}`).toBe(true);
          }
        }
      }
    }
  });

  it("draws no Inventory row for somebody holding none of its sections", () => {
    const rows = sidebarRows(user("store_staff", { home: "view", sell: "operate" }));
    expect(rows.some((r) => r.kind === "fold")).toBe(false);
  });

  it("survives a retune in either direction", () => {
    const base: Record<string, string> = {
      home: "view",
      sell: "operate",
      receive_goods: "operate",
      transfer: "operate",
      stock: "view",
      reports: "view",
    };
    const shape = (caps: Record<string, string>) => headings(sidebarRows(user("store_staff", caps)));
    expect(shape(base)).toEqual(["Home", "Sell", "Inventory", "Receive Goods", "Transfer", "Reports"]);
    // Revoked: Transfer goes, Inventory stays on the one section it still holds.
    const { transfer: _dropped, ...withoutTransfer } = base;
    expect(shape(withoutTransfer)).toEqual(["Home", "Sell", "Inventory", "Receive Goods", "Reports"]);
    // Revoked to nothing behind the fold: the fold goes with them.
    const { stock: _noStock, ...withoutStock } = base;
    expect(shape(withoutStock)).toEqual(["Home", "Sell", "Receive Goods", "Transfer", "Reports"]);
    // Newly granted and named nowhere in the layout: appended, not dropped.
    expect(shape({ ...base, setup: "operate" })).toEqual([
      "Home",
      "Sell",
      "Inventory",
      "Receive Goods",
      "Transfer",
      "Reports",
      "Setup",
    ]);
  });
});

describe("legacy URLs", () => {
  // Every route that existed before the redesign, with the screen it opened.
  const OLD_PATHS = [
    "/documents/bookings",
    "/documents/bookings/new",
    "/documents/bookings/12",
    "/documents/inbound",
    "/documents/inbound/new",
    "/documents/inbound/12",
    "/documents/pt-mapper",
    "/documents/pt-mapper/review",
    "/documents/pt-mapper/proposals",
    "/documents/pt-mapper/12",
    "/documents/sales",
    "/documents/transfers",
    "/documents/returns",
    "/documents/payments",
    "/inbound",
    "/inbound/new",
    "/inbound/12",
    "/outbound/transfers",
    "/outbound/transfers/new",
    "/outbound/transfers/12",
    "/outbound/rtvs",
    "/outbound/rtvs/new",
    "/outbound/rtvs/12",
    "/outbound/adjustments",
    "/outbound/adjustments/new",
    "/outbound/adjustments/12",
    "/outbound/writeoffs",
    "/outbound/writeoffs/new",
    "/outbound/writeoffs/12",
    "/outbound/vflips",
    "/outbound/vflips/new",
    "/outbound/vflips/12",
    "/ledgers/stock",
    "/ledgers/stock-on-hand",
    "/ledgers/vendor",
    "/ledgers/cash",
    "/masters/stores",
    "/masters/brands",
    "/masters/seasons",
    "/masters/gstins",
    "/masters/users",
    "/store/sell",
    "/store/receive",
    "/store/count",
    "/store/transfer",
    "/controls/exceptions",
    "/controls/recon",
    "/controls/approvals",
    "/controls/audit",
    "/intel/dashboards",
    "/intel/profitability",
    "/intel/dead-stock",
    "/intel/forecast",
    "/intel/reports",
    "/edges/integrations",
    "/edges/rbac",
    "/edges/tally",
    "/edges/pos",
    "/edges/config",
  ];

  it("all redirect to a screen that exists", () => {
    for (const old of OLD_PATHS) {
      const target = resolveLegacyPath(old);
      expect(target, old).not.toBeNull();
      expect(claimed(target!), `${old} → ${target}`).toBe(true);
    }
  });

  it("never redirect twice — a target is always a new URL", () => {
    for (const old of OLD_PATHS) {
      expect(resolveLegacyPath(resolveLegacyPath(old)!), old).toBeNull();
    }
  });

  it("keep the tail, so a bookmarked document still opens", () => {
    expect(resolveLegacyPath("/documents/bookings/12")).toBe("/booking/12");
    expect(resolveLegacyPath("/outbound/writeoffs/9")).toBe("/stock-count/writeoffs/9");
    expect(resolveLegacyPath("/documents/pt-mapper/review")).toBe("/receive/pt/review");
  });

  it("catch mixed case and trailing slashes", () => {
    expect(resolveLegacyPath("/Ledgers/Vendor")).toBe("/money/vendor");
    expect(resolveLegacyPath("/inbound/")).toBe("/receive");
  });

  it("leave new URLs alone", () => {
    for (const i of NAV_ITEMS) expect(resolveLegacyPath(itemPath(i)), i.to).toBeNull();
    expect(resolveLegacyPath("/something-nobody-built")).toBeNull();
  });
});
