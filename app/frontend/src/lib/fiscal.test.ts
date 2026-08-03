// The client's financial year has to agree with the server's (#171): the grid
// draws the columns, the API keys the rows, and they meet on the month string.
// Two things can go wrong and both are silent - the Jan–Mar tail landing in the
// wrong year, and a timezone west of Greenwich shifting every column back a day.
import { describe, expect, it } from "vitest";

import { financialYear, financialYearChoices, financialYearMonths } from "./fiscal";

describe("financialYear", () => {
  it("opens in April", () => {
    expect(financialYear(new Date(2026, 3, 1))).toBe("26-27");
    expect(financialYear(new Date(2026, 2, 31))).toBe("25-26");
  });

  it("puts the January–March tail in the year that started the April before", () => {
    expect(financialYear(new Date(2027, 0, 15))).toBe("26-27");
    expect(financialYear(new Date(2027, 2, 31))).toBe("26-27");
    expect(financialYear(new Date(2027, 3, 1))).toBe("27-28");
  });
});

describe("financialYearMonths", () => {
  it("runs April to March", () => {
    const months = financialYearMonths("26-27");
    expect(months).toHaveLength(12);
    expect(months[0]).toEqual({ iso: "2026-04-01", label: "Apr 2026" });
    expect(months[11]).toEqual({ iso: "2027-03-01", label: "Mar 2027" });
  });

  it("labels each column with the year the month is actually in", () => {
    const byLabel = Object.fromEntries(financialYearMonths("26-27").map((m) => [m.label, m.iso]));
    expect(byLabel["Dec 2026"]).toBe("2026-12-01");
    expect(byLabel["Jan 2027"]).toBe("2027-01-01");
  });

  it("agrees with financialYear about every month it produces", () => {
    // The round trip, and the reason both functions live in one file: a column
    // the grid draws under `26-27` must be a month the server files under `26-27`.
    for (const { iso } of financialYearMonths("26-27")) {
      const [year, month] = iso.split("-").map(Number);
      expect(financialYear(new Date(year, month - 1, 1))).toBe("26-27");
    }
  });

  it("builds the ISO date from digits, never from a parsed Date", () => {
    // A `new Date("2026-04-01")` round trip would fail this west of Greenwich.
    // Asserted as an exact string set so the timezone can never get a vote.
    expect(financialYearMonths("26-27").map((m) => m.iso)).toEqual([
      "2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01",
      "2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01",
      "2026-12-01", "2027-01-01", "2027-02-01", "2027-03-01",
    ]);
  });

  it("refuses a label the server would refuse", () => {
    for (const label of ["", "2026", "26/27", "26-28", "26-26", "ab-cd"]) {
      expect(financialYearMonths(label)).toEqual([]);
    }
  });
});

describe("financialYearChoices", () => {
  it("offers next year, this year and last, newest first", () => {
    expect(financialYearChoices(new Date(2026, 7, 1))).toEqual(["27-28", "26-27", "25-26"]);
  });

  it("always contains the year we are standing in", () => {
    const on = new Date(2027, 1, 1);
    expect(financialYearChoices(on)).toContain(financialYear(on));
  });
});
