import { matchRoutes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PROTECTED_ROUTES } from "./routes";
import { INVENTORY_FOLD, LEGACY_PATHS, NAV_ITEMS, itemPath, resolveLegacyPath } from "./shell/navConfig";

/** Which screen does this URL actually open? */
function screenAt(url: string): string | null {
  const matched = matchRoutes(PROTECTED_ROUTES, url);
  return matched?.[matched.length - 1]?.route.id ?? null;
}

describe("the route table", () => {
  it("opens the screen each canonical URL names", () => {
    const cases: [string, string][] = [
      ["/", "home"],
      ["/approvals", "approvals"],
      ["/booking", "booking-list"],
      ["/receive", "grn-list"],
      ["/receive/pt", "pt-list"],
      ["/transfer", "transfer-list"],
      ["/transfer/requests", "stock-request-list"],
      ["/stock-count", "count-list"],
      ["/stock-count/adjustments", "adjustment-list"],
      ["/stock-count/writeoffs", "writeoff-list"],
      ["/return-to-brand", "rtv-list"],
      // The folded page (#170): its own URL, no menu entry pointing at it.
      ["/inventory", "inventory"],
      ["/sell", "sell-billing"],
      ["/sell/till", "sell-till"],
      ["/stock", "stock-on-hand"],
      ["/stock/history", "stock-history"],
      ["/stock/vflips", "vflip-list"],
      ["/money/vendor", "vendor-ledger"],
      ["/money/cash", "cash-ledger"],
      ["/setup/users", "setup-users"],
      ["/setup/access", "setup-access"],
    ];
    for (const [url, id] of cases) expect(screenAt(url), url).toBe(id);
  });

  it("never lets a document id shadow a named sub-screen", () => {
    // The risk of `/receive/:id` living beside `/receive/new`: one wrong rank
    // and "create a GRN" silently becomes "open GRN number new".
    expect(screenAt("/receive/new")).toBe("grn-new");
    expect(screenAt("/receive/12")).toBe("grn-detail");
    expect(screenAt("/receive/pt/review")).toBe("pt-review");
    expect(screenAt("/receive/pt/proposals")).toBe("pt-proposals");
    expect(screenAt("/receive/pt/12")).toBe("pt-detail");
    expect(screenAt("/booking/new")).toBe("booking-new");
    expect(screenAt("/booking/12")).toBe("booking-detail");
    expect(screenAt("/transfer/new")).toBe("transfer-new");
    expect(screenAt("/transfer/requests/new")).toBe("stock-request-new");
    expect(screenAt("/transfer/requests/12")).toBe("stock-request-detail");
    expect(screenAt("/transfer/12")).toBe("transfer-detail");
    expect(screenAt("/return-to-brand/new")).toBe("rtv-new");
    expect(screenAt("/return-to-brand/12")).toBe("rtv-detail");
    expect(screenAt("/stock/vflips/new")).toBe("vflip-new");
    expect(screenAt("/stock/vflips/12")).toBe("vflip-detail");
    expect(screenAt("/stock-count/writeoffs/new")).toBe("writeoff-new");
    expect(screenAt("/stock-count/writeoffs/12")).toBe("writeoff-detail");
    // A count id lives in the same slot as the section's two named sub-screens.
    expect(screenAt("/stock-count/12")).toBe("count-detail");
  });

  it("Transfer sub-screens do not swallow the Transfer document ids", () => {
    // /transfer/distribution is still a planned page; /transfer/in-transit and
    // /transfer/requests are now built (#71, #74) — all three sit where ids live.
    expect(screenAt("/transfer/requests")).toBe("stock-request-list");
    expect(screenAt("/transfer/distribution")).toBe("planned:/transfer/distribution");
    expect(screenAt("/transfer/in-transit")).toBe("transfer-in-transit");
    expect(screenAt("/transfer/12")).toBe("transfer-detail");
    // The transfer's own PT hangs off the document, not off the section (#72).
    expect(screenAt("/transfer/12/pt")).toBe("transfer-pt");
  });

  it("gives every sidebar item somewhere to land", () => {
    for (const item of NAV_ITEMS) {
      expect(screenAt(itemPath(item)), item.to).not.toBeNull();
    }
  });

  it("gives every folded page somewhere to land, and leaves its tabs' own URLs alone", () => {
    // A fold is a second address for screens that keep their first one: the
    // sidebar sends a store person to /inventory, and /stock still opens Stock
    // on Hand for everybody the fold is not drawn to.
    expect(screenAt(INVENTORY_FOLD.to), INVENTORY_FOLD.to).not.toBeNull();
    for (const tab of INVENTORY_FOLD.tabs) {
      const path = tab.entry.split("?")[0];
      expect(screenAt(path), tab.entry).not.toBeNull();
    }
  });

  it("routes nothing at a legacy URL, so the redirect always wins", () => {
    // A legacy path that also matched a route would render that screen instead
    // of redirecting, and the old URL would quietly become canonical again.
    for (const item of NAV_ITEMS) {
      const legacy = resolveLegacyPath(itemPath(item));
      expect(legacy, `${item.to} must not be a legacy path`).toBeNull();
    }
    for (const old of ["/inbound/12", "/ledgers/vendor", "/outbound/rtvs/3", "/masters/stores"]) {
      expect(screenAt(old), old).toBeNull();
    }
  });

  it("redirects the deleted Upload Bill stub instead of reading it as a GRN id", () => {
    // The one legacy path that cannot be left to the catch-all (#228): it sits
    // exactly where `/receive/:id` looks for a document number, so without its
    // own route the old link opens "GRN number upload-bill" - a spinner and a
    // 404 - rather than the Receive screen.
    expect(screenAt("/receive/upload-bill")).toBe("legacy:/receive/upload-bill");
    expect(resolveLegacyPath("/receive/upload-bill")).toBe("/receive");
    // And the screen it lands on is still the one that owns the address.
    expect(screenAt("/receive")).toBe("grn-list");
  });

  it("gives a redirect route to every legacy path a screen would otherwise claim", () => {
    // The derivation, not the one path it currently finds: a legacy address that
    // a route claims is the case the catch-all cannot see, and it must never be
    // left to somebody noticing.
    for (const old of LEGACY_PATHS) {
      const id = screenAt(old);
      expect(id === null || id.startsWith("legacy:"), `${old} → ${id}`).toBe(true);
    }
  });

  it("has one route per URL", () => {
    const paths = PROTECTED_ROUTES.map((r) => r.path);
    expect(new Set(paths).size).toBe(paths.length);
  });
});
