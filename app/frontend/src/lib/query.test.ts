import { describe, expect, it } from "vitest";

import { withQuery } from "./query";

describe("withQuery", () => {
  it("leaves the path alone when there is nothing to ask", () => {
    expect(withQuery("/bookings")).toBe("/bookings");
    expect(withQuery("/bookings", {})).toBe("/bookings");
  });

  it("drops an empty or blank value, so an empty search box is not a search", () => {
    // The load-bearing case: with an untouched box the screen must make the
    // request it made before search existed, not a different one that happens
    // to return the same rows.
    expect(withQuery("/bookings", { q: "" })).toBe("/bookings");
    expect(withQuery("/bookings", { q: "   " })).toBe("/bookings");
    expect(withQuery("/bookings", { q: undefined })).toBe("/bookings");
    expect(withQuery("/bookings", { q: null })).toBe("/bookings");
  });

  it("trims the term — a trailing space from a scan is not part of the barcode", () => {
    expect(withQuery("/bookings", { q: "  KURTA  " })).toBe("/bookings?q=KURTA");
  });

  it("encodes a term that would otherwise change the URL's meaning", () => {
    expect(withQuery("/stockledger/on-hand", { q: "A&B 40%" })).toBe(
      "/stockledger/on-hand?q=A%26B+40%25",
    );
  });

  it("carries several filters together", () => {
    expect(withQuery("/outbound/transfers", { type: "inter_store", q: "DEO" })).toBe(
      "/outbound/transfers?type=inter_store&q=DEO",
    );
  });

  it("appends to a path that already carries a question mark", () => {
    expect(withQuery("/stockledger/on-hand?group_by=sku", { q: "DEO" })).toBe(
      "/stockledger/on-hand?group_by=sku&q=DEO",
    );
  });

  it("keeps a numeric filter", () => {
    expect(withQuery("/outbound/mark-damaged", { docstatus: 0 })).toBe(
      "/outbound/mark-damaged?docstatus=0",
    );
  });
});
