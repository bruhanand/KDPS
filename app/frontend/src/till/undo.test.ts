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
    expect(tagOf(stack[0].cart)).toBe(6); // the oldest five fell off
    expect(tagOf(stack[stack.length - 1].cart)).toBe(UNDO_LIMIT + 5);
  });
});

// The grid's cells fire an edit per keystroke, so a run of typing in one box
// must collapse to one step - otherwise Undo walks back through "₹15" and "₹1"
// to reach the price the line actually had, and a bounded stack fills with
// characters instead of actions.
describe("a run of typing is one step", () => {
  it("keeps only the state before the typing started", () => {
    let stack = emptyUndo();
    stack = pushUndo(stack, cart(1), "line-a:discount_paise");
    stack = pushUndo(stack, cart(2), "line-a:discount_paise");
    stack = pushUndo(stack, cart(3), "line-a:discount_paise");

    expect(stack).toHaveLength(1);
    const popped = popUndo(stack);
    expect(popped && tagOf(popped.cart)).toBe(1);
  });

  it("keeps a different field on the same line as its own step", () => {
    let stack = emptyUndo();
    stack = pushUndo(stack, cart(1), "line-a:discount_paise");
    stack = pushUndo(stack, cart(2), "line-a:qty");

    expect(stack).toHaveLength(2);
  });

  it("keeps the same field on a different line as its own step", () => {
    let stack = emptyUndo();
    stack = pushUndo(stack, cart(1), "line-a:discount_paise");
    stack = pushUndo(stack, cart(2), "line-b:discount_paise");

    expect(stack).toHaveLength(2);
  });

  it("does not collapse a discrete action into a run, or two of them together", () => {
    let stack = emptyUndo();
    stack = pushUndo(stack, cart(1)); // a scan
    stack = pushUndo(stack, cart(2)); // another scan

    expect(stack).toHaveLength(2);
  });

  it("lets a scan between two edits of one field break the run", () => {
    let stack = emptyUndo();
    stack = pushUndo(stack, cart(1), "line-a:discount_paise");
    stack = pushUndo(stack, cart(2)); // a scan lands
    stack = pushUndo(stack, cart(3), "line-a:discount_paise");

    // Three separate things happened, so there are three ways back.
    expect(stack).toHaveLength(3);
  });
});
