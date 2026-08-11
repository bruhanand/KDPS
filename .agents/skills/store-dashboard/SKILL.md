---
name: store-dashboard
description: >
  Generate the KDPS monthly store business dashboard (all 16 measures) from a store's
  sales + stock-on-hand Excel exports, as a house-style HTML + PDF. Use when the user
  wants to build, refresh, or produce a store dashboard / monthly store report / store
  business health-check, or analyse a KDPS store's sales and stock. Trigger on phrases
  like "store dashboard", "refresh the JSL dashboard", "monthly store report", "run the
  dashboard for <store>".
---

# store-dashboard

Turns a KDPS store's monthly POS exports into the standard **16-measure business dashboard**
in the house navy/gold style (HTML + PDF). The analysis logic is frozen in `generate.py`, so
each month is just **drop the export → run**.

**The 16 measures:** 1 staff productivity · 2 average bill value · 3 repeat/new customers ·
4 month-on-month P&L · 5 dead stock · 6 fast-moving · 7 stock turnover · 8 ageing ·
9 out-of-stock · 10 item-wise · 11 gender-wise · 12 top-20 brands · 13 size analysis ·
14 accessories · 15 discount · 16 margin. (Two can't be done from POS data — see Caveats.)

## How to run

1. **Find the store folder.** Stores live under `docs/data-from-kdps/store-analysis/<store>/`.
   Resolve the user's store (e.g. "JSL") to that folder (case-insensitive). If they gave a full
   path, use it. If unclear, ask which store.

2. **Make sure the exports are in the folder.** It needs at least one **sales** export (a sheet with
   `Bill No`, `Item`, `Net Amount` columns) and one **stock-on-hand** export (a sheet with
   `Item Name`, `Tqty`). Multiple sales files (e.g. one per financial year) are fine — the engine
   auto-detects the right sheet in each workbook and de-duplicates overlapping bills. If a file is
   sitting in `~/Downloads`, copy it into the store folder first.

3. **Set up Python deps once** (venv lives in this skill folder):
   ```bash
   cd .agents/skills/store-dashboard
   [ -d .venv ] || python3 -m venv .venv
   .venv/bin/pip install -q -r requirements.txt
   ```

4. **Run the engine** on the store folder:
   ```bash
   .venv/bin/python generate.py <absolute-path-to-store-folder>
   ```
   Add `--no-pdf` to skip the PDF. Output is written **into the store folder** as
   `<CODE>-Dashboard.html` and `.pdf`.

5. **Report back**: the one-line summary the script prints (period, net sales, profit %, margin,
   turnover) and the paths to the HTML + PDF. Optionally read the first PDF page to eyeball the render.

## Per-store config (`dashboard-config.json` in the store folder)

Holds the numbers that aren't in the data. Minimal example:
```json
{ "store_name": "JSL Store", "store_code": "JSL", "region": "Bihar / Jharkhand",
  "costs": { "variable_pct_of_sales": 7, "rent": 220000, "electricity": 100000, "misc": 40000 },
  "discount_ceiling_pct": null, "soh_as_on": "2026-06-30" }
```
- `costs` → the P&L running-cost formula (variable % of sales + fixed rent/power/misc per month).
- `discount_ceiling_pct` → `null` means "use the break-even discount" (derived from cost vs MRP).
- `soh_as_on` → the stock snapshot date, used for stock ageing.
- Brand-alias and category-merge maps have sensible KDPS defaults in `generate.py`; override in the
  config only if a store uses different codes.

## What the engine handles automatically (KDPS data quirks)

- Drops the **hidden grand-total row** in the stock file (else every total doubles).
- Excludes **carry bags** (packaging, not merchandise).
- Merges **brand aliases** (LP/LY/LR → Louis Philippe, VH/VS/VD → Van Heusen, etc.).
- Treats the sales **"Colour" column as a price band** (it is not a real colour).
- Matches every sold item to its **cost in the stock file** to estimate margin, P&L and profit.
- De-duplicates bills across multiple sales files; fills down bill-level fields.

## Caveats to state in the output (already written into the report footer)

- **Profit/margin are estimates** — the sales export has no cost column (cost comes from the stock file).
- **No true conversion rate** (needs footfall data) — only repeat-vs-new customers.
- **No colour analysis** (the "Colour" field is a price band; stock has no colour).
- **Dead stock** = not sold within the months of data supplied.

## If it errors

The engine **stops with a clear message** rather than produce wrong numbers. Most likely cause: the
POS export format changed (a renamed/missing column). Fix the export to match, or update the column
lists (`SALES_COLS` / `SOH_COLS`) and mappings in `generate.py`.

## Note

This is the bridge to the ERP: the same 16 metric definitions become the live analytics-module
screens later. Keep the metric logic here and in the ERP in sync.
