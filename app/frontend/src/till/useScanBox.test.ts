import { describe, expect, it } from "vitest";

import { ownsTheKeyboard } from "./useScanBox";
import type { FocusTarget } from "./useScanBox";

/** An element as the focus patrol sees it. `inside` names an ancestor selector
 *  this element sits under, which is all `closest` is asked. */
function focused(
  tagName: string,
  extra: { inside?: string; isContentEditable?: boolean } = {},
): FocusTarget {
  return {
    tagName,
    isContentEditable: extra.isContentEditable,
    closest: (selector: string) => (selector === extra.inside ? {} : null),
  };
}

describe("who is allowed to keep the cursor", () => {
  // The whole point of the patrol is that a wedge scanner types into whatever
  // is focused. Take focus off a cashier mid-word and their discount, mobile
  // number or cash amount is truncated; leave it on a button and the next
  // barcode is lost as stray characters.

  it("lets a cashier finish typing into any box", () => {
    for (const tag of ["INPUT", "TEXTAREA", "SELECT"]) {
      expect(ownsTheKeyboard(focused(tag))).toBe(true);
    }
  });

  it("takes the cursor back from a button that was just pressed", () => {
    expect(ownsTheKeyboard(focused("BUTTON"))).toBe(false);
    expect(ownsTheKeyboard(focused("DIV"))).toBe(false);
    expect(ownsTheKeyboard(focused("A"))).toBe(false);
  });

  it("takes the cursor back when nothing is focused at all", () => {
    expect(ownsTheKeyboard(null)).toBe(false);
  });

  it("leaves anything inside a wedge-ignore region alone", () => {
    // A popover or dialogue that owns the keyboard while it is open: the button
    // inside it must not have focus pulled out from under it.
    expect(ownsTheKeyboard(focused("BUTTON", { inside: "[data-wedge-ignore]" }))).toBe(true);
  });

  it("leaves a contenteditable alone even though it is not an input", () => {
    expect(ownsTheKeyboard(focused("DIV", { isContentEditable: true }))).toBe(true);
  });
});
