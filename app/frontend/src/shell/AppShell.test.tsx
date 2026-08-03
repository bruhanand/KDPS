// @ts-expect-error Vitest runs in Node, while the production frontend deliberately excludes Node types.
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { SyncLight } from "../till/SyncLight";
import { AppShell } from "./AppShell";

const appShellCss = readFileSync(new URL("./AppShell.css", import.meta.url), "utf8");
const appShellRules = appShellCss.replace(/\/\*[\s\S]*?\*\//g, "");

vi.mock("../till/TillProvider", () => ({
  useTill: () => ({
    till: {
      status: {
        colour: "amber",
        label: "Offline",
        reason: "Working offline. Bills will sync when the line is back.",
      },
    },
  }),
}));

describe("the counter's shell chrome", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  function shell(room?: "counter"): string {
    return renderToStaticMarkup(
      <MemoryRouter>
        <AuthProvider>
          <AppShell room={room}>
            <div>Screen</div>
          </AppShell>
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  it("links the live sync pill to Till & Sync inside the counter room", () => {
    const html = shell("counter");

    expect(html).toContain('data-testid="counter-sync-link"');
    expect(html).toContain('href="/sell/till"');
    expect(html).toContain('data-testid="till-sync-light"');
    expect(html).toContain("Offline · will sync");
  });

  it("leaves every other route without counter chrome", () => {
    expect(shell()).not.toContain('data-testid="counter-sync-link"');
  });

  it("keeps the existing short label outside the counter top bar", () => {
    const html = renderToStaticMarkup(<SyncLight />);

    expect(html).toContain(">Offline<");
    expect(html).not.toContain("Offline · will sync");
  });
});

describe("the flat sidebar stylesheet contract", () => {
  it("attaches a square, shadowless rail directly to the left edge", () => {
    expect(appShellRules).toMatch(
      /\.sidebar\s*\{[^}]*border:\s*0;[^}]*border-right:\s*1px solid var\(--sidebar-border\);[^}]*border-radius:\s*0;[^}]*box-shadow:\s*none;[^}]*margin:\s*0;/s,
    );
    expect(appShellRules).toMatch(
      /\.sidebar-resizer\s*\{[^}]*margin-left:\s*-6px;[^}]*margin-right:\s*-6px;/s,
    );
  });

  it("leaves icons, the collapse control, and the profile row unboxed", () => {
    expect(appShellRules).toMatch(
      /\.nav-ic\s*\{[^}]*border-radius:\s*0;[^}]*background:\s*transparent;[^}]*border:\s*0;/s,
    );
    expect(appShellRules).toMatch(
      /\.sidebar-rail-toggle\s*\{[^}]*border:\s*0;[^}]*border-radius:\s*0;[^}]*background:\s*transparent;/s,
    );
    expect(appShellRules).toMatch(
      /\.profile-btn\s*\{[^}]*background:\s*transparent;[^}]*border:\s*0;[^}]*border-radius:\s*0;[^}]*box-shadow:\s*none;/s,
    );
  });

  it("uses a rust-tinted selected tab for expanded, nested, and rail destinations", () => {
    expect(appShellRules).toMatch(
      /\.nav-grouplink\.active\s*\{[^}]*background:\s*rgba\(var\(--rust-rgb\),\s*\.14\);[^}]*color:\s*var\(--rust\);[^}]*font-weight:\s*700;/s,
    );
    expect(appShellRules).toMatch(
      /\.nav-item\.active\s*\{[^}]*background:\s*rgba\(var\(--rust-rgb\),\s*\.14\);[^}]*color:\s*var\(--rust\);[^}]*font-weight:\s*700;/s,
    );
    expect(appShellRules).toMatch(
      /\.rail-link\.active,\s*\.rail-flyout-trigger\.active\s*\{[^}]*background:\s*rgba\(var\(--rust-rgb\),\s*\.14\);/s,
    );
    expect(appShellRules).not.toMatch(/\.nav-grouplink\.active::before/);
  });
});
