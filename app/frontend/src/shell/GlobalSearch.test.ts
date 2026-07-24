import { describe, expect, it } from "vitest";

import { scanDestination } from "./GlobalSearch";
import type { SearchResponse, SearchResult } from "./GlobalSearch";

function hit(over: Partial<SearchResult>): SearchResult {
  return {
    kind: "document",
    title: "t",
    subtitle: "s",
    meta: "m",
    to: "/somewhere",
    exact: false,
    ...over,
  };
}

function body(...results: SearchResult[]): SearchResponse {
  return {
    query: "q",
    groups: [{ key: "g", label: "G", results, truncated: false }],
    total: results.length,
    notes: [],
  };
}

describe("scanDestination", () => {
  it("sends a scanned barcode straight to its stock, cohorts and all", () => {
    // One barcode, two seasons — two rows, one screen. Still unambiguous.
    const target = scanDestination(
      body(
        hit({ kind: "item", to: "/ledgers/stock-on-hand?sku=BB-1", exact: true }),
        hit({ kind: "item", to: "/ledgers/stock-on-hand?sku=BB-1", exact: true }),
      ),
    );
    expect(target?.to).toBe("/ledgers/stock-on-hand?sku=BB-1");
  });

  it("sends a full voucher number to that document", () => {
    expect(scanDestination(body(hit({ to: "/inbound/7", exact: true })))?.to).toBe("/inbound/7");
  });

  it("stays put when the answer is a choice, not an answer", () => {
    // Two different documents matched exactly — only the person can pick.
    expect(scanDestination(body(hit({ to: "/inbound/7", exact: true }), hit({ to: "/inbound/8", exact: true })))).toBeNull();
    // Partial matches only: the panel is the answer, Enter is not.
    expect(scanDestination(body(hit({ to: "/inbound/7" })))).toBeNull();
    // An exact match does not drag its partial neighbours along.
    expect(scanDestination(body(hit({ to: "/inbound/7", exact: true }), hit({ to: "/inbound/8" })))?.to).toBe("/inbound/7");
  });

  it("handles an empty or failed answer", () => {
    expect(scanDestination(null)).toBeNull();
    expect(scanDestination(body())).toBeNull();
  });
});
