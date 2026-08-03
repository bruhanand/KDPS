import { describe, expect, it } from "vitest";

import type { Brand, Store, User } from "../auth/AuthContext";
import { contextKey, optionKey, switcherModel, unitContextLabel } from "./unitSwitcher";

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
  it("locks a store person to their own store, named alone", () => {
    // The bar says only where you are. The code is menu detail, the state is
    // not the bar's to say at all (ruled 1 Aug 2026).
    const model = switcherModel(user({ business_units: [DEO] }), DEO, null);
    expect(model.locked).toBe(true);
    expect(model.label).toBe("Deoghar");
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
    expect(model.label).toBe("All business units");
    expect(model.options.map((o) => o.kind)).toEqual(["all-units", "unit", "unit"]);
  });

  it("never calls a two-store aggregate the network", () => {
    // Someone with two stores may look at both at once — that is just their own
    // scope — but it is "all my business units", never the network they cannot see.
    const model = switcherModel(user({ business_units: [DEO, PAT] }), null, null);
    const all = model.options.find((o) => o.kind === "all-units");
    expect(all?.label).toBe("All my business units");
    expect(all?.label).not.toMatch(/network/i);
    expect(model.locked).toBe(false);
  });

  it("offers a unit's store code beside its name, not inside it", () => {
    // The menu shows "Deoghar" with "DEO" as a hint the row draws separately —
    // never fused into one string the chip would then have to carry.
    const model = switcherModel(user({ business_units: [DEO, PAT] }), null, null);
    const deo = model.options.find((o) => o.kind === "unit" && o.store.code === "DEO");
    expect(deo?.label).toBe("Deoghar");
    expect(deo?.hint).toBe("DEO");
  });

  it("lets no state name into anything the bar or menu can draw", () => {
    // The state a unit bills under is a real fact, but the bar is not where it
    // gets said (ruled 1 Aug 2026). Sweep every drawable string.
    const models = [
      switcherModel(user({ business_units: [DEO, PAT], all_business_units: true }), DEO, null),
      switcherModel(user({ business_units: [DEO, PAT] }), PAT, null),
      switcherModel(user({ business_units: [DEO] }), DEO, null),
    ];
    for (const model of models) {
      const drawable = [model.label, ...model.options.flatMap((o) => [o.label, o.hint])];
      for (const text of drawable) {
        expect(text).not.toMatch(/bihar|jharkhand/i);
      }
    }
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

describe("what identifies a menu row", () => {
  it("keeps two same-named units apart", () => {
    // The real case this guards: KDPS has more than one unit per town name, and
    // since the bar stopped saying the code a row's label is only the name. Two
    // rows sharing a React key let React reuse the wrong one.
    const MAIN_A = store("DEO", "Main Road");
    const MAIN_B = store("RAN", "Main Road");
    const model = switcherModel(user({ business_units: [MAIN_A, MAIN_B] }), null, null);
    expect(model.options.map((o) => o.label)).toContain("Main Road");
    const keys = model.options.map(optionKey);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("keeps a unit and a brand of the same name apart", () => {
    expect(optionKey({ kind: "unit", label: "Mufti", hint: "", store: DEO })).not.toBe(
      optionKey({ kind: "brand", label: "Mufti", hint: "", brand: MUFTI }),
    );
  });

  it("gives the two aggregates their own identities", () => {
    expect(optionKey({ kind: "all-units", label: "All my business units", hint: "" })).toBe(
      "all-units",
    );
    expect(optionKey({ kind: "all-brands", label: "All my brands", hint: "" })).toBe("all-brands");
  });
});

describe("how the dashboard names the working unit", () => {
  it("names an active unit by code and name, with no state", () => {
    // The dashboard always says whose numbers these are (ruled 1 Aug 2026).
    // Code and name here - the dashboard is a report heading, not a chip -
    // but the state stays off it, same as the bar.
    expect(unitContextLabel(DEO)).toBe("DEO · Deoghar");
    expect(unitContextLabel(PAT)).not.toMatch(/bihar|jharkhand/i);
  });

  it("calls no active unit the aggregate, in business-unit language", () => {
    expect(unitContextLabel(null)).toBe("All business units");
  });
});

describe("the context key", () => {
  it("changes when the working unit changes, so screens refetch", () => {
    expect(contextKey(DEO, null)).not.toBe(contextKey(PAT, null));
    expect(contextKey(null, null)).not.toBe(contextKey(DEO, null));
    expect(contextKey(null, PETER)).not.toBe(contextKey(null, MUFTI));
  });
});
