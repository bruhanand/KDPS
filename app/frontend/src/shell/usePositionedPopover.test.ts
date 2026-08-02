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
      left: 400, // no clamp needed
      maxHeight: 834, // 1080 - 238 - 8
    });
  });

  it("clamps left when the trigger sits near the right edge", () => {
    const trigger = { top: 200, bottom: 230, left: 1200, right: 1280 };
    const viewport = { width: 1280, height: 1080 };
    expect(placePopover(trigger, viewport, 380, "below")).toEqual({
      top: 238,
      left: 892, // 1280 - 380 - 8, not trigger.left
      maxHeight: 834,
    });
  });

  it("clamps maxHeight on a short viewport", () => {
    const trigger = { top: 600, bottom: 630, left: 100, right: 480 };
    const viewport = { width: 1280, height: 768 };
    expect(placePopover(trigger, viewport, 380, "below")).toEqual({
      top: 638,
      left: 100,
      maxHeight: 122, // 768 - 638 - 8
    });
  });

  it("floors maxHeight rather than emit a negative CSS length", () => {
    const trigger = { top: 900, bottom: 930, left: 100, right: 480 };
    const viewport = { width: 1280, height: 768 };
    expect(placePopover(trigger, viewport, 380, "below").maxHeight).toBe(120);
  });
});
