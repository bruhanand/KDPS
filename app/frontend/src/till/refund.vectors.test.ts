// The two refund engines, on one set of golden cases (#184, D2).
//
// This file lives in the backend (`app/backend/sell/vectors/refunds.json`) and is
// read from disk here rather than copied, exactly as the GSTIN strings and the
// offer rulebook's carts are. A copy is a second file somebody updates one of -
// and the day the two copies differ is the day a counter prints a refund the
// server will not take, on a receipt already in a customer's hand, with every
// bill behind it stopped in the queue.
//
// So: this suite fails if `app/backend/sell/services/refunds.py` and
// `./exchange.ts` ever disagree about what a piece is worth back.
//
// What is *not* shared is in `exchange.test.ts`: the leg a refund becomes on the
// bill, its tax, and why an exchange cannot close - none of which has a Python
// counterpart, because the server is handed a finished leg rather than building
// one.

import { expect, it } from "vitest";

import { refundShare } from "./exchange";

interface Vectors {
  note: string;
  rule: string;
  cases: {
    why: string;
    paid: number;
    line_qty: number;
    returning: number;
    returned_qty: number;
    returned_paise: number;
    refund: number;
  }[];
}

// Vite's own glob rather than `node:fs`, so the suite needs no Node typings and
// so a path that stops resolving is a build error here rather than a silently
// empty run. The file is the backend's; see the header.
const LOADED = import.meta.glob<Vectors>("../../../backend/sell/vectors/refunds.json", {
  eager: true,
  import: "default",
});
const VECTORS: Vectors = Object.values(LOADED)[0];

it("found the shared vector file", () => {
  // A glob that matched nothing would leave the `it.each` below with an empty
  // list and the suite passing on no assertions at all.
  expect(VECTORS?.cases?.length).toBeGreaterThan(5);
});

it.each(VECTORS.cases)("$why", ({ paid, line_qty, returning, returned_qty, returned_paise, refund }) => {
  expect(
    refundShare({
      paid_paise: paid,
      line_qty,
      returning,
      returned_qty,
      returned_paise,
    }),
  ).toBe(refund);
});
