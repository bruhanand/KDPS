import { describe, expect, it } from "vitest";

import type { NavSection, User } from "./AuthContext";
import { canAccess } from "./routeAccess";

function makeUser(over: Partial<User>): User {
  return {
    id: 1,
    username: "u",
    full_name: "U",
    is_superuser: false,
    role: null,
    scope_type: "store",
    scope_label: "Store",
    entity: null,
    stores: [],
    nav_groups: [],
    landing_page: "/",
    ...over,
  };
}

/** A user holding exactly these sections — the shape the server sends (#85). */
function withSections(
  caps: Record<string, NavSection["capability"]>,
  over: Partial<User> = {},
): User {
  return makeUser({
    capabilities: caps,
    sections: Object.entries(caps).map(([code, capability], order) => ({
      code,
      label: code,
      order,
      capability,
      scope_label: "",
    })),
    ...over,
  });
}

const ROLE = (code: string) => ({ code, name: code, landing_page: "/", nav_groups: [] });

// The six personas of the SIDEBAR RBAC matrix, at the capabilities the sheet
// grants them (accounts/rbac_matrix.py). Absent section ⇒ the role has none.
const storePerson = withSections(
  {
    home: "view",
    sell: "operate",
    receive_goods: "operate",
    transfer: "operate",
    stock_count: "operate",
    return_to_brand: "operate",
    stock: "view",
    money: "operate",
    offers_price: "view",
    staff: "operate",
    reports: "view",
  },
  { role: ROLE("store_staff") },
);
const warehouse = withSections(
  {
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
  },
  { role: ROLE("warehouse") },
);
const accounts = withSections(
  {
    home: "view",
    money: "manage",
    stock: "view",
    reports: "view",
    setup: "view",
    // "View (payroll inputs)" — Accounts reads salary inputs without operating
    // the floor's attendance, which is why it sits at `view` and not higher.
    staff: "view",
  },
  { role: ROLE("accounts") },
);
const owner = withSections(
  { home: "view", money: "manage", stock: "manage", setup: "manage", reports: "view" },
  { role: ROLE("owner") },
);
// Admin runs the system but keeps no books: the sheet's note (2) gives it_admin
// `money: none` deliberately, so every Money URL must be shut to it.
const admin = withSections(
  {
    home: "view",
    sell: "manage",
    booking: "manage",
    receive_goods: "manage",
    transfer: "view",
    stock_count: "manage",
    return_to_brand: "manage",
    stock: "manage",
    offers_price: "manage",
    staff: "manage",
    reports: "view",
    setup: "manage",
  },
  { role: ROLE("it_admin") },
);
const superuser = makeUser({ is_superuser: true });

describe("canAccess", () => {
  it("superuser reaches everything", () => {
    for (const p of ["/money/vendor", "/setup/users", "/reports/sales", "/stock/vflips"]) {
      expect(canAccess(p, superuser)).toBe(true);
    }
  });

  it("a user the server sent no sections reaches nothing but unclaimed paths", () => {
    const orphan = makeUser({});
    expect(canAccess("/", orphan)).toBe(false);
    expect(canAccess("/stock", orphan)).toBe(false);
    expect(canAccess("/money/vendor", orphan)).toBe(false);
    // Legacy URLs are unclaimed — they must load so the router can redirect
    // them, and the guard then applies at the screen's new home.
    expect(canAccess("/ledgers/vendor", orphan)).toBe(true);
  });

  it("the store person gets their day and nothing else", () => {
    expect(canAccess("/", storePerson)).toBe(true);
    expect(canAccess("/sell", storePerson)).toBe(true);
    expect(canAccess("/receive", storePerson)).toBe(true);
    expect(canAccess("/receive/pt/review", storePerson)).toBe(true);
    expect(canAccess("/transfer/7", storePerson)).toBe(true);
    expect(canAccess("/stock-count/adjustments", storePerson)).toBe(true);
    expect(canAccess("/staff/attendance", storePerson)).toBe(true);
    // No Booking and no Setup in the matrix — hidden in the menu, shut by URL.
    expect(canAccess("/booking", storePerson)).toBe(false);
    expect(canAccess("/setup/stores", storePerson)).toBe(false);
    expect(canAccess("/setup/users", storePerson)).toBe(false);
  });

  it("Money is one section but its books stay finance-only", () => {
    // The store person holds money:operate — "Expenses only" on the sheet. The
    // section opens, the vendor/cash books do not: those need money:manage, the
    // same rung the server's `finledger.IsBooksKeeper` demands.
    expect(canAccess("/money/expenses", storePerson)).toBe(true);
    expect(canAccess("/money/vendor", storePerson)).toBe(false);
    expect(canAccess("/money/cash", storePerson)).toBe(false);
    expect(canAccess("/money/vendor", warehouse)).toBe(false); // money:operate too
    expect(canAccess("/money/vendor", accounts)).toBe(true);
    expect(canAccess("/money/cash", accounts)).toBe(true);
    expect(canAccess("/money/vendor", owner)).toBe(true);
  });

  it("Admin keeps no books — every Money URL is shut", () => {
    // Regression: browser-testing #87 found the sidebar hiding Money from Admin
    // while the ledger API still served it vendor payables, because the gate was
    // a role list containing it_admin instead of the section it claims to mirror.
    for (const p of [
      "/money/expenses",
      "/money/vendor",
      "/money/cash",
      "/money/payments",
      "/money/bank",
      "/money/tally",
    ]) {
      expect(canAccess(p, admin)).toBe(false);
    }
    // Everything Admin *does* own still opens.
    expect(canAccess("/setup/users", admin)).toBe(true);
    expect(canAccess("/stock", admin)).toBe(true);
  });

  it("Staff opens attendance for the floor, records and salary for the back office", () => {
    // The store person holds staff:operate for their *own* attendance only.
    expect(canAccess("/staff/attendance", storePerson)).toBe(true);
    expect(canAccess("/staff/members", storePerson)).toBe(false);
    expect(canAccess("/staff/payroll", storePerson)).toBe(false);
    // Accounts sits *lower* on the ladder (staff:view) yet owns payroll inputs —
    // the case the ordinal ladder cannot express, so Payroll keeps a role list.
    expect(canAccess("/staff/payroll", accounts)).toBe(true);
    expect(canAccess("/staff/members", accounts)).toBe(false);
    expect(canAccess("/staff/members", admin)).toBe(true);
    expect(canAccess("/staff/payroll", admin)).toBe(true);
  });

  it("Users & Roles needs an RBAC-admin role, not just the Setup section", () => {
    expect(canAccess("/setup/users", warehouse)).toBe(false); // setup:operate only
    expect(canAccess("/setup/stores", warehouse)).toBe(true);
    expect(canAccess("/setup/users", owner)).toBe(true);
  });

  it("V-flip rides on the Stock section it is an action of", () => {
    expect(canAccess("/stock", storePerson)).toBe(true);
    expect(canAccess("/stock/vflips/3", storePerson)).toBe(true);
    // /stock is not a prefix of /stock-count — a different section entirely.
    expect(canAccess("/stock-count/writeoffs", accounts)).toBe(false);
  });

  it("the stock lookups global search sends people to are open to stock holders", () => {
    // Search returns stock results scoped to the caller, so the destination has
    // to open for anyone the matrix gives `stock` at any capability (#86).
    expect(canAccess("/stock", withSections({ stock: "view" }))).toBe(true);
    expect(canAccess("/stock/history", withSections({ stock: "view" }))).toBe(true);
    expect(canAccess("/stock", withSections({ home: "view" }))).toBe(false);
  });

  it("mixed-case URLs are guarded too (React Router matches case-insensitively)", () => {
    expect(canAccess("/MONEY/VENDOR", storePerson)).toBe(false);
    expect(canAccess("/Setup/Users", storePerson)).toBe(false);
    expect(canAccess("/Booking/12", storePerson)).toBe(false);
    expect(canAccess("/Money/Vendor", accounts)).toBe(true);
  });
});
