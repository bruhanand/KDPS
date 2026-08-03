import { describe, expect, it } from "vitest";

import { searchCountLabel } from "./SearchBox";

describe("searchCountLabel", () => {
  it("counts the unsearched list without claiming anything was searched", () => {
    expect(searchCountLabel(4, "booking", "")).toBe("4 bookings");
    expect(searchCountLabel(0, "transfer", "")).toBe("0 transfers");
  });

  it("says the count is of the searched set, and what was searched for", () => {
    expect(searchCountLabel(2, "transfer", "DEO")).toBe("2 transfers matching “DEO”");
  });

  it("keeps the singular honest — one row is not '1 bookings'", () => {
    expect(searchCountLabel(1, "booking", "")).toBe("1 booking");
    expect(searchCountLabel(1, "transfer", "DEO")).toBe("1 transfer matching “DEO”");
  });
});
