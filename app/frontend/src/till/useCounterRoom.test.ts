import { describe, expect, it } from "vitest";

import { enterCounterRoom } from "./useCounterRoom";

describe("the counter room lifecycle", () => {
  it("dresses the document while mounted and restores it on cleanup", () => {
    const root = { dataset: {} as Record<string, string> } as HTMLElement;

    const leave = enterCounterRoom(root);
    expect(root.dataset.room).toBe("counter");

    leave();
    expect(root.dataset.room).toBeUndefined();
  });

  it("survives the setup-cleanup-setup sequence React StrictMode runs", () => {
    const root = { dataset: {} as Record<string, string> } as HTMLElement;

    enterCounterRoom(root)();
    const leaveSecondMount = enterCounterRoom(root);
    expect(root.dataset.room).toBe("counter");

    leaveSecondMount();
    expect(root.dataset.room).toBeUndefined();
  });
});
