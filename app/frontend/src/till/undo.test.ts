// Stepping the bill back one action at a time (#244, grill ruling 30 Jul 2026).

import { describe, expect, it } from "vitest";

import { emptyCart } from "./cart";
import type { Cart } from "./cart";
import { UNDO_LIMIT, emptyUndo, popUndo, pushUndo } from "./undo";
import type { UndoStack } from "./undo";
import { emptyPayment } from "./tender";

/** A cart standing for "the bill after action N" - distinguishable by nothing
 *  but a tag, since these tests are about the stack's order and bound, not
 *  about what a cart holds. */
function cart(tag: number): Cart {
  return { ...emptyCart(), payment: { ...emptyPayment(), cash_received_paise: tag } };
}

function tagOf(c: Cart): number {
  return c.payment.cash_received_paise;
}

describe("stepping the bill backwards", () => {
  it("starts with nothing to undo", () => {
    expect(popUndo(emptyUndo())).toBeNull();
  });

  it("hands back the last snapshot pushed, and empties as it goes", () => {
    const stack = pushUndo(emptyUndo(), cart(1));

    const popped = popUndo(stack);

    expect(popped && tagOf(popped.cart)).toBe(1);
    expect(popped?.stack).toEqual(emptyUndo());
  });

  it("steps back one action at a time, most recent first", () => {
    let stack = emptyUndo();
    stack = pushUndo(stack, cart(1));
    stack = pushUndo(stack, cart(2));
    stack = pushUndo(stack, cart(3));

    const first = popUndo(stack);
    const second = first && popUndo(first.stack);
    const third = second && popUndo(second.stack);

    expect([first, second, third].map((p) => p && tagOf(p.cart))).toEqual([3, 2, 1]);
    expect(third?.stack).toEqual(emptyUndo());
  });

  it("has no redo - a popped step is gone, not parked to replay", () => {
    const stack = pushUndo(emptyUndo(), cart(1));
    const popped = popUndo(stack);

    // Nothing pushes it back: the caller that wanted a "redo" would have to
    // push it again itself, which nothing in this module does.
    expect(popUndo(popped?.stack ?? stack)).toBeNull();
  });

  it("bounds the depth, dropping the oldest step first", () => {
    let stack: UndoStack = emptyUndo();
    for (let n = 1; n <= UNDO_LIMIT + 5; n += 1) stack = pushUndo(stack, cart(n));

    expect(stack).toHaveLength(UNDO_LIMIT);
    expect(tagOf(stack[0])).toBe(6); // the oldest five fell off
    expect(tagOf(stack[stack.length - 1])).toBe(UNDO_LIMIT + 5);
  });
});
