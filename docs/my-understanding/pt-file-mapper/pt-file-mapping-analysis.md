> **Superseded (1 Jul 2026) → see [`pt-mapper-engine-build.html`](pt-mapper-engine-build.html).**
> This analysis was sound on the *target format* and the *archetype* idea, but it described the
> mapper as software-to-build. The engine was in fact already built (Django app `ptmapper`) and
> was simply **under-fed** (sparse lookup tables) and **missing profiles** for archetypes D/E/F.
> The HTML doc has the corrected diagnosis (an audit harness quantified each field), the fix that
> was shipped (size/colour normalisers, 274 colour aliases, 125 taxonomy rules, profiles D/E/F,
> layered resolver), and measured before/after fill rates. Read that for current state.

# PT File Mapper — Brand → KDPS Format Mapping

**What this is.** A build specification for the software that converts each brand's "PT file" (the item/price file the brand sends with a consignment) into KDPS's single in-house PT format. **No AI, no agents** — this is deterministic, table-driven column mapping with a human review queue for anything the tables don't yet cover.

**Inputs analysed**

- **KDPS target format** — `docs/data-from-kdps/KDPS PT FILE SHEET.xlsx` (the "Work Sheet" layout + the "Master Sheet" of allowed values).
- **Blank target template** — `docs/data-from-kdps/05-reference-data/pt-file-format.xlsx` (same layout, empty).
- **33 real brand PT files** — `docs/data-from-kdps/Q&A-req-recieved/PT FILE/`.

> One-line summary of the finding: **~60–70% of every brand file maps to KDPS by a plain column rename** (barcode, HSN, qty, MRP, size, rate). The hard 30% is KDPS's own **merchandising taxonomy** (Season, Sub-Category, Type, Item, Fit, Gender, Colour) which the brand files do **not** carry in KDPS's words — that part needs **lookup tables that grow over time + a review queue**, not code changes per file.

---

## 1. The KDPS target — what every brand must become

Each output row = **one SKU line** = one barcode = Style × Colour × Size. The "Work Sheet" header (row 2 of each worksheet) is:

| # | KDPS column | What it holds | How it is filled |
|---|---|---|---|
| 1 | **SEASON** | One of 22 allowed labels: `SPRING SUMMER(Mon-YY)` / `AUTUMN WINTER(Mon-YY)` | **Derived** from invoice date or the brand's own season code, mapped to KDPS label |
| 2 | **BRAND** | One of ~592 brands in the master | **Normalised** from the brand field / filename to the KDPS brand name |
| 3 | **COLOR** | One of ~23 KDPS buckets | **Normalised** from the brand's shade (see §6, anomaly) |
| 4 | **GENDER** | MALE / FEMALE / KIDS MALE / KIDS FEMALE / UNISEX | **Derived** via lookup from brand category/gender |
| 5 | **SUB CATEGORY** | 9 values (CASUAL WEAR, FORMAL WEAR, INNERWEAR, …) | **Derived** via category lookup |
| 6 | **TYPE** | 7 values (TOP WEAR, BOTTOM WEAR, FULL SET, …) | **Derived** via category lookup |
| 7 | **ITEM** | 98 values (T-SHIRT, JEANS, BRIEF, …) | **Derived** from item description |
| 8 | **FIT** | 75 values (SLIM, REGULAR, BOXER, …) | **Derived** from description / brand fit field |
| 9 | **SIZE** | 135 values (XS…5XL, numeric, age `5-6 Y`, …) | **Normalised** from the brand's size string |
| 10 | **BARCODE** | EAN / barcode | **Direct copy** |
| 11 | **DESIGN** | Style/design code + name (e.g. `SQI-RN-26193`, `10005-Assorted`) | **Direct / concatenated** from style code + description |
| 12 | **HSN** | HSN code | **Direct copy** |
| 13 | **QTY** | Pieces on this line | **Direct copy** (sum if line is split) |
| 14 | **MRP** | Printed MRP | **Direct copy** |
| 15 | **BASIC** | Per-unit base/taxable cost | **From brand cost column** (see §5 — money-critical) |
| 16 | **P RATE** | Per-unit purchase rate KDPS books | **From brand cost column / loading** (see §5) |
| 17 | **INPUT TAX** | GST % on purchase | **Direct** from brand tax-rate |
| 18 | **OUTPUT TAX** | GST % on sale | **Usually = INPUT TAX** |
| 19 | **NAG** | Number of garments | **= QTY** (confirmed in worked sheets) |
| 20 | **MARGIN** | % margin | **Computed** = `(MRP − P RATE) / MRP × 100` (confirmed) |
| (21–22) | SUGGESTED SUB CATEGORY / TYPE | Helper alt-taxonomy columns | Optional, from a second lookup |

**Derived-field formulas confirmed against KDPS's own worked rows** (the `…Work Sheet` tabs already filled by staff):

```
NAG    = QTY
MARGIN = (MRP − P RATE) / MRP × 100        e.g. (549 − 325.116)/549 = 40.78 %
                                           e.g. (1399 − 1091.22)/1399 = 22.0 %
INPUT TAX = OUTPUT TAX = brand GST %        (occasional staff mismatch seen — validate)
```

**The "Master Sheet"** is KDPS's controlled vocabulary — the dropdown lists behind every derived column. It is the seed for the lookup tables the mapper needs:

- SEASON (22) · GENDER (5) · SUB CATEGORY (9) · TYPE (7) · ITEM (98) · FIT (75) · COLOR (23) · SIZE (135) · GST % (5 / 12 / 18 / TAX FREE) · BRAND (592).

---

## 2. The core idea — brand files cluster into ~6 archetypes

The 33 files are **not** 33 unique formats. They come from a handful of retail ERPs, so they cluster. **You build one mapping profile per archetype, then small per-brand overrides** — not 40 separate programs.

| Archetype | Origin / look | Header row | Brands (files) in this study |
|---|---|---|---|
| **A — Simple item list** | A clean item master; already close to KDPS | row 0 | AMIDHARA, DSY, kidcity, minelli, peppermint, XERICS, ZILU BOTTOMS, Madura (.xlsb) |
| **B — Tally / Vistaar sales voucher** | "Voucher No/Date/Party… Stock No, Product, Brand, Style, Shade, Size, Sales Qty, Retail Price, Item Rate, Season" | row 4–5 (banner rows above) | ARVIND & SPYKAR, BK ENTERPRISES, DEAL, BANJARAN, STATUS QUO, TWILLS |
| **C — Ginesys "PT EMAIL _Dont touch"** | ABFRL distributor export: `OWNER SITE, BARCODE, CATEGORY1-5, DIVISION/SECTION/DEPARTMENT, TAX_RATE, INVOICE_RATE, INVOICE_RSP, MRP` | row 2 | BEEVEE, MUFTI, go colours, HYPHEN |
| **D — Jockey / Page SAP export** | "Bill Date, Tran Type, StockNo, Product/Range/Style/Colour Code, Cost, MDP, Doc Rate, Qty, Tax" | row 0 or row 8 | JOCKEY 852, JOCKEY PARAS, JOCKEY-NARAYANI, JOCKEY-NARVADA, JOCKEY_DD SALES, JOCKEY.xlsx |
| **E — Branded-house wide SAP** | 40–56 columns, lots of GST/logistics noise; pick a subset | row 0 (or headerless) | BLACKBERRY, Peter England (.CSV), USPOLO (headerless .csv) |
| **F — Printed-invoice .xls** | A formatted invoice with title/address banner; item table starts deep in the sheet | row 9–15 | AS INNERWEAR (mislabelled .csv), ambreli, 36257 SUVIDHI, FAHRENHEIT, SWEET DREAMS, KILLER JUNIOR |

**Why this matters for the build:** Archetypes B, C, D cover ~18 of the 33 files and share most columns. Solve those three profiles well and the bulk of volume is done. Archetype F (printed invoices) is the messy long tail — handle it last, with anchored header detection.

---

## 3. How the software works — 7 stages

```
brand file ─▶ (1) IDENTIFY ─▶ (2) LOCATE TABLE ─▶ (3) COLUMN MAP ─▶
              (4) NORMALISE VALUES ─▶ (5) DERIVE FIELDS ─▶ (6) VALIDATE ─▶ (7) WRITE KDPS ROWS
                                                                │
                                                                └─▶ unresolved values ─▶ REVIEW QUEUE
```

**(1) Identify the brand / profile.** Two signals, in order:
- **Filename keyword** (`JOCKEY*`, `MUFTI*`, `BEEVEE*` → known profile), else
- **Header fingerprint** — the set of column names in the detected header row matches an archetype signature (e.g. presence of `OWNER SITE`+`CATEGORY1`+`INVOICE_RSP` ⇒ Archetype C). This makes new files from a known ERP auto-route even with a new brand name.

**(2) Locate the header row & data range.** Files have 0–15 banner rows. Detect the header by scoring each of the first ~12 rows against a keyword set (`barcode, size, mrp, qty, hsn, style, rate, …`); the highest-scoring row is the header. Data runs until the first fully-blank row or a "Total/Grand Total" row. (This is already prototyped in the analysis script and works on all 33 files.)

**(3) Column map (declarative, per profile).** A table: `KDPS column ← source column (by name or index)`. No code per brand — just config. Example (Archetype C):

```yaml
profile: ginesys_pt_email          # BEEVEE, MUFTI, go colours, HYPHEN
header_row: detect
map:
  BARCODE:    BARCODE
  HSN:        HSN CODE
  QTY:        INVOICE_QUANTITY
  NAG:        =QTY
  MRP:        MRP
  P RATE:     INVOICE_RATE          # per-unit cost
  BASIC:      "=TAXABLE_AMOUNT / INVOICE_QUANTITY"
  INPUT TAX:  TAX_RATE
  OUTPUT TAX: =INPUT TAX
  DESIGN:     CATEGORY2             # style code
  COLOR:      lookup(color, CATEGORY3)
  SIZE:       lookup(size, CATEGORY4)
  ITEM:       lookup(item, DEPARTMENT or CATEGORY5)
  BRAND:      lookup(brand, CATEGORY1 or filename)
  SEASON:     derive_season(INVOICE_DATE)
  GENDER/SUB CATEGORY/TYPE/FIT: lookup(taxonomy, DIVISION+SECTION+DEPARTMENT)
  MARGIN:     "=(MRP − P RATE)/MRP*100"
```

**(4) Normalise values via lookup tables** (the heart of the work — see §4).

**(5) Derive fields** — SEASON, NAG, MARGIN, INPUT/OUTPUT TAX as above.

**(6) Validate** — every derived KDPS column must resolve to a value that exists in the Master Sheet. If a brand size `1.02M(L)` or category `INDO WESTERN SET` doesn't resolve, **don't guess** — write the row with the field blank and push the unresolved `(field, raw value, brand)` to a **review queue**. A human adds one lookup entry; the mapper re-runs and now knows it forever.

**(7) Write KDPS rows** — append to the Work Sheet layout (or a CSV/XLSX in that shape).

---

## 4. The lookup tables (the real product)

These tables — not the parser — are what make the mapper correct. They are **data, edited by KDPS staff**, not code. Seed them from the Master Sheet + the brand files, then grow via the review queue.

| Table | Key (brand raw value) → | Value (KDPS) | Examples |
|---|---|---|---|
| **size_map** | brand size string | KDPS SIZE | `XL (105 CMS)`→`XL`; `36/XS`→`XS`; `5-6 Y`→`5-6 Y`; `1.02M(L)`→`L`; `96CM(M)`→`M` |
| **color_map** | brand shade | KDPS COLOR | `LIGHT BLUE`→`BLUE`; `INDIGO MEL`→`BLUE`; `TNAVY`→`NAVY`; `MUSTARD`→`YELLOW`(?) |
| **brand_map** | brand alias | KDPS BRAND | `Blackberrys`→`BLACKBERRY`; `GO COLORS`→`GO COLOURS`; `FM`→`FLYING MACHINE`; `PJ`→`PETER ENGLAND` |
| **taxonomy_map** | brand category/dept/desc keyword | (GENDER, SUB CATEGORY, TYPE, ITEM, FIT) | `MENS TRACK PANT`→(MALE, SPORTS WEAR, BOTTOM WEAR, JOGGER, REGULAR); `KIDS SAREE`→(KIDS FEMALE, PARTY WEAR, ONE-PIECE, SAREE, ETHNIC) |
| **season_rule** | invoice month / brand season code | KDPS SEASON | `2026-03-24`→`SPRING SUMMER(Mar-26)`; `AW24`→`AUTUMN WINTER(...)` |
| **hsn / gst** | (pass-through; GST sanity-checked against HSN) | INPUT/OUTPUT TAX | 5 / 12 / 18 |

**taxonomy_map is the biggest.** The brand files describe an item in their own words (`Item Description`, `Product`, `CATEGORY1-5`, `Group Category`, `Section/Department`). KDPS has its own 5-axis merchandising grid (Gender × Sub-Category × Type × Item × Fit). Mapping `"DEAL WOMAN STRAIGHT JEANS"` → `(FEMALE, CASUAL WEAR, BOTTOM WEAR, JEANS, REGULAR)` is a **business decision KDPS makes once per pattern** and the table remembers. Start with keyword rules (`*JEANS*`→ITEM JEANS, `*BRIEF*`→ITEM BRIEF) and let the review queue fill the gaps.

---

## 5. Money-critical: BASIC, P RATE, MARGIN  ⚠️ confirm with finance/CA

This is the one place to be careful — it touches cost and margin, which the project treats as **CA-gated**.

**Observed in KDPS's own worked rows:**

| Brand row | MRP | BASIC | P RATE | GST | MARGIN | P RATE / BASIC |
|---|---|---|---|---|---|---|
| TOMBOY shorts | 549 | 295.56 | 325.116 | 5 | 40.78 | 1.10 |
| LEVIS jeans | 4799 | 2805.90 | 3367.08 | 18 | 29.84 | 1.20 |
| FLYING MACHINE tee | 1399 | 909.35 | 1091.22 | 5 | 22.00 | 1.20 |
| VAN HEUSEN brief | 319 | 227.86 | 273.432 | 5 | 14.28 | 1.20 |

**What is solid:**
- `MARGIN = (MRP − P RATE) / MRP × 100` — holds on every row.
- `P RATE` is the per-unit cost KDPS books; `BASIC` is a lower per-unit base cost.

**What is NOT a fixed formula (needs a rule per brand/commercial term):**
- The `P RATE / BASIC` loading is **1.10 for TOMBOY but 1.20 for the rest** — it is **not** the GST rate (VAN HEUSEN is GST 5 yet loaded 1.20). It is a KDPS commercial loading that varies by brand/terms.
- In the wide brand files, `BASIC` and `P RATE` are usually **two different existing columns**, e.g. DEAL has both `Item Rate` (1448.31) and `Purchase Price` (1346.93); Peter England has `Net Unit Cost` and `Unit Cost`; Jockey has `Cost`, `MDP`, and `Doc Rate`. So per profile we map BASIC and P RATE to the **right two source columns** rather than computing one from the other.

**Action:** before the mapper posts cost, get KDPS finance to confirm, per archetype, **which source column is BASIC and which is P RATE**, and whether any loading is applied. Until then, carry both raw source numbers through and flag.

---

## 6. Known traps (found in the real files)

1. **COLOR is used loosely.** KDPS's COLOR list contains `PREMIUM`, `ECONOMY`, `MEDIUM` — these are **price tiers, not colours**, and worked rows show `COLOR = PREMIUM`. So KDPS's COLOR field is sometimes a tier, sometimes a real shade. Decide the rule (true colour vs tier) before mapping; otherwise colour normalisation is ambiguous.
2. **Mislabelled extensions.** `AS INNERWEAR.csv` and `USPOLO INNER WEAR.csv` are **not CSV** — AS INNERWEAR is an OLE `.xls`, USPOLO is a real CSV but **headerless** (positional columns). `TWILLS.xls` is actually an `.xlsx`. Detect by file magic bytes, not extension.
3. **Banner / printed-invoice rows.** Archetype F files put the item table at row 9–15 under an address block, and add `Total` rows at the bottom — the data-range detector must skip both.
4. **Multi-sheet files.** `AMIDHARA.xlsx` has two brand sheets (`ANOKHI`, `AMIDHARA`); `ambreli` has `INVOICE` + `PACKING`. Profile must say which sheet (or all) to read.
5. **One style, many size rows.** Every file is already exploded to one row per barcode/size — good, that matches KDPS. Don't re-aggregate.
6. **Size strings are wild:** `XL (105 CMS)`, `L (1 MTR.)`, `36/XS`, `96CM(M)`, `1.02M(L)`, `10-11 YEARS`, `FS`, `FREE`. The size_map must cover unit-suffixed, slash-dual, and age formats.
7. **INPUT ≠ OUTPUT tax** occasionally in staff sheets (e.g. a `5 / 18` row) — treat as a validation warning, default OUTPUT = INPUT unless a rule says otherwise.
8. **Season is rarely in the file** in KDPS's label form. Some give a code (`SS26`, `AW24`); most give only an invoice date. Derive from date by default.

---

## 7. Per-file index (all 33)

| File | Archetype | Header row | Key source columns | Notes |
|---|---|---|---|---|
| 36257 KDPS SUVIDHI.xls | F | 0 | Item Code, ITEM NAME, PACK/SIZE, TOTAL QTY, SALE RATE, M.R.P. | barcode in Item Code; size embedded in PACK/SIZE |
| AMIDHARA.xlsx | A | 0 | Barcode, Item Code, Category, Color, Size, Quantity, MRP, HSN | 2 sheets (ANOKHI, AMIDHARA) |
| ARVIND ALL BRAND & SPYKAR_PT.xlsx | B | 4 | Stock No, Product, Brand, Style, Shade, Size, Sales Qty, Retail Price, Item Rate, HSN, Season | 4 banner rows |
| AS INNERWEAR.csv | F | 15 | HSN, Particulars, MRP, Qty, Rate, Barcode | really `.xls`; printed invoice |
| BANJARAN.xlsx | B | 0 | Supplier Barcode, Item Name, Net Rate, Retail Rate, Size, Colour, HSN | many empty attribute cols |
| BEEVEE 390.xlsx | C | 2 | BARCODE, CATEGORY2-5, INVOICE_RATE, INVOICE_RSP, MRP, TAX_RATE, HSN | Ginesys PT EMAIL |
| BK ENTERPRISES_LC_PT.xlsx | B | 4 | Stock No, Product, Brand, Style, Shade, Size, Item Rate, Retail Price, HSN, Season | |
| BLACKBERRY.xlsx | E | 0 | EANCODE, STYLE, COLOUR, SIZES, FIT, UNIT MRP, COST PER UNIT, HSN, ARTICLE SEASON | 41 cols, has FIT! |
| DEAL SS26 2970.xlsx | B | 4 | Stock No, Product, Brand, Style, Shade, Size, Item Rate, Purchase Price, Total Value (MRP), HSN, Season | BASIC vs P RATE both present |
| DSY.xlsx | A | 0 | Barcode, ITEM NAME, BRAND, SIZE, QTY, MRP, RATE, HSN, CATEGORY, GENDER | has GENDER |
| FAHRENHEIT 60518.xls | F | 0 | Item Code, ITEM NAME, PACK/SIZE, TOTAL QTY, SALE RATE, M.R.P, HSN | size in PACK/SIZE |
| go colours 000023.xlsx | C | 2 | BARCODE, CATEGORY2-5, INVOICE_RATE, INVOICE_RSP, MRP, TAX_RATE, HSN | Ginesys PT EMAIL |
| HYPHEN.xlsx | C | 2 | BARCODE, STYLE, SIZE, MRP, RSP, INVOICE_RATE, HSN, SECTION, DEPARTMENT | Ginesys variant |
| JOCKEY 852.xls | D | 8 | StockNo, Style/Colour Code, Size, Cost, MDP, Doc Rate, Qty, Tax Perc. | |
| JOCKEY PARAS.xls | D | 8 | StockNo, Product/Range/Style/Colour Code, Size, HSN, Cost, MDP, Doc Rate, Qty | 39 cols |
| JOCKEY-NARAYANI.xls | D | 0 | StockNo, Style/Colour Code, Size, HSN, Cost, MDP, Doc Rate, Qty | header at row 0 |
| JOCKEY-NARVADA.xls | D | 8 | StockNo, Style/Colour Code, Size, HSN, MDP, Doc Rate, Qty | no Cost col |
| JOCKEY.xlsx | F/A | 1 | STOCK NO., STYLE CODE, COLOUR, SIZE, QTY, MRP, RATE, HSN | hand-made simple |
| JOCKEY_DD SALES.xls | D | 8 | StockNo, Style/Colour Code, Size, HSN, Cost, MDP, Doc Rate, Qty | |
| KILLER JUNIOR.xlsx | F | 2 | BARCODE, ITEM NAME, SHADE, SIZE, TOTAL QTY, M.R.P., RATE/UNIT, HSN | age sizes (10-11 YEARS) |
| Madura Fashion … .xlsb | A/E | 0 | EAN/UPC, Generic Material, Size 1, HSN, Billed Quantity, MRP, NET Value | binary `.xlsb` |
| minelli 06161.xlsx | A | 0 | BarCode, Brand, Style, Shade, Size, MRP, DP, Cost Price, Tax, HSN, Qty | DP + Cost Price |
| MUFTI.xlsx | C | 2 | BARCODE, CATEGORY2-5, DIVISION/SECTION/DEPARTMENT, INVOICE_RATE, RSP, MRP, HSN | richest Ginesys (fit in CAT) |
| Peter England.CSV | E | 0 | EAN No, Material, Size, Color, Fit Type, MRP, WSP, Net Unit Cost, Unit Cost, HSN | 53 cols, has Fit + Color |
| peppermint 13.xlsx | A/B | 0 | Stock No, Product, Brand, Style, Shade, Size, Retail Price, Cost Price, GENDER, SEASON, HSN | has GENDER + SEASON |
| STATUS QUO.xlsx | B | 0 | EN Code, Item, Item Code, Shade, Size, MRP, Rate, GST%, HSN | |
| SWEET DREAMS.xlsx | F | 2 | ITEM CODE, ADDITIONAL ITEM CODE, SHADE, SIZE, QTY, M.R.P., RATE, GENDER+Body, BODY, Season, HSN | has gender+body |
| TWILLS.xls | B | 0 | Bar Code, Item Name, Type, HSN, Quantity, Rate, MRP | really `.xlsx` |
| USPOLO INNER WEAR.csv | E | (none) | positional: EAN[20], style[27], size[30], qty[33], rate[34], MRP[35], HSN[26] | headerless — map by index |
| XERICS JEANS PT FILE.xlsx | A | 0 | Br-Code, Description, HSN, Size, MRP, Quantity, Rate, Disc % | invoice-ish |
| ZILU BOTTOMS.xlsx | B | 0 | Barcode, Product, Brand, Style, Shade, Size, Retail Price, Item Rate, Item Base Value, HSN | BASIC = Item Base Value |
| ambreli 1855.xls | F | ~22 | STYLE NO., EAN CODE, COLOUR, MRP, QTY (in PACKING/INVOICE sheet) | printed invoice + packing list |
| kidcity 1316&1317.xlsx | A | 0 | VSKU, Age Group, Color, Gender, Category Name, Price, SKU No, QTY | SKU No = barcode; Age=size |

---

## 8. Recommended build order

1. **Lock the target & lookups.** Freeze the KDPS Work Sheet columns + load the Master Sheet into the six lookup tables (size, colour, brand, taxonomy, season, gst).
2. **Build the engine once:** magic-byte reader (xls/xlsx/xlsb/csv) → header detector → data-range detector → declarative column-map applier → lookup normaliser → derived-field calculator → validator → review queue → KDPS writer.
3. **Write profiles in archetype order:** C (Ginesys) → B (Tally/Vistaar) → D (Jockey) — these cover ~18 files and most volume. Then A (simple) — nearly free. Then E (wide SAP — subset selection). Then F (printed invoices — anchored header) last.
4. **Settle the money rule (§5)** with finance/CA before BASIC/P RATE/MARGIN are trusted for posting.
5. **Run all 33 files, work the review queue to zero,** then the tables cover the long tail and new files from the same ERPs map with no code change.

**Definition of done:** every one of the 33 files produces KDPS rows where each derived field is either a valid Master-Sheet value or an explicit review-queue entry — and re-running after a lookup is added needs **zero code change**.

---

## 9. Why software, not AI

Every transformation here is **deterministic and auditable**: a rename, a table lookup, or an arithmetic formula. The only "intelligence" needed is the **one-time human decision** of "this brand category means this KDPS item/fit" — captured once in a lookup row and reused forever. AI would make cost and taxonomy non-reproducible and unauditable, which is unacceptable for a file that drives stock value and margin. The review queue is the controlled place where human judgement enters; everything else is fixed rules.
