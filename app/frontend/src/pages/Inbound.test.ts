import { describe, expect, it } from "vitest";

import { activeFlow, receiveFlows } from "./Inbound";

/** The unit payload the switcher hands the screen, trimmed to what the rule
 *  reads. Nothing here is inferred from a role — only from the unit itself. */
const store = { store_type: "store" };
const warehouse = { store_type: "warehouse" };

describe("the Receive screen's flows", () => {
  it("offers a store the branded flow only", () => {
    // The server refuses a non-branded receipt anywhere but a warehouse, so
    // offering the tab at a store would walk a store person into a 400.
    expect(receiveFlows(store)).toEqual(["branded"]);
  });

  it("offers a warehouse both", () => {
    expect(receiveFlows(warehouse)).toEqual(["branded", "nonbranded"]);
  });

  it("offers both when no single unit is active", () => {
    // An owner on "All units" has not said where the goods are landing, so the
    // choice is still theirs to make; the store named on the receipt decides.
    expect(receiveFlows(null)).toEqual(["branded", "nonbranded"]);
  });

  it("draws no toggle at a store, and one at a warehouse", () => {
    // The screen draws the toggle on `flows.length > 1` — the single-flow unit
    // gets the flow itself, not a one-button switch.
    expect(receiveFlows(store).length > 1).toBe(false);
    expect(receiveFlows(warehouse).length > 1).toBe(true);
  });
});

describe("the flow the URL asks for", () => {
  it("is honoured where the unit has it", () => {
    expect(activeFlow(receiveFlows(warehouse), "nonbranded")).toBe("nonbranded");
    expect(activeFlow(receiveFlows(warehouse), "branded")).toBe("branded");
  });

  it("falls back to branded at a store, whatever the URL still says", () => {
    // The switcher changes the unit, not the query string: someone who was on
    // the warehouse's Non-branded tab and picked a store keeps `?tab=nonbranded`
    // in the address bar. Without the clamp the screen would list non-branded
    // receipts under a store, with no toggle to get back out of.
    expect(activeFlow(receiveFlows(store), "nonbranded")).toBe("branded");
  });

  it("is branded when the URL says nothing, or says nonsense", () => {
    expect(activeFlow(receiveFlows(warehouse), null)).toBe("branded");
    expect(activeFlow(receiveFlows(warehouse), "sideways")).toBe("branded");
  });
});
