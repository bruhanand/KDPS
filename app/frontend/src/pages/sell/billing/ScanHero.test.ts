import { describe, expect, it } from "vitest";

import { scanHeroState } from "./ScanHero";

describe("scan hero state", () => {
  it("names a normal sale scanner as listening", () => {
    expect(scanHeroState("sale", false)).toBe("LISTENING");
  });

  it("names a return scanner as awaiting the original bill", () => {
    expect(scanHeroState("return", false)).toBe("AWAITING BILL");
  });

  it("makes a failed scan visible until the cashier dismisses it", () => {
    expect(scanHeroState("sale", true)).toBe("NOT FOUND");
  });
});
