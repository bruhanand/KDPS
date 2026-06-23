# Minutes of Meeting — KDPS Current Workflow Walkthrough

| | |
|---|---|
| **Date** | 21 May 2026 |
| **Mode** | Video call |
| **Subject** | Walkthrough of KDPS's **current** operational workflow — as understood and drawn by Anand |
| **Reference doc** | `03-workflow-diagrams/KDPS-end-to-end-workflow.pdf` (Part 1 "Before the Store", Part 2 "After the Store") |

### Attendees
| Label | Role |
|---|---|
| Anand | Developer / consultant (presenter) |
| Owner ("Bhaiya") | Senior decision-maker — left part-way through the meeting |
| AK ji | Operations head — warehouse + store process knowledge |

> Also referenced (not present): **Devanjan ji** — handles the warehouse / PT-file side; Anand to coordinate with him for the store visit.

---

## 1. Purpose of the Meeting

This meeting was **only about the current (as-is) workflow** — how KDPS operates today across booking, sourcing, warehouse, PT-file, stores and sales. It was **not** about the system to be built. Anand walked the client through the workflow PDF; the client gave corrections so the diagram accurately reflects reality. Confirming this shared understanding is the gate before any system design or development begins.

---

## 2. Current Workflow — Confirmed as Correct (no change)

- **Booking:** branded booked 6–8 months ahead, non-branded 3–4 months ahead; verbal / undocumented agreement with vendor or city agent. Mix is roughly **70% branded / 30% non-branded**.
- **Branded inbound:** goods mostly land at the store (some at warehouse) → store receives goods + invoice → store forwards invoice to warehouse → warehouse converts to **KDPS-format PT file** → **Patna office verifies** (GST + margin) → Patna inwards into the system → PT file sent to store → store scans & inwards → stock is sellable.
- **Non-branded inbound:** ~99% to warehouse, ~1% direct to store (vendor location constraints) → physical counting at warehouse → if vendor sends a PT file, convert to KDPS format; if only an invoice and it is detailed enough, build the PT file from the invoice; if the invoice is too vague, call the vendor.
- **Exchange — damaged vs good:** a damaged exchanged item goes back to the brand; a good item goes back to the sales floor.
- **Barcode present but scanner/POS not reading it** → falls back to **manual billing** → head office enters it next day. Confirmed already covered in the diagram.

---

## 3. Review Comments — Corrections to Make to the Workflow Diagram

These are the changes the client asked for. Each is the punch-list for the PDF update.

### C1 — "With-tag" items are BRANDED, not non-branded *(Part 1)*
- If a vendor attaches **their own brand + tag + MRP + barcode**, the item is treated as **branded** ("we count it in brand"), regardless of where it physically arrived. It follows the branded flow.
- **New case to add:** some companies (often local-level) attach tag + MRP **but do not send a PT file**. Here KDPS must **build the PT file using the MRP as the base** and apply the **margin the company has already decided**.
  - This is distinct from the existing "no barcode at all" case, where KDPS sets MRP = base + transport + GST + 30–35% margin and generates its own barcodes.
- Action: in the diagram, make the branded/non-branded split key off *"did the vendor put their own brand/tag on it"*, and add the missing branch *"tag present but no PT file → build PT from MRP base + company-set margin."*

### C2 — Remove the "Return" branch; returns are exchange-only *(Part 2)*
- Policy: **"return is goods exchange — no money, no credit."** Exchange is **MRP-to-MRP**.
  - Exchanged item MRP **lower** → customer takes additional item(s) to cover the gap (down to socks / handkerchief).
  - Exchanged item MRP **higher** → customer pays the balance.
- **Delete the "Return" node entirely** from Part 2 — Anand confirmed this in the meeting.
- A cash refund exists only as a **rarest-of-rare exception** (influential customer / police / diplomat, with management approval — ~1 in 10,000). This must **not** be drawn in the diagram or built as a system rule — making it visible would turn an exception into an expectation for floor staff. Keep it backend / manual / undocumented.

### C3 — Inter-store transfer: keep the WhatsApp method; no bus-detail tracking *(Part 2)*
- Anand asked whether to capture bus number / driver details. Owner said **no** — transfers are effectively instant (~2 hrs); by the time data is entered it is immaterial, and it adds overhead.
- **Actual current process:** dispatcher loads goods on a bus → posts bus number + driver number in a **WhatsApp group** → receiver posts receipt confirmation in the same group → the receiving store's software shows the items under **"today's credit"** → receiver inwards them. This happens **very frequently**.
- Action: redraw the Part 2 transfer section to show the WhatsApp-group confirmation + "today's credit" inward — **not** a system-tracked transfer with bus-detail fields. System-level transfer tracking is deferred to a later ERP phase.

### C4 — Defective / GR returns happen via TWO routes — show both *(Part 2)*
- **Route A — Madura Fashion brands** (Allen Solly, Louis Philippe / "LP", etc.): the brand picks up its GR / defective stock **directly from KDPS stores**.
- **Route B — all other brands + non-branded:** defective goods go to the **warehouse**; stock from all stores is consolidated in one place; **GR and defective returns are processed from the warehouse**.
- Action: split the single "Returned to the brand" path in Part 2 into these two routes. (The SOR end-of-season return path is separate and stays.)

---

## 4. Parked for the Requirements / ERP-Design Phase (not current-workflow changes)

- **GR value should be auto-calculable:** KDPS wants to independently know per-season purchase value and the resulting GR entitlement (e.g., 10% of purchases = ₹2 lakh) to cross-check the brand. Owner raised it; Anand parked it explicitly for the ERP discussion.
- **System-level inter-store transfer tracking** — later ERP phase.
- **Rarest-of-rare cash refund** — backend only; never a documented rule.
- **Finer-grained defective / GR return flow:** today AK ji described defective returns as a single umbrella ("defective stock, meaning whatever GR there is"), routed by brand (Madura pickup from store vs warehouse consolidation for the rest) — captured as-is under C4. In the ERP phase this needs to be broken into a more granular flow distinguishing **post-inward defective stock** (found on the floor / during stock checks), **damaged-exchange quarantine items** (came back via customer exchange — currently routed through the same brand-pickup vs warehouse-consolidation decision), and **defective return vs GR claim as separate processes** (they share routing today but differ commercially). Confirm with AK ji during the requirements walkthrough.

---

## 5. Decisions

- **D1.** Return-for-money / store-credit path is removed — exchange-only, MRP-to-MRP.
- **D2.** Items carrying the vendor's own brand/tag are classified as branded.
- **D3.** Inter-store transfer stays on the WhatsApp method; no bus-detail entry; system tracking deferred.
- **D4. POS system — keep the existing POS for now.** The current POS is **"Ten Software"** (T-E-N, a Dhanbad-based company). The client strongly prefers **integrating changes into the existing POS over a full revamp** — reasons: staff comfort, low staff skill, cost and effort of retraining across many stores. Approach agreed: first list the POS functionality KDPS actually needs, then decide (talk to Ten's vendor for changes, obtain their files to edit, or evaluate alternatives such as **"Wizamp"**, mentioned by the Owner as cheaper and popular). If a rebuild is ever unavoidable, the new system must **look and feel identical to the current UI** so no training is needed — only a document / short video.
  - Limitations Anand noted in Ten Software: discounts not handled (manual entry); no single sign-on (separate login per store); ~100 functions but only ~10 used at warehouse, ~4 at store level.
  - Cost context: an option Anand had shared was ~₹12.5 lakh for ~30–35 stores + 1 warehouse; client finds market software pricey.
- **D5. Process sequence agreed:** confirm current workflow → **Requirements Document** → system / agent architecture design → client review & back-and-forth → finalise plan → development. No development starts until the shared understanding of requirements is locked.
- **D6. The invoice / PT-file → KDPS-format conversion tool is the #1 priority** (manual entry is the biggest pain point). Anand will build it as a parallel side project and integrate it into the main system later.

---

## 6. Action Items

| # | Action | Owner | Due |
|---|---|---|---|
| 1 | Update the workflow PDF/diagrams with corrections C1–C4 and send the "shared understanding of the workflow" to AK ji | Anand | Night of 21 May |
| 2 | Review the updated workflow; mark what is right / wrong | AK ji | Morning of 22 May |
| 3 | Review call to finalise the current workflow | Anand + AK ji | Morning of 22 May |
| 4 | Coordinate with Devanjan ji; visit the "See More" store (near Hatia, Ranchi) ~4–5 PM peak for 2–3 hrs; observe billing + process; explore "Ten Software"; review Devanjan ji's system | Anand | Within 1–2 days |
| 5 | Assess store attendance approach (Wi-Fi / GPS-radius geo-tagging) during the store visit | Anand | Store visit |
| 6 | Draft the Requirements Document once the workflow is signed off | Anand | After workflow confirmed |
| 7 | Continue building the invoice / PT-file conversion tool as a parallel side project | Anand | Ongoing / priority |

---

## 7. Timeline

- **Hard deadline:** everything must be in place **before Durga Puja** (huge PT-file rush) — i.e., **by September**.
- **Working window:** June, July, August. Anand budgets ~1 month for planning (the current month) + ~2 months for the build.

---

## 8. Next Point of Action

**Update the workflow diagram and re-issue it for sign-off.** Concretely:

1. Apply corrections **C1–C4** to the two Mermaid source files —
   - **Part 1 "Before the Store":** `03-workflow-diagrams/stock-workflows.html` (C1)
   - **Part 2 "After the Store":** `03-workflow-diagrams/store-workflow.html` (C2, C3, C4)
2. Re-render `KDPS-end-to-end-workflow.pdf`.
3. Send it to AK ji **tonight (21 May)** as the "shared understanding of the workflow."
4. Hold the **22 May morning call** to get sign-off.

Workflow sign-off is the gate for everything downstream — the Requirements Document, the architecture/agent design, and development all wait on it.
