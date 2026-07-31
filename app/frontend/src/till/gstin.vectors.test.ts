// The two GSTIN checkers, on one set of golden strings.
//
// This file lives in the backend (`app/backend/sell/vectors/gstin.json`) and is
// read from disk here rather than copied, exactly as the offer rulebook's carts
// are. A copy is a second file somebody updates one of - and the day the two
// copies differ is the day the counter prints one tax and the books post
// another, which is the precise failure this pairing exists to make impossible.
//
// So: this suite fails if `app/backend/sell/gstin.py` and `./gstin.ts` ever
// disagree about whether a string is a GSTIN, about *why* it is not (the message
// is what a head-office clerk reads off the flag), about which state it names,
// or about which split a bill carries.
//
// Everything here is shared with Python. What is *not* shared is in
// `gstin.test.ts`: the check digit against three real registrations, and
// `splitTax`, which has no Python counterpart because the split is a
// presentation of one liability rather than two postings.

import { describe, expect, it } from "vitest";

import { describeGstin, normaliseGstin, taxKindFor } from "./gstin";
import type { B2bTaxKind } from "./gstin";

interface Vectors {
  note: string;
  well_formedness: { gstin: string; reason: string; why?: string }[];
  state_code: { gstin: string; state_code: string; why?: string }[];
  tax_kind: {
    buyer_gstin: string;
    store_state_code: string;
    kind: B2bTaxKind;
    why?: string;
  }[];
}

// Vite's own glob rather than `node:fs`, so the suite needs no Node typings and
// so a path that stops resolving is a build error here rather than a silently
// empty run. The file is the backend's; see the header.
const LOADED = import.meta.glob<Vectors>("../../../backend/sell/vectors/gstin.json", {
  eager: true,
  import: "default",
});
const VECTORS: Vectors = Object.values(LOADED)[0];

it("found the shared vector file", () => {
  // A glob that matched nothing would leave every `it.each` below with an empty
  // list and the suite passing on no assertions at all.
  expect(VECTORS?.well_formedness?.length).toBeGreaterThan(5);
});

describe("is this a GSTIN, and why not", () => {
  it.each(VECTORS.well_formedness)("$gstin", ({ gstin, reason }) => {
    expect(describeGstin(gstin)).toBe(reason);
  });
});

describe("which state it names", () => {
  it.each(VECTORS.state_code)("$gstin", ({ gstin, state_code }) => {
    expect(normaliseGstin(gstin).slice(0, 2)).toBe(state_code);
  });
});

describe("which split the bill carries", () => {
  it.each(VECTORS.tax_kind)("$buyer_gstin at $store_state_code", (vector) => {
    expect(taxKindFor(vector.buyer_gstin, vector.store_state_code)).toBe(vector.kind);
  });
});
