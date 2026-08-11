import { evidence, expect, loginAs, test } from "./kdps";

// Outbound navigation, inside the three shell sections the #84 shell already
// publishes (#79). The #229/#87 shell wiring, #76's rebuilt Adjustments, #267's
// Sell-side returns and #319's Distribution grid all landed the screens this
// issue was meant to connect - this spec is the live proof that nothing was
// left a dead end, not new screens.
//
// Seed data used throughout (seed_demo_data): a warehouse-scoped account with
// *network-wide* read (`wh.patna`, not `wh.ranchi` - the latter is scoped to
// just RAN-WH, which owns none of the stocktakes or returns this spec reaches
// into) is the role with full write access to all three sections at once.
// Transfer #3 (26-27/RAN-WH/STO/3, RAN-WH -> HZB) is dispatched and unreceived
// - the one seeded "still on the truck" - so it is the fixture for
// scan-and-receive. Stocktake #1 (HZB) is closed with a submitted session, so
// it is the fixture for the variance report. One quarantined piece
// (MF-JEAN-BLK-32 at DEO) is the fixture for the Damage/Quarantine deep link.

/** Expand a sidebar section (a no-op if it is already open), then click one of
 *  its items. Mirrors outbound-slice6-distribution-grid.spec.ts's pattern -
 *  the section head is a toggle for every persona in this spec except the
 *  store one, which draws its own single-line strip instead. */
async function openSectionItem(
  page: import("@playwright/test").Page,
  sectionCode: string,
  itemTestId: string,
) {
  const toggle = page.getByTestId(`nav-section-${sectionCode}`);
  if ((await toggle.count()) && (await toggle.getAttribute("aria-expanded")) === "false") {
    await toggle.click();
  }
  await page.getByTestId(itemTestId).click();
}

test("warehouse reaches every Transfer screen from the sidebar, scan-and-receive on a dispatched transfer, and the in-transit gaps view", async ({
  page,
}) => {
  await loginAs(page, "warehouse");

  await openSectionItem(page, "transfer", "nav-transfer-transfer");
  await expect(page).toHaveURL(/\/transfer$/);
  await expect(page.getByTestId("page-title")).toHaveText("Transfers");

  await openSectionItem(page, "transfer", "nav-transfer-new");
  await expect(page).toHaveURL(/\/transfer\/new$/);
  await expect(page.getByTestId("save-transfer-btn")).toBeVisible();

  await openSectionItem(page, "transfer", "nav-transfer-requests");
  await expect(page).toHaveURL(/\/transfer\/requests$/);
  await expect(page.getByTestId("page-title")).toHaveText("Stock Request");

  await openSectionItem(page, "transfer", "nav-transfer-in-transit");
  await expect(page).toHaveURL(/\/transfer\/in-transit$/);
  await expect(page.getByTestId("page-title")).toHaveText("In transit & gaps");
  // Gaps first: T2's shortfall was already closed in the seed, so there is
  // nothing open right now - the empty state is the honest answer, not a hole.
  await expect(page.getByTestId("gaps-empty")).toBeVisible();
  // T3 (RAN-WH -> HZB, 6+6 pcs) is the one transfer still on the road.
  await expect(page.getByTestId("transit-units")).toHaveText("12");
  await expect(page.getByTestId("transit-table")).toContainText("26-27/RAN-WH/STO/3");
  await evidence(page, "in-transit-gaps-and-on-the-road");

  // Scan-and-receive is not a sidebar item - it is an action on the transfer
  // T3's own detail page, reached from the Transfers list.
  await openSectionItem(page, "transfer", "nav-transfer-transfer");
  await page.getByTestId("transfer-tab-split").click();
  await page.getByTestId("transfer-link-3").click();
  await expect(page).toHaveURL(/\/transfer\/3$/);
  await expect(page.getByTestId("transfer-detail-back")).toBeVisible();

  const receiveBtn = page.getByTestId("receive-transfer-toggle");
  await expect(receiveBtn).toBeVisible();
  await receiveBtn.click();
  await expect(page.getByTestId("scan-screen")).toBeVisible();
  await evidence(page, "transfer-scan-and-receive-opened");
  await page.getByTestId("scan-close").click();
  await expect(page.getByTestId("scan-screen")).toBeHidden();
});

test("the store persona's Transfer strip covers its three tabs, and Send Stock stays reachable off the strip via the New transfer CTA", async ({
  page,
}) => {
  await loginAs(page, "deoManager");

  // The strip draws as one sidebar line into the section's first screen -
  // Distribution and Send Stock are deliberately not tabs on it (D10 §1).
  await page.getByTestId("nav-strip-transfer").click();
  await expect(page).toHaveURL(/\/transfer$/);

  const tabs = page.getByTestId("section-tabs");
  await expect(tabs).toBeVisible();
  await expect(page.getByTestId("section-tab-transfer")).toBeVisible();
  await expect(page.getByTestId("section-tab-requests")).toBeVisible();
  await expect(page.getByTestId("section-tab-in-transit")).toBeVisible();
  // Nothing on the store's own sidebar promises Send Stock or Distribution -
  // the full nav-transfer-* items only exist for a persona that expands the
  // section, which this one does not.
  await expect(page.getByTestId("nav-transfer-new")).toHaveCount(0);
  await expect(page.getByTestId("nav-transfer-distribution")).toHaveCount(0);

  await page.getByTestId("section-tab-requests").click();
  await expect(page).toHaveURL(/\/transfer\/requests$/);
  await page.getByTestId("section-tab-in-transit").click();
  await expect(page).toHaveURL(/\/transfer\/in-transit$/);
  await page.getByTestId("section-tab-transfer").click();
  await expect(page).toHaveURL(/\/transfer$/);

  // Send Stock, off the strip but not a dead end: the "New transfer" CTA on
  // the Transfers list still opens it, gated the same way the sidebar item
  // would have been (canWriteTransfer - a store manager holds transfer:operate).
  const newTransferBtn = page.getByTestId("new-transfer-btn");
  await expect(newTransferBtn).toBeVisible();
  await newTransferBtn.click();
  await expect(page).toHaveURL(/\/transfer\/new$/);
  await expect(page.getByTestId("save-transfer-btn")).toBeVisible();
  await evidence(page, "store-transfer-strip-and-new-transfer-cta");
});

test("warehouse reaches every Stock Count screen from the sidebar, including the Variance report inside a session", async ({
  page,
}) => {
  await loginAs(page, "warehouse");

  await openSectionItem(page, "stock_count", "nav-stock_count-stock-count");
  await expect(page).toHaveURL(/\/stock-count$/);
  await expect(page.getByTestId("page-title")).toHaveText("Count Sessions");

  // Stocktake #1 (HZB) is closed with a submitted session - the Variance
  // report is embedded in its detail page, not a sidebar item of its own.
  await page.getByTestId("count-link-1").click();
  await expect(page).toHaveURL(/\/stock-count\/1$/);
  await expect(page.getByTestId("count-detail-back")).toBeVisible();

  const varianceCard = page.getByTestId("variance-card");
  await expect(varianceCard).toBeVisible();
  await page.getByTestId("load-variance-btn").click();
  await expect(page.getByTestId("variance-table")).toBeVisible();
  await evidence(page, "stock-count-variance-report");

  await openSectionItem(page, "stock_count", "nav-stock_count-adjustments");
  await expect(page).toHaveURL(/\/stock-count\/adjustments$/);
  await expect(page.getByTestId("page-title")).toHaveText("Adjustments");

  await openSectionItem(page, "stock_count", "nav-stock_count-writeoffs");
  await expect(page).toHaveURL(/\/stock-count\/writeoffs$/);
  await expect(page.getByTestId("page-title")).toHaveText("Write-offs");
});

test("warehouse reaches every Return to Brand screen from the sidebar, and the Damage/Quarantine deep link lands correctly on Stock's own quarantine tab", async ({
  page,
}) => {
  await loginAs(page, "warehouse");

  await openSectionItem(page, "return_to_brand", "nav-return_to_brand-return-to-brand");
  await expect(page).toHaveURL(/\/return-to-brand$/);
  await expect(page.getByTestId("page-title")).toHaveText("Returns");

  await openSectionItem(page, "return_to_brand", "nav-return_to_brand-new");
  await expect(page).toHaveURL(/\/return-to-brand\/new$/);
  // The warehouse holds return_to_brand:operate, so this is the real create
  // form (Step 1's store/brand pickers) - not the "New Return" denial card a
  // view-only caller would see (proved separately in the scope-negative test).
  await expect(page.getByTestId("rtv-new-denied")).toHaveCount(0);
  await expect(page.getByText("Step 1")).toBeVisible();

  // Damage / Quarantine deep-links into Stock's own screen, owned by the
  // "stock" section rather than this one - never a placeholder covering it.
  await openSectionItem(page, "return_to_brand", "nav-return_to_brand-stock-quarantine");
  await expect(page).toHaveURL(/\/stock\?view=quarantine$/);
  await expect(page.getByText("Units quarantined")).toBeVisible();
  await expect(page.getByTestId("quarantine-table")).toBeVisible();
  await expect(page.getByTestId("quarantine-table")).toContainText("MF-JEAN-BLK-32");
  await evidence(page, "return-to-brand-quarantine-deep-link");
});

test("a role holding none of these three sections neither sees them in the sidebar nor reaches them by typing the URL", async ({
  page,
  guard,
}) => {
  // Home's own warehouse-queue widget probes `/inbound/queue` on every
  // landing, 403 included by design (InboundQueueCard.tsx's `useInboundQueue`:
  // "null = not loaded / not my screen (403)") - promo1 holds no
  // receive_goods capability at all, so this fires on login, well before this
  // spec's three sections are ever touched. Unrelated to outbound nav; declared
  // rather than left to fail the guard.
  guard.allowResponse(
    /\/inbound\/queue$/,
    "Home's queue widget probes receive_goods on every landing and treats 403 as 'not my screen' - promo1 holds no receive_goods capability",
  );

  await loginAs(page, "promo");

  // Promotions holds Home, Stock, Offers & Price and Reports only (seed
  // seed_foundation's role grants) - none of the three sections this issue
  // wired ever reach this sidebar.
  await expect(page.getByTestId("nav-section-transfer")).toHaveCount(0);
  await expect(page.getByTestId("nav-section-stock_count")).toHaveCount(0);
  await expect(page.getByTestId("nav-section-return_to_brand")).toHaveCount(0);
  await expect(page.getByTestId("nav-strip-transfer")).toHaveCount(0);

  // The URL a determined typist reaches for is refused just as plainly - kept
  // in the shell (not silently redirected), so the address bar still tells the
  // truth about where they tried to go.
  await page.goto("/transfer");
  await expect(page.getByTestId("access-denied")).toBeVisible();

  await page.goto("/stock-count");
  await expect(page.getByTestId("access-denied")).toBeVisible();

  await page.goto("/return-to-brand");
  await expect(page.getByTestId("access-denied")).toBeVisible();
  await evidence(page, "outbound-sections-scope-negative");
});

test("reloading on the Damage/Quarantine deep link keeps you on it - the tab is URL-driven, not remembered in memory", async ({
  page,
}) => {
  await loginAs(page, "warehouse");

  await openSectionItem(page, "return_to_brand", "nav-return_to_brand-stock-quarantine");
  await expect(page).toHaveURL(/\/stock\?view=quarantine$/);
  await expect(page.getByTestId("quarantine-table")).toBeVisible();

  await page.reload();

  await expect(page).toHaveURL(/\/stock\?view=quarantine$/);
  await expect(page.getByText("Units quarantined")).toBeVisible();
  await expect(page.getByTestId("quarantine-table")).toBeVisible();
  await expect(page.getByTestId("quarantine-table")).toContainText("MF-JEAN-BLK-32");
});
