import { describe, expect, it } from "vitest";

import type { Brand, Store, User } from "../auth/AuthContext";
import { contextKey, switcherModel } from "./unitSwitcher";

function store(code: string, name: string, state = "Jharkhand"): Store {
  return {
    id: code.length + name.length,
    code,
    name,
    store_type: "store",
    state_name: state,
    state_code: state === "Bihar" ? "10" : "20",
    gstin_number: "10AAACK1234M1Z5",
  };
}

const DEO = store("DEO", "Deoghar");
const PAT = store("PAT", "Patna", "Bihar");
const PETER: Brand = { id: 1, code: "peter-england", name: "Peter England" };
const MUFTI: Brand = { id: 2, code: "mufti", name: "Mufti" };

function user(payload: Partial<User>): User {
  return {
    id: 1,
    username: "u",
    full_name: "U",
    is_superuser: false,
    role: null,
    scope_type: "store",
    scope_label: "Single store",
    entity: null,
    stores: [],
    nav_groups: [],
    landing_page: "home",
    business_units: [],
    all_business_units: false,
    business_unit_mode: "units",
    ...payload,
  };
}

describe("what the switcher offers", () => {
  it("locks a store person to their own store", () => {
    const model = switcherModel(user({ business_units: [DEO] }), DEO, null);
    expect(model.locked).toBe(true);
    expect(model.label).toBe("DEO · Deoghar");
    // No path to any other store, open or hidden.
    expect(model.options.filter((o) => o.kind === "unit")).toHaveLength(1);
  });

  it("gives an owner every unit plus the network view", () => {
    const model = switcherModel(
      user({ business_units: [DEO, PAT], all_business_units: true }),
      null,
      null,
    );
    expect(model.locked).toBe(false);
    expect(model.label).toBe("All stores (network)");
    expect(model.options.map((o) => o.kind)).toEqual(["all-units", "unit", "unit"]);
  });

  it("never calls a two-store aggregate the network", () => {
    // Someone with two stores may look at both at once — that is just their own
    // scope — but it is "all my stores", never the network they cannot see.
    const model = switcherModel(user({ business_units: [DEO, PAT] }), null, null);
    const all = model.options.find((o) => o.kind === "all-units");
    expect(all?.label).toBe("All my stores");
    expect(all?.label).not.toMatch(/network/i);
    expect(model.locked).toBe(false);
  });

  it("shows an empty, locked selector when there are no units (fail-closed)", () => {
    const model = switcherModel(user({}), null, null);
    expect(model.locked).toBe(true);
    expect(model.options).toEqual([]);
    expect(model.label).toBe("No unit assigned");
    // The failure mode that matters: never silently reading as network-wide.
    expect(model.label).not.toMatch(/all/i);
  });

  it("gives a brand manager brands instead of units", () => {
    const model = switcherModel(
      user({
        business_unit_mode: "brands",
        assigned_brands: [PETER, MUFTI],
        business_units: [DEO, PAT], // present in the payload, irrelevant here
      }),
      null,
      null,
    );
    expect(model.mode).toBe("brands");
    expect(model.options.map((o) => o.label)).toEqual([
      "All my brands",
      "Peter England",
      "Mufti",
    ]);
    expect(model.options.some((o) => o.kind === "unit")).toBe(false);
  });

  it("locks a brand manager with nothing assigned", () => {
    const model = switcherModel(user({ business_unit_mode: "brands" }), null, null);
    expect(model.locked).toBe(true);
    expect(model.label).toBe("No brand assigned");
  });

  it("reads the units from the payload, never from the role or scope word", () => {
    // Scope says "all" but the server sent no units and no network flag: the
    // client must believe the payload, not the label.
    const model = switcherModel(user({ scope_type: "all" }), null, null);
    expect(model.options).toEqual([]);
  });
});

describe("the context key", () => {
  it("changes when the working unit changes, so screens refetch", () => {
    expect(contextKey(DEO, null)).not.toBe(contextKey(PAT, null));
    expect(contextKey(null, null)).not.toBe(contextKey(DEO, null));
    expect(contextKey(null, PETER)).not.toBe(contextKey(null, MUFTI));
  });
});
