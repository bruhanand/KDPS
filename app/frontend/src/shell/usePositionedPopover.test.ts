// The placement math behind `usePositionedPopover` (#243 round 4). It has been
// wrong twice already - round 2 clamped the wrong axis, round 3's `maxHeight`
// formula never fired - and nothing caught either because the hook had no
// test at all. `placePopover` is pulled out pure so the formula can be pinned
// down without a DOM.

import { describe, expect, it } from "vitest";

import { placePopover } from "./usePositionedPopover";

describe("the sidebar flyout and profile panel (side: \"right\")", () => {
  it("sits beside the trigger, clamped to the bottom of a short viewport", () => {
    const trigger = { top: 700, bottom: 730, left: 100, right: 140 };
    const viewport = { width: 1280, height: 768 };
    expect(placePopover(trigger, viewport, 200, "right")).toEqual({
      top: 560, // 768 - 200 - 8
      left: 148, // trigger.right + margin
    });
  });

  it("does not clamp when the trigger has room below it", () => {
    const trigger = { top: 100, bottom: 130, left: 100, right: 140 };
    const viewport = { width: 1280, height: 768 };
    expect(placePopover(trigger, viewport, 200, "right")).toEqual({
      top: 100,
      left: 148,
    });
  });
});

describe("the Billing scan-box prompt (side: \"below\")", () => {
  it("hangs below the box on a wide viewport, unclamped", () => {
    const trigger = { top: 200, bottom: 230, left: 400, right: 780 };
    const viewport = { width: 1920, height: 1080 };
    expect(placePopover(trigger, viewport, 380, "below")).toEqual({
      top: 238, // trigger.bottom + margin
      bottom: undefined,
      left: 400, // no clamp needed
      maxHeight: 834, // 1080 - 238 - 8
    });
  });

  it("clamps left when the trigger sits near the right edge", () => {
    const trigger = { top: 200, bottom: 230, left: 1200, right: 1280 };
    const viewport = { width: 1280, height: 1080 };
    expect(placePopover(trigger, viewport, 380, "below")).toEqual({
      top: 238,
      bottom: undefined,
      left: 892, // 1280 - 380 - 8, not trigger.left
      maxHeight: 834,
    });
  });

  it("clamps maxHeight when the trigger still has the most room below it", () => {
    const trigger = { top: 300, bottom: 330, left: 100, right: 480 };
    const viewport = { width: 1280, height: 768 };
    expect(placePopover(trigger, viewport, 380, "below")).toEqual({
      top: 338,
      bottom: undefined,
      left: 100,
      maxHeight: 422, // 768 - 338 - 8, and still more than the 284 above
    });
  });

  it("anchors above the trigger when below it is the smaller half (#249)", () => {
    // The customer typeahead's field sits low on the payment rail: 122px below
    // it is five customers in a box the height of two. Anchored by `bottom`,
    // never `top`, so the list can be placed without measuring its height.
    const trigger = { top: 600, bottom: 630, left: 100, right: 480 };
    const viewport = { width: 1280, height: 768 };
    expect(placePopover(trigger, viewport, 380, "below")).toEqual({
      top: undefined,
      bottom: 176, // 768 - 600 + 8
      left: 100,
      maxHeight: 584, // 600 - 8 - 8
    });
  });

  it("stays below rather than flip when neither half has room", () => {
    // Both halves are cramped, so flipping would only move the problem: a
    // `bottom`-anchored box with the 120px floor applied would have its top
    // edge off the screen, and `position: fixed` cannot be scrolled back.
    const trigger = { top: 100, bottom: 280, left: 100, right: 480 };
    const viewport = { width: 1280, height: 300 };
    const at = placePopover(trigger, viewport, 380, "below");
    expect(at.top).toBe(288);
    expect(at.bottom).toBeUndefined();
    expect(at.maxHeight).toBe(120);
  });

  it("floors maxHeight rather than emit a negative CSS length", () => {
    // A trigger scrolled clean off the bottom: nothing below, everything
    // above, so it flips - and the floor is what guards the other direction.
    const offBottom = placePopover(
      { top: 900, bottom: 930, left: 100, right: 480 },
      { width: 1280, height: 768 },
      380,
      "below",
    );
    expect(offBottom.bottom).toBe(-124);
    expect(offBottom.maxHeight).toBe(884);

    const offTop = placePopover(
      { top: -30, bottom: 0, left: 100, right: 480 },
      { width: 1280, height: 40 },
      380,
      "below",
    );
    expect(offTop.top).toBe(8);
    expect(offTop.maxHeight).toBe(120);
  });
});
