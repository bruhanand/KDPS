import { describe, expect, it } from "vitest";

import { destinationOptions, isCrossState, type LocationT } from "./transfer-locations";

// One GSTIN per state, as KDPS is registered: Jharkhand 7, Bihar 4.
const JH = { gstin: 7, state_code: "20", state_name: "Jharkhand" };
const BH = { gstin: 4, state_code: "10", state_name: "Bihar" };

const loc = (id: number, code: string, reg: typeof JH): LocationT => ({
  id,
  code,
  name: `${code} store`,
  store_type: "store",
  ...reg,
});

const DEO = loc(1, "DEO", JH);
const RAN = loc(2, "RAN", JH);
const PAT = loc(3, "PAT", BH);
const NETWORK = [DEO, RAN, PAT];

describe("destinationOptions", () => {
  it("offers the whole network minus the source", () => {
    expect(destinationOptions(NETWORK, "1").map((l) => l.code)).toEqual(["RAN", "PAT"]);
  });

  it("offers the other state too — cross-state is flagged, never blocked", () => {
    expect(destinationOptions(NETWORK, "1").map((l) => l.code)).toContain("PAT");
  });

  it("offers everything while no source is picked", () => {
    expect(destinationOptions(NETWORK, "")).toHaveLength(3);
  });

  it("is empty only when the network is", () => {
    expect(destinationOptions([], "1")).toEqual([]);
  });
});

describe("isCrossState", () => {
  it("is false within one registration", () => {
    expect(isCrossState(NETWORK, "1", "2")).toBe(false);
  });

  it("is true across Bihar ↔ Jharkhand, so the screen demands an e-way bill", () => {
    expect(isCrossState(NETWORK, "1", "3")).toBe(true);
    expect(isCrossState(NETWORK, "3", "1")).toBe(true);
  });

  // The server sets `is_cross_state` from `source.gstin_id != destination.gstin_id`.
  // Asking a narrower question here would let a transfer the books record as
  // cross-state pass the screen with no e-way bill.
  it("asks the same question the server does — registration, not state code", () => {
    const secondBiharReg = { ...PAT, id: 4, code: "MUZ", gstin: 9 };
    expect(isCrossState([PAT, secondBiharReg], "3", "4")).toBe(true);
  });

  it("is false until both ends are chosen", () => {
    expect(isCrossState(NETWORK, "1", "")).toBe(false);
    expect(isCrossState(NETWORK, "", "3")).toBe(false);
  });

  it("is false while the list is still loading", () => {
    expect(isCrossState([], "1", "3")).toBe(false);
  });
});

// The regression this whole module exists to prevent: one scoped list feeding
// both pickers, which left a store-scoped user with nothing to send to.
const SCREEN = import.meta.glob("../pages/OutboundTransfers.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
})["../pages/OutboundTransfers.tsx"] as string;

describe("the new-transfer screen", () => {
  it("fetches the network location list for the destination", () => {
    expect(SCREEN).toContain('"/masters/locations"');
  });

  it("still fetches the scoped store list for the source", () => {
    expect(SCREEN).toContain('"/masters/stores"');
  });

  it("does not feed the destination picker from the scoped store list", () => {
    const picker = SCREEN.match(/data-testid="transfer-dest-select"[\s\S]*?<\/select>/)?.[0];
    expect(picker, "destination <select> not found").toBeTruthy();
    expect(picker).toContain("destinations.map");
    expect(picker).not.toContain("stores");
  });
});
