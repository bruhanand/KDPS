import { describe, expect, it } from "vitest";

// navConfig.test asserts the *manifest* carries none of the five layer groups
// the redesign dissolved. This asserts the same thing about the *screens* — the
// half nobody was checking, and where eleven of them still said "Documents",
// "Store Ops", "Ledgers", "Outbound" or "Master data" long after the sidebar
// stopped. A page caption is navigation: it comes from the manifest
// (`components/PageHeader`), never typed by hand.

const SOURCES = import.meta.glob("./*.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

const DEAD = /\b(store ops|documents|ledgers|controls|intelligence|edges|master data|outbound)\b/i;

/** Every string a page renders as its kicker: `className="eyebrow">…<`. */
function eyebrows(source: string): string[] {
  return [...source.matchAll(/className="eyebrow"[^>]*>([^<{]*)</g)]
    .map((m) => m[1].trim())
    .filter(Boolean);
}

describe("screen captions", () => {
  const files = Object.keys(SOURCES);

  it("has pages to check", () => {
    expect(files.length).toBeGreaterThan(10);
  });

  for (const file of files) {
    it(`${file} uses none of the dissolved layer vocabulary`, () => {
      for (const caption of eyebrows(SOURCES[file])) {
        expect(caption, `${file}: “${caption}”`).not.toMatch(DEAD);
      }
    });
  }
});
