import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resolveTheme } from "./theme";

describe("resolveTheme", () => {
  it("returns the explicit preference regardless of system", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("light", false)).toBe("light");
    expect(resolveTheme("dark", true)).toBe("dark");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("follows the system for the system preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
});

/* vitest runs in node (no DOM), so we stub the browser globals the theme module
   touches. Each test re-imports the module (vi.resetModules) to reset its
   singleton state (initialised flag, listeners). */
function setupDom(opts: { stored?: string | null; systemDark?: boolean } = {}) {
  const store = new Map<string, string>();
  if (opts.stored != null) store.set("kdps-theme", opts.stored);
  let systemDark = opts.systemDark ?? false;

  const mqListeners = new Set<(e: { matches: boolean }) => void>();
  const mq = {
    get matches() {
      return systemDark;
    },
    addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => mqListeners.add(cb),
    removeEventListener: (_: string, cb: (e: { matches: boolean }) => void) => mqListeners.delete(cb),
  };
  const meta = {
    content: "",
    setAttribute(_: string, v: string) {
      this.content = v;
    },
  };
  const root = { dataset: {} as Record<string, string> };
  const winListeners: Record<string, ((e: { key: string }) => void)[]> = {};
  const localStorage = {
    getItem: (k: string) => (store.has(k) ? (store.get(k) as string) : null),
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
  const win = {
    localStorage,
    matchMedia: (_q: string) => mq,
    addEventListener: (ev: string, cb: (e: { key: string }) => void) => {
      (winListeners[ev] ??= []).push(cb);
    },
  };
  const doc = { documentElement: root, querySelector: (_sel: string) => meta };

  vi.stubGlobal("window", win);
  vi.stubGlobal("document", doc);
  vi.stubGlobal("localStorage", localStorage);
  vi.stubGlobal("getComputedStyle", () => ({
    getPropertyValue: (name: string) =>
      name === "--paper" && root.dataset.room === "counter" ? "counter-paper" : "",
  }));

  return {
    setSystemDark: (v: boolean) => {
      systemDark = v;
    },
    fireSystemChange: () => mqListeners.forEach((cb) => cb({ matches: systemDark })),
    fireStorage: (key: string, val: string | null) => {
      if (val == null) store.delete(key);
      else store.set(key, val);
      (winListeners.storage ?? []).forEach((cb) => cb({ key }));
    },
    dataTheme: () => root.dataset.theme,
    metaColor: () => meta.content,
    stored: () => store.get("kdps-theme") ?? null,
  };
}

describe("theme side effects", () => {
  beforeEach(() => vi.resetModules());
  afterEach(() => vi.unstubAllGlobals());

  it("getThemePreference defaults to system with no stored value", async () => {
    setupDom();
    const m = await import("./theme");
    expect(m.getThemePreference()).toBe("system");
  });

  it("getThemePreference reads a persisted value", async () => {
    setupDom({ stored: "dark" });
    const m = await import("./theme");
    expect(m.getThemePreference()).toBe("dark");
  });

  it("setThemePreference persists and applies data-theme + theme-color", async () => {
    const dom = setupDom({ systemDark: false });
    const m = await import("./theme");

    m.setThemePreference("dark");
    expect(dom.stored()).toBe("dark");
    expect(dom.dataTheme()).toBe("dark");
    expect(dom.metaColor()).toBe("#201d18");

    m.setThemePreference("light");
    expect(dom.dataTheme()).toBe("light");
    expect(dom.metaColor()).toBe("#faf7f2");
  });

  it("snapshot changes when the OS theme flips under the system preference", async () => {
    const dom = setupDom({ stored: "system", systemDark: false });
    const m = await import("./theme");
    m.initTheme();

    const before = m.getThemeSnapshot();
    dom.setSystemDark(true);
    dom.fireSystemChange();
    const after = m.getThemeSnapshot();

    expect(before).not.toBe(after);
    expect(after.endsWith("dark")).toBe(true);
    expect(dom.dataTheme()).toBe("dark");
  });

  it("ignores OS theme changes when the preference is explicit", async () => {
    const dom = setupDom({ stored: "light", systemDark: false });
    const m = await import("./theme");
    m.initTheme();

    dom.setSystemDark(true);
    dom.fireSystemChange();
    expect(dom.dataTheme()).toBe("light");
  });

  it("re-applies on a cross-tab storage event", async () => {
    const dom = setupDom({ stored: "light", systemDark: false });
    const m = await import("./theme");
    m.initTheme();
    expect(dom.dataTheme()).toBe("light");

    dom.fireStorage("kdps-theme", "dark");
    expect(dom.dataTheme()).toBe("dark");
  });

  it("keeps the counter room colour while the app theme changes", async () => {
    const dom = setupDom({ stored: "light", systemDark: false });
    const m = await import("./theme");
    m.initTheme();
    document.documentElement.dataset.room = "counter";

    m.refreshThemeColour();
    expect(dom.metaColor()).toBe("counter-paper");

    m.setThemePreference("dark");
    expect(dom.metaColor()).toBe("counter-paper");
  });
});
