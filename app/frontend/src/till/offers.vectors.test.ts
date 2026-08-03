// The two engines, on one set of golden carts.
//
// These JSON files live in the backend (`app/backend/offers/vectors/`) and are
// read from disk here rather than copied, deliberately. A copy is a second file
// somebody updates one of - and the day the two copies differ is the day the
// counter and the books quietly start pricing the same cart differently, which
// is the exact failure this slice exists to make impossible.
//
// So: this suite fails if `app/backend/offers/resolution.py` and `./offers.ts`
// ever disagree about anything, and it fails on the *shape* too - the Python's
// `Resolution.as_dict()` and this port's return value are compared whole.

import { describe, expect, it } from "vitest";

import { hundredths, percentOf, resolveOffers } from "./offers";
import type { OfferCart, OfferCartLine, Resolution } from "./offers";
import type { TillOffer } from "./types";

interface Vector {
  name: string;
  note: string;
  day: string;
  declined_gifts: number[];
  offers: TillOffer[];
  lines: OfferCartLine[];
  expect: Resolution;
}

// Vite's own glob rather than `node:fs`, so the suite needs no Node typings and
// so a path that stops resolving is a build error here rather than an empty
// directory at run time. The files are the backend's; see the header.
const LOADED = import.meta.glob<Vector>("../../../backend/offers/vectors/*.json", {
  eager: true,
  import: "default",
});

const VECTORS: Vector[] = Object.keys(LOADED)
  .sort()
  .map((path) => LOADED[path]);

describe("the golden carts, priced by the till's own engine", () => {
  it("has the vectors the backend has", () => {
    // A path that silently resolved to an empty directory would make every case
    // below vacuous, and a green suite that asserts nothing is worse than a red
    // one. The count is the backend's; raising it is a two-file change.
    expect(VECTORS.length).toBe(12);
  });

  for (const vector of VECTORS) {
    it(`prices ${vector.name} exactly as the server does`, () => {
      const cart: OfferCart = {
        lines: vector.lines,
        day: vector.day,
        declinedGifts: vector.declined_gifts,
      };
      expect(resolveOffers(cart, vector.offers)).toEqual(vector.expect);
    });
  }
});

describe("the arithmetic both engines have to share", () => {
  it("rounds a percentage half-up, never to even", () => {
    expect(percentOf(100, 5000)).toBe(50);
    expect(percentOf(101, 5000)).toBe(51);
    expect(percentOf(103, 5000)).toBe(52);
    expect(percentOf(105, 5000)).toBe(53);
    expect(percentOf(0, 5000)).toBe(0);
    expect(percentOf(1000, 0)).toBe(0);
  });

  it("reads a percentage off its digits, never through a float", () => {
    expect(hundredths("7.50")).toBe(750);
    expect(hundredths("30")).toBe(3000);
    expect(hundredths("0.05")).toBe(5);
    expect(hundredths("")).toBe(0);
    expect(() => hundredths("half")).toThrow();
  });
});
