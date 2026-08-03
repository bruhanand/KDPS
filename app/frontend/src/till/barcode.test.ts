import { describe, expect, it } from "vitest";

import { code128B, code128Svg } from "./barcode";

describe("Code 128 subset B", () => {
  it("encodes known symbols and the checksum for ABC", () => {
    // Start B, A, B, C, checksum 1, stop. The checksum is
    // (104 + 33×1 + 34×2 + 35×3) mod 103 = 1.
    expect(code128B("ABC")).toEqual([104, 33, 34, 35, 1, 106]);
  });

  it("encodes the full printed bill number without changing it", () => {
    expect(code128B("26-27/BANKA/SAL/1041")).toEqual([
      104, 18, 22, 13, 18, 23, 15, 34, 33, 46, 43, 33, 15, 51, 33, 44, 15, 17, 16, 20, 17, 28,
      106,
    ]);
  });

  it("draws bars in an SVG whose label keeps the source number", () => {
    const svg = code128Svg("26-27/DEO/SAL/74");

    expect(svg).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
    expect(svg).toContain('aria-label="Bill 26-27/DEO/SAL/74"');
    expect(svg).toContain("<rect");
  });

  it("refuses characters outside subset B", () => {
    expect(() => code128B("BILL₹1")).toThrow("Code 128 B");
  });
});
