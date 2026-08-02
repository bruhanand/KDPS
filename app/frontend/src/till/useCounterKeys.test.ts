import { describe, expect, it } from "vitest";

import { counterKeyAction } from "./useCounterKeys";

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
});
