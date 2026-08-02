import { describe, expect, it, vi } from "vitest";

import { enterCounterRoom } from "./useCounterRoom";

describe("the counter room lifecycle", () => {
  it("dresses the document while mounted and restores it on cleanup", () => {
    const root = { dataset: {} as Record<string, string> } as HTMLElement;
    const refreshThemeColour = vi.fn();

    const leave = enterCounterRoom(root, refreshThemeColour);
    expect(root.dataset.room).toBe("counter");
    expect(refreshThemeColour).toHaveBeenCalledTimes(1);

    leave();
    expect(root.dataset.room).toBeUndefined();
    expect(refreshThemeColour).toHaveBeenCalledTimes(2);
  });

  it("survives the setup-cleanup-setup sequence React StrictMode runs", () => {
    const root = { dataset: {} as Record<string, string> } as HTMLElement;
    const refreshThemeColour = vi.fn();

    enterCounterRoom(root, refreshThemeColour)();
    const leaveSecondMount = enterCounterRoom(root, refreshThemeColour);
    expect(root.dataset.room).toBe("counter");

    leaveSecondMount();
    expect(root.dataset.room).toBeUndefined();
  });
});
