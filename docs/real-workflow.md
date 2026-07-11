# KDPS OS:

## Booking where data is born.

### 2 booking type:

1. Branded Booking
   (considered branded: Proper booking reciept is giving at bokking, when goods arrieve at KDPS, it comes with invoice, all the goods are tagged, PT file can be provided by the vendor.
   Brand = at booking: Booking reciept + at arrival: invoice, tagged goods, Branded, provided by the brand)
2. Non-branded booking: there will be some receiving on any of the platforms like WhatsApp, email, phone call, or the raw invoice itself — mostly no receipt, no tag, no PT file. Sometimes just "X pieces, this rate."
   Non-brand = at booking: verbal / WhatsApp / email / call + at arrival: plain invoice, often untagged, no PT file → KDPS builds everything itself.

### Booking facts — branded vs non-branded

**Branded.**
- To book, **someone goes to the brand, selects the items / models, and places the order** (brand reps invite KDPS to the Ranchi warehouse / showroom to see new models; the booking happens there).
- You get a proper **receiving** (booking receipt) — the booking is documented.
- **The supplier takes care of it** — no agent in between (payment terms, shipment, the commercial model). Booked **6–8 months** ahead (winter stock booked in March).

**Non-branded.**
- The booking is informal, done in many ways with none more common than the rest — a person may **go to the vendor and book in person**, or it happens over a **call, WhatsApp, or email**, or there is no talk at all and the **goods simply arrive with the invoice**.
- A **receiving may or may not come; when it does, it isn't very detailed.**
- An **agent sits in the middle (non-brand only):** guarantees **payment** to the vendor for KDPS · guarantees **shipment** to KDPS · handles **returns / defect adjustments** (100 billed, 96 usable → agent fixes the ledger). Commission **1–2%** · payment cycles **30 / 45 / 60 / 90 days**.
- Booked **3–4 months** ahead; the vendor roster rotates ~every 6 months.

**Mix: ~70% branded · ~30% non-branded.** The 30% non-branded is the hardest part — worst data, most manual work — and it is the heart of the business (ladies' + kids'). It all runs on trust; KDPS is a known name in the trade.

### Does a booking get cancelled?

- **Brands:** generally no.
- **Non-brands:** quantity/item can change (booked 100 → sent 90 booked + 10 something else), but rarely zeroed out.
- Practically, **whatever actually arrives = the booking.**

---

## The commercial model — decides everything downstream

Before the goods even arrive, the **commercial model** on the supplier decides who owns the stock, when money is owed, the margin, and how a return works. Tagging is at the **supplier** level, not the brand — one supplier can carry many brands.

**Model 1 — Margin / commission ("25-18-10")**
The company bills KDPS below MRP; KDPS keeps its cut and pays the rest.
- ~**25%** at full price · ~**18%** in an offer/EOSS · ~**10%** goods-return (GR) allowance per season.
- ₹100 item billed to KDPS at ₹75; KDPS keeps ₹25, pays ₹75.

**Model 2 — Buy & Sell (BNS / outright)**
KDPS **buys outright** and prices it however it wants; the brand has no say in MRP or margin.
- **With barcode** → MRP capped at what's printed. **Without barcode** → KDPS sets MRP + tags it.

**Model 3 — SOR / Consignment (same thing)**
Stock **belongs to the brand**, sits in KDPS's custody. Sell it, report it, pay after sale; unsold goes back **with no penalty, no capping**.
- Sell 400 of 1,000 → the other 600 go back as-is (old or new, doesn't matter).
- Minor split only: **SOR** = one booking, return the rest; **Consignment** = rolling top-up, return the unsold. Same for KDPS.
- Value stays **off KDPS's books** until the item sells — brand liability posts only on sale.

**Collection / Correction model (a variant)**
A % (10/12/20…) allowed, but calculated on **what was serviced (delivered)**, not booked.
- Booked 1,000, delivered 900 → collection on **900**. Booked 800 + 200 more → on the **1,000 delivered**.
- Some brands (Levi's) compute against **"actual buying"** vs last year.

**EBO model (a separate world)**
An **EBO** runs on the **brand's own software** — brand decides what to send / pull back and tracks its own sales. KDPS is basically the custodian: at month-end it takes a flat commission (20% of ₹10 L = ₹2 L for rent + salaries + profit, sends ₹8 L to the brand). **EBOs are outside the KDPS inventory/PT flow entirely.**

**Brand incentives (on top of the model)**
Dynamic, per brand: "run 6 stores → 2% extra; run 10 → 3% extra." Feeds the cash / payment audit later.

### Store formats

| Format | Meaning | Who owns the inventory data |
|---|---|---|
| **EBO** | Exclusive Brand Outlet (one brand) | Brand's own software |
| **MBO** | Multi-Brand Outlet (men-only, or men+women) | **KDPS** owns data + PT process |
| **SIS** | Store-in-Store (brand corners in one MBO, e.g. Big Shop) | KDPS, many brand PT files in one place |
| **KDPS Lifestyle** | KDPS's own name at some locations (e.g. Deoghar) | Internal |

Layout follows psychology: a flagship like Sanskar (Ratu Road) = **ground floor women's, first floor men's**; women's drives ~70% (women shop for ~12 occasions/year; men buy on need).

---

## Goods arrive — inbound

### Branded inbound

Brand sends goods **with the invoice**. Most land **at the store**; a few at the **warehouse** (Ranchi).
1. Land at **store** → store forwards invoice (photo/PDF, WhatsApp) to the warehouse.
2. Land at **warehouse** → invoice already there.
3. Goods **counted by hand** vs the invoice.
4. Warehouse asks the brand for the **master PT file** — brands like Aditya Birla (Madura: Allen Solly, Louis Philippe, Van Heusen, Peter England) send one **every ~15 days** for the whole East zone (Bihar, Jharkhand…).
5. Match by invoice/reference number → pull the matching rows → build the **KDPS-format PT file**.

*Barcode note:* one style code can ship with **different unique barcodes** per piece ("1,1,1,1" usually = four unique barcodes for one style). Structural, not an error.

### Non-branded inbound

~**99% to the warehouse**; ~1% straight to a store when the vendor's location forces it. **Counted by hand** vs the invoice. Then, depending on what the vendor sent:
- **Vendor PT file** → convert to KDPS format; keep vendor barcode + MRP tag (tag MRP is final).
- **Only an invoice, detailed enough** → build PT from the invoice.
- **Invoice too vague** → **call the vendor** ("what's in style code X? what sizes?").
- **Nothing tagged** (no barcode/MRP/tag) → KDPS sets the MRP + generates + sticks its own barcodes.

Invoices are wildly inconsistent — some have style code / colour / size, some don't. Missing style codes come off the **challan** or the **box**. Barcode rule of thumb: **one barcode per size**, never per colour for sarees / petticoats (free size → all pieces share one barcode).

### The "counted as branded" rule

Treated as **branded** only when **all three** are present:
1. vendor **barcode + tag**, 2. a **proper detailed invoice**, 3. a **vendor PT file**.
If any one is missing → stays non-branded.
Middle case: **tag + MRP but no PT file** → KDPS builds the PT using the **printed MRP as the base** + the **company's already-decided margin** (does not invent a new MRP).

### How KDPS sets MRP (when it must)

```
MRP = Base rate
    + 1.1%  (flat transport, on receipt)
    + GST   (per HSN)
    + Margin  (~25% branded · 30–35% non-branded)
```
Mostly fixed; nudged by demand (last cycle's sell-through). Transport cost **~90% borne by KDPS**.

---

## PT file check & head-office inward

Every PT file — branded or non-branded — goes to the **Patna head office** first.
1. HO checks **GST + margin**, okays the PT file.
2. HO **inwards** the PT into the current system (**Ten Software**); barcodes are generated **inside Ten**.
3. Chain today = ~**4 people**: generate (warehouse) → approve → inward (Patna) → bill to store. Any one absent → pipeline stalls.

*Timing:* ~1 working day/invoice normally; **3–4 days** in the Aug–Dec rush; Sundays add delay (Patna inward off).

---

## Split across stores & transfer out of the warehouse

PT file is made **first**, uploaded, **then** split.
1. **Sorting / distribution** by each store's **past-sales share** ("100 pieces — 40% here, 60% there"). Lives in the ops team's head today; done at the warehouse or over the phone.
2. Produces N separate store stocks.
3. **Mahendra ji bills each split under that store's name** + puts it in transport.
4. The receiving store sees a **pending inward** on its POS login — quantity visible **before** goods arrive.

---

## Store inward — how stock becomes sellable

1. The moment the sender (Patna HO, warehouse, or a sister store) **saves the transfer voucher**, a **pending inward** appears on the receiving store's POS login.
2. Goods arrive; inward is done **daily**.
3. Staff opens the matching inward voucher.
4. **Each piece scanned by barcode** → **Received qty ↑, Pending qty ↓**.
5. All scanned → inward complete → **sellable at the counter**.

**Selling before "in":** goods are in hand the moment they arrive, so staff can sell before keying the inward. That SKU then shows a **negative SOH** until the inward is done; the next sync evens it out. This is how it runs today.

**SOH report:** Reports → Retail Analysis → Stock Query · scoped per login · filter all/one brand · Excel export. Columns: Opening / Purchase / Sale / Adjustments / Transfers / Receipt / Total + MRP, Rate, Season, Barcode, Supplier. Spans store-open → today (sold-out SKUs show at zero).

---

## The counter — a normal sale

1. Staff check the **active offers on the placards** — the POS does **not** apply them automatically.
2. Barcode scanned.
3. Reads cleanly + POS up → ring **full price** or **key the discount in by hand** (% or cash amount).
4. Customer pays **cash or UPI** — only **Cash / GPay / Card** are ever used. **No udhaar (credit) at all** — payment is always full at sale.
5. Bill printed → **stock comes off automatically**.

**Part payment:** customer has ₹500 of ₹1,000 → the **store manager** covers the rest personally, settles with the customer later. Company gets its full ₹1,000, doesn't care who paid. Off-system; UPI hits the manager's personal QR, not the POS.

---

## Manual billing fallback

**A · POS down / no internet** (common at rush hour — cell networks choke even on Wi-Fi):
1. Counter cuts a **handwritten / manual bill** — customer served now.
2. POS/net back → staff **type the bill into the POS themselves** (barcode written by hand, then added).
3. Stock comes off; sale matches. HO **not** involved.

**B · POS hangs mid-transaction** (unclear if it recorded):
1. State ambiguous — bill may or may not have saved.
2. **HO gets involved** to check + fix — corrected next day.

---

## Customer exchange (there is no "return for money")

Policy: **return = goods exchange. No money, no store credit.** Swap is **MRP-to-MRP, valued against what the customer actually paid** on the original bill.

| New item MRP vs original bill | At the counter |
|---|---|
| **Lower** | Customer adds items to cover the gap — down to socks / handkerchief |
| **Equal** | Direct swap |
| **Higher** | Customer pays the difference |

- **Window:** printed **5 days**, stretched to **10–12** for repeat customers — effectively not a hard rule.
- **Lost bill:** looked up by the customer's **phone number** → bill, item, date, amount.
- After swap: **good** piece → back to floor stock; **defective** → kept aside for the defective flow.

*Rarest-of-rare:* a cash refund only for a VIP (police / diplomat), with management approval — ~1 in 10,000. **Never** a documented rule or a system feature (making it visible turns an exception into an expectation).

---

## Inter-store transfer

**Only MBO stores.** EBOs don't move stock between themselves — that's between the brand and the EBO.

Reasons (purpose need not be recorded): **sister store needs it** (bill made at the receiving store) · **slow-moving** (sitting 3–4 months here, sells there) · **seasonal swap** (winter out / summer in) · **free up floor space** (old stock back to warehouse).

How it's made:
1. Open **Stock Transfer**, pick the receiving store.
2. Scan each piece by barcode. For some brands (**Jockey**) entry is by **style code** — because that's how the brand's PT file is written.
3. **Save voucher** → a **PT-like transfer document** is auto-generated (POS makes it; data pullable to Excel).
4. Receiving store sees **pending inward / "today's credit"** — even before goods arrive.

How goods travel: **public bus** (~2 hrs, most common) · **courier/parcel** · **own/hired vehicle** · **hand-carried**. Then:
1. Dispatcher hands goods to transport.
2. Bus no. + driver no. posted in a **WhatsApp group**.
3. Receiving store confirms in the same group on arrival.
4. Receiving store scans each piece to inward it → sellable.

Transfers are near-instant, so **bus/driver details aren't stored** in the system today. System-level transfer tracking is a later concern.

---

## Defective & GR returns to the brand

Defective stock — found on the floor or quarantined from an exchange — goes back by one of **two routes**:

| Brand | Route |
|---|---|
| **Madura Fashion** (Allen Solly, Louis Philippe, Van Heusen, Peter England) | Brand **picks up directly from the store**. |
| **All other brands + non-branded** | Goes to the **warehouse** first; every store's defective stock is consolidated there; GR / defective return is sent to the brand **from the warehouse**. |

In practice most defective pieces travel back the **same path they came in on**, and ultimately route through the warehouse's goods-return process. On the counter: a **manufacturing defect** is swapped equal-or-higher value with no window fuss for a known customer; a **used** item must return within the ~5–7 day window (tag-less accepted — the barcode/bill carries the data).

*Debit notes ("V-spikers"):* vendor ships excess / unordered stock → KDPS returns it or issues a **debit note** so the loss is covered. Entered by hand, matched bill-by-bill vs the vendor ledger.

---

## SOR seasonal return

For **SOR / consignment** brands, unsold pieces (within the agreed allowance) go back **at end of season**.
- **Separate path** from the defective / GR flow.
- The return window / allowance per brand lives in the **supplier master** — the ~10% stretched to **12–15%**.
- KDPS wants to **compute the entitlement itself** (10% of the season's purchases = ₹2 L) to cross-check the brand instead of trusting the brand's number.

---

## EOSS / discounts

Two windows: **Summer EOSS ≈ August**, **Winter EOSS ≈ February**. Seasonal items discount end of same season; **core** items (men's tees, jeans, basic shirts) usually run their offer the *next* year.

- Discount is **brand-funded** (flat % off a category) or **KDPS-funded** (old / dead-stock clearance).
- Brand margin usually drops **~25% → ~18%** during EOSS.
- Offers reach stores as **placards** → typed in **by hand** at billing (POS doesn't enforce).
- Beyond the counter's ~10% discretion → **higher-management approval**.
- Only 2–3 stores (Gaya, Hazaribagh) can split "offer" from "fresh"; elsewhere the whole store goes on offer.

**How offers are structured (brand-specific):**
- **Value-slab** — buy ₹6,900 → ₹600 off; ₹10,999 → ₹1,000 off; ₹14,999 → ₹1,500 off; higher → ₹2,000 off. To hit a slab, several sales are **clubbed under one bill number + one date**.
- **B2G1** — club three items, make the **lowest-value one 100% off**.
- **Gift thresholds** — cross a ₹23,000 basket → free trolley / duffel (only if the gift was actually handed over).
- Every offer has a **start date**, often **no end date** (rolling until the brand changes it). Offers are **per store** — a brand's offer may only apply at specific stores.

---

## The month-start reporting crunch (1st–7th)

The most painful recurring duty. Every brand needs the **previous month's sales report** (with discount cross-checks per SKU per store) before it releases KDPS's **commission**.

- Report by ~**4th–5th** → commission by the **7th** → salaries on time. Miss it → payroll delay cascades.
- These 7 days: **18–19 hr days**, mostly from home; **all PT-file work halts**; days 8–15 clear the backlog → only ~10 normal working days/month. Daily deadline: **11 PM**.
- Every sale is cross-checked: was the brand-eligible discount actually applied at POS? If not, KDPS **retro-applies it on the report** so the brand still funds it.
- Reporting is **managed for leverage**: over-achieved months are held back and **surfaced in a slow month** (report 6–7 sales on a zero-sale day) to keep numbers steady and pressure the brand. Brand only checks the **discount + date + unbroken sequence** — not the bill numbers.

*Related leak:* placard discounts applied by hand let a salesperson quote 20% on a 40%-eligible item, pocket the difference, and cover it via an MRP-to-MRP exchange (which ignores discount history). Volume makes per-bill audit impossible.

---

## Payments, ledger & reconciliation

KDPS pays vendors later (creditor's counterparty), so a **ledger per vendor** tracks: what came in, what was paid, what's outstanding.

- **Cash discount (CD)** is on the **pre-tax** value: ₹100 bill (₹90 base + ₹10 tax) → 5% CD off ₹90 → add GST back → pay.
- **Lump-sum payments** are the headache: 10 invoices totalling ₹10 L, pay ₹6 L in bulk → clears 4 full + half of a 5th. Attributing a bulk payment across fractured invoices by hand is the hardest part.
- **Ledger matching:** returns + GR must show on **both** sides (KDPS's books and the vendor's), matched bill by bill (the "F3" invoice detail). Big brands (Madura, Vishal Marketing, DD Sales) → complicated, pending ledgers; small non-brands (Variety Textile, BK Enterprise) → settle on trust.
- **Brand incentives** (run N stores → X% extra) feed into this too.

Separately, the owner's biggest financial worry: the **daily cash / payment audit** — reconcile **Cash + UPI + Card** collected per store vs **actual bank deposits**, to catch cash leakage.

---

## The one-line journey

**Booking (verbal, via agent) → goods + invoice arrive → count → PT file (from master / invoice / call / self-made) → HO GST+margin check → inward → split by store past-sales share → store scans in → sellable → leaves via: counter sale · MRP-to-MRP exchange · inter-store transfer · defective/GR return · SOR seasonal return · EOSS clearance → month-start brand reports release commission → ledger reconciliation & payment.**

---

*Sources: the signed-off as-is workflow (`docs/my-understanding/workflow/KDPS-current-workflow.pdf`) + `conversations.md`; meetings — 18 May warehouse, 21 May workflow walkthrough, 25–26 May store visit, 1 Jun offers & reporting, 5 Jun 3-month deal, 13 Jun SOR/commercial Q&A.*
