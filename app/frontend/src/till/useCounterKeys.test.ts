import { describe, expect, it } from "vitest";

import { activeCounterKeyAction, counterKeyAction } from "./useCounterKeys";

describe("the counter keyboard map", () => {
  it("assigns the counter's function keys and escape", () => {
    expect(counterKeyAction("F2")).toBe("hold");
    expect(counterKeyAction("F3")).toBe("lookup");
    expect(counterKeyAction("F4")).toBe("new-bill");
    expect(counterKeyAction("F9")).toBe("save");
    expect(counterKeyAction("Escape")).toBe("back-to-scan");
  });

  it("leaves every other key alone", () => {
    expect(counterKeyAction("Enter")).toBeNull();
    expect(counterKeyAction("f2")).toBeNull();
    expect(counterKeyAction("x")).toBeNull();
  });

  it("uses Enter only to leave an open finish overlay", () => {
    expect(activeCounterKeyAction("Enter", false, true)).toBe("next-bill");
    expect(activeCounterKeyAction("F9", false, true)).toBeNull();
    expect(activeCounterKeyAction("Escape", false, true)).toBeNull();
    expect(activeCounterKeyAction("Enter", false, false)).toBeNull();
  });

  it("leaves the counter untouched while a decision surface is open", () => {
    expect(activeCounterKeyAction("F2", true, false)).toBeNull();
    expect(activeCounterKeyAction("F3", true, false)).toBeNull();
    expect(activeCounterKeyAction("F4", true, false)).toBeNull();
    expect(activeCounterKeyAction("F9", true, false)).toBeNull();
    expect(activeCounterKeyAction("Escape", true, false)).toBeNull();
    expect(activeCounterKeyAction("Enter", true, true)).toBeNull();
  });
});
