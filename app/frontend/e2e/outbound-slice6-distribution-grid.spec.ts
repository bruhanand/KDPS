import { evidence, expect, expectCall, loginAs, test } from "./kdps";

// Distribution grid (#73): warehouse to store allocation. A warehouse person
// picks a source warehouse and destination stores, adds arrived SKUs, and the
// grid groups them into style rows with a per-store qty cell and a warehouse
// "buffer" cell, pre-filled from a suggested split. Confirm bulk-creates one
// draft `store_split` transfer per destination store - still unapproved, still
// blocked from dispatch until the Operations Head clears it (#137), and the
// grid itself never touches the stock ledger.
//
// Seed data used throughout (seed_demo_data, RAN-WH warehouse): "Oxford Shirt"
// (Louis Philippe, LP-OXF-BLU-40, Blue 40, qty 24) and "Pique Polo" (Peter
// England, PE-PLO-GRN-L, Green L, qty 19) are each the only SKU under their
// design, so a search term unique to the design name returns exactly one row.
// RAN-WH, DEO and BKR are all Jharkhand (same GSTIN), so this spec never has
// to also exercise the e-way-bill prompt to get through the flow.

const API_BASE = process.env.KDPS_BACKEND_URL ?? "http://localhost:8001";

/** Login as the warehouse person who owns RAN-WH, land on the grid, pick the
 *  warehouse as source and the given store codes as destinations. */
async function toStep3(page: import("@playwright/test").Page, destCodes: string[]) {
  await loginAs(page, "warehouseRanchi");
  await page.goto("/transfer/distribution");
  await page
    .getByTestId("distribution-source-select")
    .selectOption({ label: "RAN-WH · Ranchi Central Warehouse" });
  for (const code of destCodes) {
    await page.getByTestId(`distribution-dest-${code}`).click();
  }
}

/** Search for `term` and add the one result it returns - the search box
 *  really calls stock-search, and adding a fresh style really calls the
 *  suggested-split endpoint for its pre-fill, so both are asserted, not
 *  assumed. */
async function addSku(page: import("@playwright/test").Page, term: string) {
  await page.getByTestId("distribution-sku-search").fill(term);
  await expectCall(page, /outbound\/stock-search/, async () => {
    await page.getByTestId("distribution-sku-search-btn").click();
  });
  const result = page.locator('[data-testid^="distribution-result-"]').first();
  await expect(result).toBeVisible();
  const addBtn = result.locator('[data-testid^="distribution-add-"]');
  await expectCall(page, /distribution\/suggested-split/, async () => {
    await addBtn.click();
  });
}

test("wh.ranchi reaches the grid from the sidebar and sees the suggested split pre-filled, with a live buffer column", async ({
  page,
}) => {
  await loginAs(page, "warehouseRanchi");

  // Reachable from the sidebar, not just a URL - Transfer → Distribution.
  const sectionToggle = page.getByTestId("nav-section-transfer");
  if ((await sectionToggle.count()) && (await sectionToggle.getAttribute("aria-expanded")) === "false") {
    await sectionToggle.click();
  }
  await page.getByTestId("nav-transfer-distribution").click();
  await expect(page).toHaveURL(/\/transfer\/distribution$/);

  await page
    .getByTestId("distribution-source-select")
    .selectOption({ label: "RAN-WH · Ranchi Central Warehouse" });
  await page.getByTestId("distribution-dest-DEO").click();
  await page.getByTestId("distribution-dest-BKR").click();
  await addSku(page, "Oxford");

  const style = page.getByTestId("distribution-style-Oxford Shirt");
  await expect(style).toBeVisible();
  await expect(page.getByTestId("distribution-grid-table")).toContainText("Buffer");

  // No dispatch history for this brand+store pair, so the documented fallback
  // is an even split across the two picked stores (24 / 2 = 12 each) with
  // nothing left over for the buffer.
  const qtyInputs = page.locator('[data-testid^="distribution-qty-LP-OXF-BLU-40-"]');
  await expect(qtyInputs).toHaveCount(2);
  await expect(qtyInputs.nth(0)).toHaveValue("12");
  await expect(qtyInputs.nth(1)).toHaveValue("12");
  const bufferInput = page.getByTestId("distribution-buffer-LP-OXF-BLU-40");
  await expect(bufferInput).toHaveValue("");

  // The buffer cell is a real, live-editable column, not a static label: move
  // 3 pieces from the second store into the buffer and the style row's own
  // Buffer and Allocated totals roll with it, while total allocation still
  // reads exactly what's available (24), not over.
  await qtyInputs.nth(1).fill("9");
  await bufferInput.fill("3");
  const numCells = style.locator("td.num");
  await expect(numCells.nth(0)).toHaveText("24"); // Available
  await expect(numCells.nth(3)).toHaveText("3"); // Buffer total
  await expect(numCells.nth(4)).toContainText("24"); // Allocated
  await expect(numCells.nth(4).locator("b")).not.toHaveAttribute("style");

  await evidence(page, "distribution-grid-prefilled-with-buffer");
});

test("a style's size and colour breakup opens and collapses inside its row", async ({ page }) => {
  await toStep3(page, ["DEO"]);
  await addSku(page, "Oxford");

  const line = page.getByTestId("distribution-line-LP-OXF-BLU-40");
  await expect(line).toBeVisible(); // a freshly-added style opens expanded
  await expect(line).toContainText("Blue");
  await expect(line).toContainText("40");

  await evidence(page, "distribution-style-expanded");

  await page.getByTestId("distribution-style-toggle-Oxford Shirt").click();
  await expect(line).toBeHidden();

  await page.getByTestId("distribution-style-toggle-Oxford Shirt").click();
  await expect(line).toBeVisible();
});

test("a line that would exceed available stock turns red immediately and blocks Create transfers", async ({
  page,
  guard,
}) => {
  await toStep3(page, ["DEO", "BKR"]);
  await addSku(page, "Polo"); // Pique Polo, PE-PLO-GRN-L, qty 19

  const line = page.getByTestId("distribution-line-PE-PLO-GRN-L");
  const lineTotal = line.locator("td.num b");
  await expect(lineTotal).not.toHaveAttribute("style");

  const qty0 = page.locator('[data-testid^="distribution-qty-PE-PLO-GRN-L-"]').first();
  await qty0.fill("999");

  await expect(lineTotal).toHaveAttribute("style", /--red/);
  const styleTotal = page.getByTestId("distribution-style-Pique Polo").locator("td.num b");
  await expect(styleTotal).toHaveAttribute("style", /--red/);

  await evidence(page, "distribution-over-allocation-red");

  await page.getByTestId("distribution-submit").click();
  await expect(page.getByTestId("distribution-error")).toContainText("exceeds available");
  await expect(page.getByTestId("distribution-outcome")).toHaveCount(0);
  expect(guard.requests().some((r) => r.method === "POST" && /outbound\/transfers/.test(r.url))).toBe(
    false,
  );
});

test("Confirm creates one draft transfer per destination store with the grid's lines", async ({ page }) => {
  await toStep3(page, ["DEO", "BKR"]);
  await addSku(page, "Oxford"); // qty 24, even split -> 12 / 12

  await expectCall(page, /outbound\/transfers/, async () => {
    await page.getByTestId("distribution-submit").click();
  });

  const outcome = page.getByTestId("distribution-outcome");
  await expect(outcome).toBeVisible();
  const deoRow = page.getByTestId("distribution-outcome-DEO");
  const bkrRow = page.getByTestId("distribution-outcome-BKR");
  await expect(deoRow).toBeVisible();
  await expect(bkrRow).toBeVisible();
  await evidence(page, "distribution-confirm-outcome");

  const deoId = (await deoRow.innerText()).match(/Draft #(\d+)/)?.[1];
  const bkrId = (await bkrRow.innerText()).match(/Draft #(\d+)/)?.[1];
  expect(deoId, "DEO outcome should read as an unposted draft").toBeTruthy();
  expect(bkrId, "BKR outcome should read as an unposted draft").toBeTruthy();

  for (const [id, storeCode] of [
    [deoId, "DEO"],
    [bkrId, "BKR"],
  ] as const) {
    const resp = await page.request.get(`${API_BASE}/api/outbound/transfers/${id}`);
    expect(resp.ok()).toBe(true);
    const doc = await resp.json();
    expect(doc.docstatus).toBe(0);
    expect(doc.destination_store_code).toBe(storeCode);
    expect(doc.source_store_code).toBe("RAN-WH");
    expect(doc.transfer_type).toBe("store_split");
    expect(doc.lines).toHaveLength(1);
    expect(doc.lines[0]).toMatchObject({ sku_code: "LP-OXF-BLU-40", qty_planned: 12 });
  }
});

test("the created transfers are unapproved drafts and cannot be dispatched", async ({ page }) => {
  await toStep3(page, ["DEO"]);
  await addSku(page, "Oxford");

  await expectCall(page, /outbound\/transfers/, async () => {
    await page.getByTestId("distribution-submit").click();
  });
  const outcomeText = await page.getByTestId("distribution-outcome-DEO").innerText();
  const id = outcomeText.match(/Draft #(\d+)/)?.[1];
  expect(id).toBeTruthy();

  await page.getByTestId("distribution-view-transfers").click();
  await expect(page).toHaveURL(/\/transfer$/);
  await page.getByTestId("transfer-tab-split").click(); // WH → store drafts live under this tab
  await page.getByTestId(`transfer-link-${id}`).click();

  // Land on the detail page proper before reading its text - the list row
  // this link came from shows the same "Draft" / "Waiting" chips, so asserting
  // on a marker unique to the detail screen first is what keeps the checks
  // below from racing the list's own copies of that text during navigation.
  await expect(page.getByTestId("transfer-detail-back")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/transfer/${id}$`));

  // Both the toolbar's ApprovalPill and the approval trail below it say
  // "Waiting" - the same fact told twice, not ambiguity worth resolving further.
  await expect(page.getByText("Waiting", { exact: true }).first()).toBeVisible();
  await expect(page.getByTestId("dispatch-transfer-btn")).toHaveCount(0); // canDispatch requires docstatus 0 + approved

  await evidence(page, "distribution-draft-unapproved-detail");
});

test("the grid itself writes no ledger entries", async ({ page }) => {
  await toStep3(page, ["DEO", "BKR"]);

  const before = await page.request.get(
    `${API_BASE}/api/stockledger/on-hand?store=RAN-WH&sku=LP-OXF-BLU-40`,
  );
  const beforeQty = (await before.json()).summary.units_on_hand;
  expect(beforeQty).toBeGreaterThan(0);

  await addSku(page, "Oxford");
  await expectCall(page, /outbound\/transfers/, async () => {
    await page.getByTestId("distribution-submit").click();
  });
  await expect(page.getByTestId("distribution-outcome")).toBeVisible();

  const after = await page.request.get(
    `${API_BASE}/api/stockledger/on-hand?store=RAN-WH&sku=LP-OXF-BLU-40`,
  );
  const afterQty = (await after.json()).summary.units_on_hand;
  expect(afterQty).toBe(beforeQty); // planning surface only - nothing moved
});

test("a store-scoped user cannot raise a distribution out of a warehouse they don't own", async ({
  page,
}) => {
  await loginAs(page, "deoManager");
  await page.goto("/transfer/distribution");

  const select = page.getByTestId("distribution-source-select");
  await expect(select).toBeVisible();
  // DEO's own scope holds no warehouse, so /masters/stores comes back
  // filtered to just their own store - the dropdown has nothing but its
  // placeholder, and a store-scoped user cannot even pick a source, let
  // alone raise a transfer out of RAN-WH.
  await expect(select.locator("option")).toHaveCount(1);
  await expect(select.locator("option").first()).toHaveText("Select warehouse…");

  await evidence(page, "distribution-scope-negative-no-warehouse");
});

test("reloading the grid resets its in-memory plan, but the drafts it already created persist", async ({
  page,
}) => {
  await toStep3(page, ["DEO"]);
  await addSku(page, "Oxford");
  await expectCall(page, /outbound\/transfers/, async () => {
    await page.getByTestId("distribution-submit").click();
  });
  const outcomeText = await page.getByTestId("distribution-outcome-DEO").innerText();
  const id = outcomeText.match(/Draft #(\d+)/)?.[1];
  expect(id).toBeTruthy();

  await page.reload();
  await expect(page.getByTestId("distribution-source-select")).toHaveValue("");
  await expect(page.getByTestId("distribution-grid-table")).toHaveCount(0);
  await expect(page.getByTestId("distribution-outcome")).toHaveCount(0);

  // The plan was only ever client state, but the drafts it posted are real
  // rows - the reload does not take them with it.
  await page.getByTestId("distribution-back-link").click();
  await page.getByTestId("transfer-tab-split").click();
  await expect(page.getByTestId(`transfer-row-${id}`)).toBeVisible();
});
