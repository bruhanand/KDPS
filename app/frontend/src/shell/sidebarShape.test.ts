import { describe, expect, it } from "vitest";

import type { NavSection, User } from "../auth/AuthContext";
import { NAV_ITEMS, itemPath, layoutSidebar, visibleSections } from "./navConfig";
import type { NavBand, NavRow } from "./navConfig";

// The sections each persona holds, as the SIDEBAR RBAC sheet grants them
// (`accounts/rbac_matrix.py`). Only the codes matter here — shaping never reads
// a capability, and the labels the server sends are the section's own.
const STORE_PERSON = [
  "home",
  "sell",
  "receive_goods",
  "transfer",
  "stock_count",
  "return_to_brand",
  "stock",
  "money",
  "offers_price",
  "staff",
  "reports",
];
const OWNER = [...STORE_PERSON.slice(0, 2), "booking", ...STORE_PERSON.slice(2), "setup"];

function user(
  roleCode: string,
  codes: string[],
  capability: NavSection["capability"] = "operate",
): User {
  return {
    id: 1,
    username: roleCode,
    full_name: roleCode,
    is_superuser: false,
    role: { code: roleCode, name: roleCode, landing_page: "home", nav_groups: [] },
    scope_type: "store",
    scope_label: "Single store",
    entity: null,
    stores: [],
    nav_groups: [],
    landing_page: "home",
    // The server sends the sections in its own order, with its own labels; the
    // fallback label is the manifest's, which is what these assertions read.
    sections: codes.map((code, order) => ({
      code,
      label: "",
      order,
      capability,
      scope_label: "",
    })),
  };
}

/** How the sidebar reads down the page: one line per heading. */
function headings(band: NavBand): string[] {
  return band.rows.map((row) => {
    if (row.kind === "group") return row.label;
    if (row.kind === "item") return row.item.label;
    return row.section.label || row.section.def.label;
  });
}

/** Every section code the shape put on screen, wherever it sits. */
function shownSections(bands: NavBand[]): string[] {
  const codes: string[] = [];
  for (const band of bands) {
    for (const row of band.rows) {
      if (row.kind === "group") codes.push(...row.sections.map((s) => s.def.code));
      else if (row.kind === "item") codes.push(row.section.def.code);
      else codes.push(row.section.def.code);
    }
  }
  return codes;
}

function shape(u: User): NavBand[] {
  return layoutSidebar(visibleSections(u), u.role?.code ?? "");
}

describe("the store person's daily screen", () => {
  // The stores wrote this list down twice — the hand-drawn "Store Ops" page of
  // 30 June and the notes of 25 July: Sell, Inventory, Reports, Attendance,
  // Member Details, with receiving, transfer and PT files under Inventory.
  const manager = shape(user("store_manager", STORE_PERSON, "manage"));
  const cashier = shape(user("store_staff", STORE_PERSON, "operate"));

  it("is the five headings the stores drew, in their order", () => {
    expect(headings(manager[0])).toEqual(["Sell", "Inventory", "Reports", "Attendance", "Members"]);
  });

  it("differs for a cashier by exactly one line — Members", () => {
    expect(headings(cashier[0])).toEqual(["Sell", "Inventory", "Reports", "Attendance"]);
  });

  it("nests Receive Goods, Transfer and Stock under Inventory, unrenamed", () => {
    const inventory = manager[0].rows.find((r) => r.kind === "group");
    expect(inventory?.kind).toBe("group");
    if (inventory?.kind !== "group") return;
    // The words are the ones every other role uses — grouping, never renaming.
    expect(inventory.sections.map((s) => s.def.label)).toEqual([
      "Receive Goods",
      "Transfer",
      "Stock",
    ]);
  });

  it("leaves Booking out of Inventory — that is #101, not this shape", () => {
    expect(shownSections(manager)).not.toContain("booking");
  });

  it("demotes the occasional sections to a collapsed More, never hides them", () => {
    const more = manager[1];
    expect(more.label).toBe("More");
    expect(more.collapsible).toBe(true);
    expect(headings(more)).toEqual([
      "Home",
      "Stock Count",
      "Return to Brand",
      // Money keeps its own name; a store person's only line inside it is
      // Expenses, so the section renders as that one link.
      "Money",
      "Offers & Price",
    ]);
  });

  it("adds no route and moves none — every line is a manifest screen", () => {
    const known = new Set(NAV_ITEMS.map(itemPath));
    const linked: string[] = [];
    for (const band of manager) {
      for (const row of band.rows) {
        if (row.kind === "item") linked.push(itemPath(row.item));
        else if (row.kind === "group")
          linked.push(...row.sections.flatMap((s) => s.items.map(itemPath)));
        else linked.push(...row.section.items.map(itemPath));
      }
    }
    expect(linked.length).toBeGreaterThan(0);
    for (const path of linked) expect(known.has(path), path).toBe(true);
  });
});

describe("every other persona", () => {
  // "Filter, don't rename" (#84): shaping is one persona's presentation layer,
  // so a role with no shape of its own must render exactly as it did before.
  for (const roleCode of ["owner", "warehouse", "accounts", "it_admin", "brand_manager"]) {
    it(`keeps ${roleCode} on the flat list, in the server's own order`, () => {
      const u = user(roleCode, OWNER, "manage");
      const bands = shape(u);
      expect(bands).toHaveLength(1);
      expect(bands[0].label).toBeNull();
      expect(bands[0].collapsible).toBe(false);
      expect(bands[0].rows.every((r: NavRow) => r.kind === "section")).toBe(true);
      expect(shownSections(bands)).toEqual(visibleSections(u).map((s) => s.def.code));
    });
  }
});

describe("shaping filters after access, never around it", () => {
  it("shows a store person nothing the server did not send", () => {
    const u = user("store_staff", STORE_PERSON);
    expect(new Set(shownSections(shape(u)))).toEqual(
      new Set(visibleSections(u).map((s) => s.def.code)),
    );
  });

  it("drops a section nobody holds from Inventory and from More alike", () => {
    // A retune an admin can make as data, with no release: this store person
    // has lost Transfer, Stock and Offers & Price.
    const thin = STORE_PERSON.filter((c) => !["transfer", "stock", "offers_price"].includes(c));
    const bands = shape(user("store_staff", thin));
    const shown = shownSections(bands);
    expect(shown).not.toContain("transfer");
    expect(shown).not.toContain("stock");
    expect(shown).not.toContain("offers_price");
    const inventory = bands[0].rows.find((r) => r.kind === "group");
    if (inventory?.kind !== "group") throw new Error("Inventory should survive on Receive Goods");
    expect(inventory.sections.map((s) => s.def.code)).toEqual(["receive_goods"]);
  });

  it("drops the Inventory heading entirely when none of its sections are held", () => {
    const thin = STORE_PERSON.filter((c) => !["receive_goods", "transfer", "stock"].includes(c));
    const bands = shape(user("store_staff", thin));
    expect(headings(bands[0])).toEqual(["Sell", "Reports", "Attendance"]);
  });

  it("still shows a section the shape has never heard of, under More", () => {
    // Booking or Setup granted to a store person is a data change with no
    // release behind it. It must appear — just not on the daily list.
    const bands = shape(user("store_staff", [...STORE_PERSON, "booking", "setup"]));
    expect(headings(bands[0])).toEqual(["Sell", "Inventory", "Reports", "Attendance"]);
    expect(headings(bands[1])).toContain("Booking");
    expect(headings(bands[1])).toContain("Setup");
  });

  it("gives a store person with no sections at all an empty, unbroken sidebar", () => {
    const bands = shape(user("store_staff", []));
    expect(bands.flatMap((b) => b.rows)).toEqual([]);
  });
});
