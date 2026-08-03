import { describe, expect, it } from "vitest";

import { LatestRequest } from "./latest";

describe("latest-only asynchronous counter requests", () => {
  it("refuses an older answer after a newer request starts", () => {
    const requests = new LatestRequest();
    const first = requests.start();
    const second = requests.start();

    expect(first()).toBe(false);
    expect(second()).toBe(true);
  });

  it("invalidates an answer when the cashier changes state", () => {
    const requests = new LatestRequest();
    const current = requests.start();

    requests.invalidate();

    expect(current()).toBe(false);
  });
});
