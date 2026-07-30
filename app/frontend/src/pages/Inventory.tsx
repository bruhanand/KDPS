/**
 * Inventory — the store's goods work on one page (#170, D10 §1).
 *
 * Stock, Stock Count and Return to Brand used to be three headings in the
 * sidebar. D10 folded them: "no subsections in the sidebar, ever — anything
 * that needs dividing divides inside the page, as tabs." So this is one URL
 * with four tabs, and each tab is an *existing* screen rendered unchanged.
 *
 * It is presentation and nothing else. No section code moved, no permission key
 * changed, and each tab is gated by the very menu entry it draws — the manifest
 * answers "may this person see this tab?" with the same call the sidebar makes
 * (`foldTabs`), so a role without count rights simply has no Count & Adjust tab
 * and the guard on this URL refuses anyone with no tab at all.
 *
 * The panels keep their own `PageHeader`; `HostedPageContext` tells that header
 * which screen is showing and hands it the tab strip, so folding a screen never
 * means editing it.
 */

import { useMemo } from "react";
import type { ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { HostedPageContext } from "../components/PageHeader";
import { INVENTORY_FOLD, foldTabs, resolveFoldTab, visibleSections } from "../shell/navConfig";
import { RTVListPage } from "./OutboundRTV";
import { StockCountListPage } from "./StockCount";
import StockOnHand from "./StockOnHand";
import "./PtMapper.css";

/** Tab slug → the screen it draws. Keys match `INVENTORY_FOLD.tabs`, which the
 *  test below pins, so a tab can never be added without a panel to show. */
const PANELS: Record<string, () => ReactElement> = {
  stock: () => <StockOnHand view="stock" />,
  damage: () => <StockOnHand view="quarantine" />,
  count: () => <StockCountListPage />,
  returns: () => <RTVListPage />,
};

export function InventoryPage() {
  const { user } = useAuth();
  const [params] = useSearchParams();

  const tabs = useMemo(() => (user ? foldTabs(INVENTORY_FOLD, visibleSections(user)) : []), [user]);
  const active = resolveFoldTab(tabs, params.get("tab"));

  // The route guard already refuses anyone with no tab, so this is the belt to
  // its braces — and it says so rather than rendering a blank page.
  if (!active) {
    return (
      <div className="page-pad">
        <p className="warn-note" data-testid="inventory-no-tabs">
          You have no inventory screens on your account.
        </p>
      </div>
    );
  }

  const strip = (
    <div className="seg" data-testid="inventory-tabs">
      {tabs.map((t) => (
        <Link
          key={t.slug}
          to={`/inventory?tab=${t.slug}`}
          className={`seg-btn ${t.slug === active.slug ? "active" : ""}`}
          aria-current={t.slug === active.slug ? "page" : undefined}
          data-testid={`inventory-tab-${t.slug}`}
        >
          {t.label}
        </Link>
      ))}
    </div>
  );

  const Panel = PANELS[active.slug];
  return (
    <HostedPageContext.Provider
      value={{ crumb: INVENTORY_FOLD.heading, title: active.label, tabs: strip }}
    >
      {/* Keyed on the tab: the panels are whole screens with their own state and
          fetches, so switching tabs mounts a fresh one rather than leaving the
          previous tab's filters and rows behind. */}
      <div key={active.slug}>
        <Panel />
      </div>
    </HostedPageContext.Provider>
  );
}
