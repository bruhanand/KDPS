import { describe, expect, it } from "vitest";

import {
  NAV_ITEMS,
  PERSONA_LAYOUTS,
  SECTIONS,
  applyLayout,
  isActiveItem,
  itemOwning,
  itemPath,
  resolveLegacyPath,
  visibleSections,
} from "./navConfig";
import type { NavRow, VisibleSection } from "./navConfig";

/** Does any screen in the manifest own `path` (itself or as its parent)? */
function claimed(path: string): boolean {
  return itemOwning(path) !== null;
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
      "staff",
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

describe("a persona's sidebar shape (#96)", () => {
  // What the server sends today, from `accounts/rbac_matrix.py`: the sheet's
  // "Store Person" row, plus #97's `staff: manage` for a manager. Written out
  // here rather than imported because the point of these tests is that the
  // *arrangement* obeys whatever the server says — including values an admin
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
    staff: "operate",
    reports: "view",
  };
  const MANAGER_CAPS = { ...STORE_CAPS, staff: "manage" };
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
    staff: "operate",
    reports: "view",
    setup: "operate",
  };

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

  function rowsFor(roleCode: string, caps: Record<string, string>): NavRow[] {
    return applyLayout(visibleSections(user(roleCode, caps)), roleCode);
  }

  /** Each row named as the person reads it: a section by its label, a grouping
   *  heading as "Heading > section, section". */
  function headings(rows: NavRow[]): string[] {
    return rows.map((r) =>
      r.kind === "section"
        ? r.section.label
        : `${r.group.heading} > ${r.sections.map((s) => s.label).join(", ")}`,
    );
  }

  function itemsUnder(rows: NavRow[], sectionCode: string): string[] {
    const all: VisibleSection[] = rows.flatMap((r) =>
      r.kind === "section" ? [r.section] : r.sections,
    );
    return all.find((s) => s.def.code === sectionCode)?.items.map((i) => i.label) ?? [];
  }

  it("gives a store cashier the screen the store asked for, twice", () => {
    // Booking is last because the layout does not name it: they were granted
    // `booking: view` on 26 July (#130) and it joins Inventory only when #101
    // scopes it. Held and unnamed ⇒ appended, never dropped.
    expect(headings(rowsFor("store_staff", STORE_CAPS))).toEqual([
      "Home",
      "Sell",
      "Inventory > Receive Goods, Transfer, Stock",
      "Reports",
      "Stock Count",
      "Money",
      "Offers & Price",
      "Booking",
    ]);
  });

  it("gives a store manager the same, plus the one Staff row", () => {
    const rows = rowsFor("store_manager", MANAGER_CAPS);
    expect(headings(rows)).toEqual([
      "Home",
      "Sell",
      "Inventory > Receive Goods, Transfer, Stock",
      "Reports",
      "Staff",
      "Stock Count",
      "Money",
      "Offers & Price",
      "Booking",
    ]);
    // Attendance has moved to Home, so Staff is Members alone and draws as one
    // line. A cashier has no Members and so no Staff row at all.
    expect(itemsUnder(rows, "staff")).toEqual(["Members"]);
    expect(headings(rowsFor("store_staff", STORE_CAPS))).not.toContain("Staff");
  });

  it("draws Attendance under Home for a store person and under Staff for everyone else", () => {
    const store = rowsFor("store_staff", STORE_CAPS);
    expect(itemsUnder(store, "home")).toEqual(["Dashboard", "Attendance", "Approvals", "Alerts"]);
    expect(itemsUnder(store, "staff")).toEqual([]);

    const warehouse = rowsFor("warehouse", WAREHOUSE_CAPS);
    expect(itemsUnder(warehouse, "home")).toEqual(["Dashboard", "Approvals", "Alerts"]);
    expect(itemsUnder(warehouse, "staff")).toEqual(["Attendance"]);
  });

  it("leaves Return to Brand off the store's sidebar, with damage still one click away", () => {
    const rows = rowsFor("store_staff", STORE_CAPS);
    expect(headings(rows)).not.toContain("Return to Brand");
    // The store keeps "mark damage only" — the entry is drawn under Stock, the
    // section that owns the screen, so nothing became unreachable.
    expect(itemsUnder(rows, "stock")).toContain("Damage / Quarantine");
    expect(itemsUnder(rowsFor("warehouse", WAREHOUSE_CAPS), "stock")).not.toContain(
      "Damage / Quarantine",
    );
  });

  it("groups without renaming: a store person still reads Transfer", () => {
    const rows = rowsFor("store_staff", STORE_CAPS);
    const grouped = rows.find((r) => r.kind === "group");
    expect(grouped?.kind === "group" && grouped.sections.map((s) => s.label)).toEqual([
      "Receive Goods",
      "Transfer",
      "Stock",
    ]);
  });

  it("keeps the grouping heading out of the section catalog", () => {
    // It owns no route, no section code and no server counterpart.
    const codes = new Set(SECTIONS.map((s) => s.code));
    for (const layout of Object.values(PERSONA_LAYOUTS)) {
      for (const row of layout.rows) {
        if (typeof row === "string") continue;
        expect(codes.has(row.heading.toLowerCase())).toBe(false);
        for (const code of row.sections) expect(codes.has(code)).toBe(true);
      }
    }
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
  // The invariant the whole of #96 rests on: grouping consumes the output of
  // the access filter, so it can reorder, nest or drop — never add.
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
        const granted = visibleSections({
          role: { code: role },
          is_superuser: false,
          sections: SECTIONS.filter((s) => caps[s.code]).map((s) => ({
            code: s.code,
            label: s.label,
            capability: caps[s.code],
          })),
        });
        const allowed = new Map(granted.map((s) => [s.def.code, new Set(s.items.map((i) => i.to))]));
        const rows = applyLayout(granted, role);
        const drawn = rows.flatMap((r) => (r.kind === "section" ? [r.section] : r.sections));

        expect(new Set(drawn.map((s) => s.def.code)).size, `${role}/${seed}`).toBe(drawn.length);
        for (const s of drawn) {
          expect(allowed.has(s.def.code), `${role}/${seed}: ${s.def.code}`).toBe(true);
          for (const item of s.items) {
            // The item may be drawn under another heading, but it must be one
            // the access filter passed *somewhere*: its gate travelled with it.
            const passed = [...allowed.values()].some((set) => set.has(item.to));
            expect(passed, `${role}/${seed}: ${item.to}`).toBe(true);
          }
        }
      }
    }
  });

  it("never draws a relocated entry for somebody who does not hold its section", () => {
    // Attendance belongs to Staff and keeps Staff's gate wherever it is drawn.
    const caps: Record<string, string> = { home: "view", stock: "view", sell: "operate" };
    const rows = applyLayout(
      visibleSections({
        role: { code: "store_staff" },
        is_superuser: false,
        sections: SECTIONS.filter((s) => caps[s.code]).map((s) => ({
          code: s.code,
          label: s.label,
          capability: caps[s.code],
        })),
      }),
      "store_staff",
    );
    const labels = rows.flatMap((r) =>
      (r.kind === "section" ? [r.section] : r.sections).flatMap((s) => s.items.map((i) => i.label)),
    );
    expect(labels).not.toContain("Attendance");
    // Same for the other move: no Return to Brand grant, no damage entry.
    expect(labels).not.toContain("Damage / Quarantine");
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
    function shape(caps: Record<string, string>) {
      return applyLayout(
        visibleSections({
          role: { code: "store_staff" },
          is_superuser: false,
          sections: SECTIONS.filter((s) => caps[s.code]).map((s) => ({
            code: s.code,
            label: s.label,
            capability: caps[s.code],
          })),
        }),
        "store_staff",
      ).map((r) => (r.kind === "section" ? r.section.label : r.group.heading));
    }
    // Revoked: Transfer goes, Inventory stays and keeps the other two.
    const { transfer: _dropped, ...withoutTransfer } = base;
    expect(shape(withoutTransfer)).toEqual(["Home", "Sell", "Inventory", "Reports"]);
    // Revoked to nothing under a heading: the heading goes with them.
    expect(shape({ home: "view", sell: "operate" })).toEqual(["Home", "Sell"]);
    // Newly granted and named nowhere in the layout: appended, not dropped.
    expect(shape({ ...base, setup: "operate" })).toEqual([
      "Home",
      "Sell",
      "Inventory",
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
