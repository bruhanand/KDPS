import { describe, expect, it } from "vitest";

import { addLineIfAbsent } from "./ScanScreen";
import type { ScanTarget } from "./ScanScreen";

function target(barcode: string): ScanTarget {
  return { barcode, label: "Shirt · Blue · M", expected: null };
}

describe("addLineIfAbsent", () => {
  it("appends a barcode not yet in the list", () => {
    const found = target("8901234");
    expect(addLineIfAbsent([], found)).toEqual([found]);
  });

  it("skips a barcode already in the list, whatever line instance resolved", () => {
    // Two racing scans of the same new barcode each resolve their own lookup
    // and call this with their own (equal) ScanTarget object — #168.
    const first = target("8901234");
    const afterFirst = addLineIfAbsent([], first);

    const second = target("8901234");
    const afterSecond = addLineIfAbsent(afterFirst, second);

    expect(afterSecond).toEqual([first]);
    expect(afterSecond).toHaveLength(1);
  });

  it("leaves other lines untouched", () => {
    const other = target("1111111");
    const found = target("8901234");
    expect(addLineIfAbsent([other], found)).toEqual([other, found]);
  });
});
