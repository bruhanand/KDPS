import { describe, expect, it } from "vitest";

import { describePiece, olderSeasonFirst, resolveScan, searchPieces } from "./lookup";
import { item, season } from "./testSupport";

const SEASONS = [season("SS24", 1, "closed"), season("FW25", 2), season("SS26", 3)];

describe("the season a scan means", () => {
  it("takes the only one there is, and says how many are on the shelf", () => {
    const found = resolveScan("8901", {
      items: [item("8901", "FW25")],
      stock: [{ barcode: "8901", qty: 3 }],
      seasons: SEASONS,
    });

    expect(found.chosen?.season).toBe("FW25");
    expect(found.stock).toBe(3);
    expect(found.ambiguous).toBe(false);
  });

  it("takes the oldest live one when a piece was bought twice", () => {
    const found = resolveScan("8901", {
      items: [item("8901", "SS26"), item("8901", "FW25")],
      stock: [],
      seasons: SEASONS,
    });

    expect(found.chosen?.season).toBe("FW25");
    expect(found.candidates.map((c) => c.season)).toEqual(["FW25", "SS26"]);
    expect(found.ambiguous).toBe(true);
  });

  it("prefers a live season to an older closed one", () => {
    const found = resolveScan("8901", {
      items: [item("8901", "SS24"), item("8901", "FW25")],
      stock: [],
      seasons: SEASONS,
    });

    expect(found.chosen?.season).toBe("FW25");
    expect(found.candidates.map((c) => c.season)).toEqual(["FW25", "SS24"]);
  });

  it("sorts a season the master has never heard of last, not first", () => {
    // More likely a typo on a PT than the oldest thing in the shop - the same
    // reading `sell.services.resolve._season_rank` takes server-side.
    const found = resolveScan("8901", {
      items: [item("8901", "WHO-KNOWS"), item("8901", "SS26")],
      stock: [],
      seasons: SEASONS,
    });

    expect(found.chosen?.season).toBe("SS26");
  });

  it("orders two unknown seasons by name, so the same scan resolves the same way twice", () => {
    expect(olderSeasonFirst([], "ZZ", "AA")).toBeGreaterThan(0);
  });

  it("finds nothing for a barcode the counter has never heard of", () => {
    const found = resolveScan("9999", {
      items: [item("8901", "FW25")],
      stock: [{ barcode: "8901", qty: 3 }],
      seasons: SEASONS,
    });

    expect(found.chosen).toBeNull();
    expect(found.candidates).toEqual([]);
    expect(found.stock).toBe(0);
  });

  it("reads a barcode with no stock row as none on the shelf, and still sells it", () => {
    // A count that is wrong is not a reason to refuse a customer holding the
    // garment (grill Q6); the count goes negative and the stocktake settles it.
    const found = resolveScan("8901", {
      items: [item("8901", "FW25")],
      stock: [],
      seasons: SEASONS,
    });

    expect(found.chosen?.season).toBe("FW25");
    expect(found.stock).toBe(0);
  });

  it("ignores the whitespace a wedge scanner sends around a code", () => {
    const found = resolveScan("  8901\n", {
      items: [item("8901", "FW25")],
      stock: [],
      seasons: SEASONS,
    });

    expect(found.barcode).toBe("8901");
    expect(found.chosen?.season).toBe("FW25");
  });
});

describe("the tag that will not scan", () => {
  const shelf = [
    { ...item("8901", "FW25"), design: "SHIRT-01", item: "Shirt", brand: "MUFTI" },
    { ...item("8902", "FW25"), design: "TROUSER-9", item: "Trouser", brand: "LEVIS" },
    { ...item("8903", "FW25"), design: "SH-77", item: "Kurta", brand: "MANYAVAR" },
  ];

  it("finds a piece by the design number a person read off the tag", () => {
    expect(searchPieces(shelf, "trouser-9").map((r) => r.barcode)).toEqual(["8902"]);
  });

  it("puts a design the fragment starts before one that merely contains it", () => {
    expect(searchPieces(shelf, "sh").map((r) => r.design)).toEqual(["SH-77", "SHIRT-01"]);
  });

  it("finds a piece by brand and by what it is", () => {
    expect(searchPieces(shelf, "levis").map((r) => r.barcode)).toEqual(["8902"]);
    expect(searchPieces(shelf, "kurta").map((r) => r.barcode)).toEqual(["8903"]);
  });

  it("says nothing at all until there is enough to say it about", () => {
    expect(searchPieces(shelf, "s")).toEqual([]);
    expect(searchPieces(shelf, "  ")).toEqual([]);
  });

  it("caps what it offers, because somebody reads this standing up", () => {
    const many = Array.from({ length: 40 }, (_, i) => ({
      ...item(`89${i}`, "FW25"),
      design: `SHIRT-${i}`,
    }));

    expect(searchPieces(many, "shirt").length).toBe(8);
  });
});

describe("how a piece reads to a person", () => {
  it("names the garment the way the tag does", () => {
    expect(describePiece(item("8901", "FW25"))).toBe("MUFTI · Shirt · SHIRT-01 · M · NAVY");
  });

  it("drops what the books never filled in, rather than stranding a separator", () => {
    expect(describePiece({ ...item("8901"), brand: "", color: "" })).toBe("Shirt · SHIRT-01 · M");
  });
});
