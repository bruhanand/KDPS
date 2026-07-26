import { matchRoutes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PROTECTED_ROUTES } from "./routes";
import { NAV_ITEMS, itemPath, resolveLegacyPath } from "./shell/navConfig";

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
      ["/stock-count", "count-list"],
      ["/stock-count/adjustments", "adjustment-list"],
      ["/stock-count/writeoffs", "writeoff-list"],
      ["/return-to-brand", "rtv-list"],
      ["/stock", "stock-on-hand"],
      ["/stock/history", "stock-history"],
      ["/stock/vflips", "vflip-list"],
      ["/money/vendor", "vendor-ledger"],
      ["/money/cash", "cash-ledger"],
      ["/setup/users", "setup-users"],
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
    // /transfer/requests and /transfer/distribution are planned pages, and
    // /transfer/in-transit is now built (#71) — all three sit where ids live.
    expect(screenAt("/transfer/requests")).toBe("planned:/transfer/requests");
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

  it("has one route per URL", () => {
    const paths = PROTECTED_ROUTES.map((r) => r.path);
    expect(new Set(paths).size).toBe(paths.length);
  });
});
