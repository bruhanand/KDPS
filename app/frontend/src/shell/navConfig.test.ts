import { describe, expect, it } from "vitest";

import { NAV_ITEMS, SECTIONS, itemPath, resolveLegacyPath } from "./navConfig";

/** Does any screen in the manifest own `path` (itself or as its parent)? */
function claimed(path: string): boolean {
  return NAV_ITEMS.some((i) => {
    const owned = itemPath(i);
    return path === owned || path.startsWith(owned + "/");
  });
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
