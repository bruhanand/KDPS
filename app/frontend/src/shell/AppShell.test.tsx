import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { SyncLight } from "../till/SyncLight";
import { AppShell } from "./AppShell";

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
