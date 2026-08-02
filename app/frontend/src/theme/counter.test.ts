// @ts-expect-error Vitest runs in Node, while the production frontend deliberately excludes Node types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const counterCss = readFileSync(new URL("./counter.css", import.meta.url), "utf8");

describe("the counter's relationship to the KDPS design system", () => {
  it("inherits the application palette and UI typography in both themes", () => {
    const forbiddenOverrides = [
      "--paper",
      "--surface",
      "--sidebar",
      "--ink",
      "--muted",
      "--navy",
      "--rust",
      "--font-counter",
      "color-scheme",
      "font-family",
    ];

    for (const token of forbiddenOverrides) {
      expect(counterCss, `${token} belongs to the global KDPS theme`).not.toContain(token);
    }
  });

  it("keeps a functional mono face for scanner, money, and document codes", () => {
    expect(counterCss).toContain('--mono-counter: "IBM Plex Mono"');
    expect(counterCss).toContain("--mono: var(--mono-counter)");
    expect(counterCss).toContain("--tabular-font: var(--mono-counter)");
  });
});
