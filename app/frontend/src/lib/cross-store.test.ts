import { describe, expect, it } from "vitest";

import {
  MIN_TERM,
  quotedArrivalIso,
  requestBody,
  rowsFor,
  storeIdByCode,
  totalQty,
  type AvailabilityDesignT,
} from "./cross-store";
import type { LocationT } from "./transfer-locations";

const DESIGN: AvailabilityDesignT = {
  design: "CH8801",
  brand: "AvBrand",
  item: "Chinos",
  sizes: [
    {
      size: "M",
      stores: [
        { store: "AV-A", store_name: "Store A", color: "Blue", sku_code: "CH-M-BL", hsn: "6203", season: "SS26", qty: 4 },
      ],
    },
    {
      size: "L",
      stores: [
        { store: "AV-WH", store_name: "Warehouse", color: "Blue", sku_code: "CH-L-BL", hsn: "6203", season: "SS26", qty: 7 },
        { store: "AV-WH", store_name: "Warehouse", color: "Red", sku_code: "CH-L-RD", hsn: "6203", season: "SS26", qty: 2 },
      ],
    },
  ],
};

const LOCATIONS: LocationT[] = [
  { id: 11, code: "AV-A", name: "Store A", store_type: "store", gstin: 1, state_code: "20", state_name: "Jharkhand" },
  { id: 22, code: "AV-WH", name: "Warehouse", store_type: "warehouse", gstin: 1, state_code: "20", state_name: "Jharkhand" },
];

describe("flattening a design for the table", () => {
  it("puts one size-and-place on each row, in the order the server sent them", () => {
    expect(rowsFor(DESIGN).map((r) => `${r.size}/${r.store}/${r.color}`)).toEqual([
      "M/AV-A/Blue",
      "L/AV-WH/Blue",
      "L/AV-WH/Red",
    ]);
  });

  it("keeps two colours of one size apart rather than summing them", () => {
    const l = rowsFor(DESIGN).filter((r) => r.size === "L");
    expect(l.map((r) => r.qty)).toEqual([7, 2]);
  });

  it("totals every piece anywhere", () => {
    expect(totalQty(DESIGN)).toBe(13);
  });
});

describe("the time quoted to the customer", () => {
  it("is sent as an instant, not as the letters the input showed", () => {
    const iso = quotedArrivalIso("2026-08-02T17:30");
    expect(iso).toBe(new Date("2026-08-02T17:30").toISOString());
    expect(iso).toMatch(/Z$/);
  });

  it("is nothing at all when nothing was quoted", () => {
    expect(quotedArrivalIso("")).toBeNull();
    expect(quotedArrivalIso("   ")).toBeNull();
  });

  it("is nothing at all rather than a wrong time when it cannot be read", () => {
    expect(quotedArrivalIso("not a time")).toBeNull();
  });
});

describe("resolving the place the search answered in", () => {
  it("finds the location the store code names", () => {
    expect(storeIdByCode(LOCATIONS, "AV-WH")).toBe(22);
  });

  it("answers null for a place this person cannot send to", () => {
    expect(storeIdByCode(LOCATIONS, "AV-B")).toBeNull();
    expect(storeIdByCode([], "AV-WH")).toBeNull();
  });
});

describe("what Request this posts", () => {
  const draft = {
    requestingStoreId: 11,
    fulfillingStoreId: 22,
    design: DESIGN,
    row: rowsFor(DESIGN)[2], // L, red, at the warehouse
    qty: 1,
    expectedArrivalLocal: "2026-08-02T17:30",
    notes: "Customer waiting",
  };

  it("names the exact piece the counter pointed at", () => {
    expect(requestBody(draft).lines).toEqual([
      {
        sku_code: "CH-L-RD",
        design: "CH8801",
        color: "Red",
        size: "L",
        brand: "AvBrand",
        season: "SS26",
        item: "Chinos",
        hsn: "6203",
        qty: 1,
      },
    ]);
  });

  it("always says where the ask came from", () => {
    expect(requestBody(draft).source).toBe("cross_store_search");
  });

  it("carries the quoted time as an instant, and null when none was given", () => {
    expect(requestBody(draft).expected_arrival_at).toMatch(/Z$/);
    expect(requestBody({ ...draft, expectedArrivalLocal: "" }).expected_arrival_at).toBeNull();
  });

  it("asks the store the piece was found in", () => {
    const body = requestBody(draft);
    expect(body.requesting_store).toBe(11);
    expect(body.fulfilling_store).toBe(22);
  });
});

it("agrees with the server about what is too short to search", () => {
  expect(MIN_TERM).toBe(3);
});
