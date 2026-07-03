import { describe, expect, it } from "vitest";

import type { User } from "./AuthContext";
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

// Roles/groups mirror the seeded users (see DEPLOY.md / accounts fixtures).
const cashier = makeUser({
  role: { code: "store_cashier", name: "Cashier", landing_page: "/", nav_groups: ["home", "store_ops", "documents"] },
  nav_groups: ["home", "store_ops", "documents"],
});
const manager = makeUser({
  role: { code: "store_manager", name: "Manager", landing_page: "/", nav_groups: ["home", "store_ops", "documents", "ledgers"] },
  nav_groups: ["home", "store_ops", "documents", "ledgers"],
});
const accounts = makeUser({
  role: { code: "accounts", name: "Accounts", landing_page: "/", nav_groups: ["home", "ledgers", "documents"] },
  nav_groups: ["home", "ledgers", "documents"],
});
const owner = makeUser({
  role: { code: "owner", name: "Owner", landing_page: "/", nav_groups: ["home", "master_data", "ledgers", "edges_admin"] },
  nav_groups: ["home", "master_data", "ledgers", "edges_admin"],
});
const hoOps = makeUser({
  role: { code: "ho_ops", name: "HO Ops", landing_page: "/", nav_groups: ["home", "master_data"] },
  nav_groups: ["home", "master_data"],
});
const superuser = makeUser({ is_superuser: true });

describe("canAccess", () => {
  it("superuser reaches everything", () => {
    for (const p of ["/ledgers/vendor", "/masters/users", "/edges/rbac", "/intel/dashboards"]) {
      expect(canAccess(p, superuser)).toBe(true);
    }
  });

  it("home and unknown/stub routes are open to any signed-in user", () => {
    expect(canAccess("/", cashier)).toBe(true);
    expect(canAccess("/store/sell", cashier)).toBe(true); // store_ops stub
    expect(canAccess("/totally-unknown", cashier)).toBe(true);
  });

  it("cashier cannot reach ledgers, master data or edges by URL", () => {
    expect(canAccess("/ledgers/stock", cashier)).toBe(false);
    expect(canAccess("/ledgers/vendor", cashier)).toBe(false);
    expect(canAccess("/masters/users", cashier)).toBe(false);
    expect(canAccess("/edges/rbac", cashier)).toBe(false);
  });

  it("cashier keeps their own groups", () => {
    expect(canAccess("/documents/bookings", cashier)).toBe(true);
    expect(canAccess("/inbound", cashier)).toBe(true); // shared store_ops/documents
  });

  it("manager has ledgers group but not the finance-only ledgers", () => {
    expect(canAccess("/ledgers/stock", manager)).toBe(true);
    expect(canAccess("/ledgers/stock-on-hand", manager)).toBe(true);
    expect(canAccess("/ledgers/vendor", manager)).toBe(false);
    expect(canAccess("/ledgers/cash", manager)).toBe(false);
  });

  it("accounts (finance) reaches vendor/cash ledgers", () => {
    expect(canAccess("/ledgers/vendor", accounts)).toBe(true);
    expect(canAccess("/ledgers/cash", accounts)).toBe(true);
    expect(canAccess("/ledgers/stock", accounts)).toBe(true);
  });

  it("owner reaches finance ledgers and RBAC admin", () => {
    expect(canAccess("/ledgers/vendor", owner)).toBe(true);
    expect(canAccess("/masters/users", owner)).toBe(true);
    expect(canAccess("/edges/rbac", owner)).toBe(true);
  });

  it("ho_ops sees master_data but not the RBAC-admin pages (mirrors backend)", () => {
    expect(canAccess("/masters/stores", hoOps)).toBe(true);
    expect(canAccess("/masters/users", hoOps)).toBe(false);
  });
});
