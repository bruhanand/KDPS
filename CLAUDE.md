# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

Anand is the consultant/architect designing and building an operating system for **KDPS Lifestyle Pvt Ltd** — a multi-brand Indian fashion retailer (Bihar & Jharkhand, 50+ stores/warehouses, 20,000+ SKUs, 40+ brands) that currently runs on per-store POS + Tally + Excel.

**Anand designs the system himself.** The client supplied their own plans (PRD, "Definitive Plan" with 10 AI agents, an 8-month phasing) — those are in `client-requirements-docs/` and are **requirements input only, not the design**. Do not treat the client's architecture, agent list, tech stack, or phasing as decisions. The cancelled "Phase-1" plan is in `__archive/` — never build from it.

## Where things stand (25 June 2026)

**The master architecture is `my-understanding/system-design/00-system-architecture.html`** — the whole system on one page (5 layers: master data → documents → ledgers → controls → intelligence), the 12 rules every module must obey (documents-write-ledgers, snapshot masters, flag-don't-block, AI at edges only, variation-is-data-not-code, etc.), and the ordered discussion plan D3–D9. **Read it before any design discussion; designs that break a rule must change the rule consciously on that page first.**

The system design ("the spine") is built in process order, one discussion at a time. Each design lives in its own folder under `my-understanding/system-design/`:

1. **D1 · Vendor management & booking** — designed → `01-vendor-management/`
2. **D2 · Inbound** (goods arrival → data injection → sellable in store) — designed → `02-inbound/`
3. **D3 · Outbound + stocktake** (sale, exchange, transfer, returns out, EOSS, counting) — designed → `03-outbound/`
4. **D4 · Payments & roles** — designed (locked 18 Jun 2026) → `04-payments/`
5. **D5 · Offer rulebook** — designed → `05-offers/`
6. **D7 · Analytics & AI** (the intelligence layer) — designed → `07-analytics-ai/`
7. **D6 · Tally sync** — designed (locked 20 Jun 2026) → `06-tally-sync/`
8. **D8 · Master-data & users consolidation** — designed (locked 21 Jun 2026) → `08-master-data/`

**Now building.** All module designs (D1–D8) are done. Decision (23 Jun 2026): start the **foundation build** now (project setup — repo, database, login, user-roles, deployment), not more design. **Deferred to later, by decision (revisit before go-live):** D9 · migration & rollout → `09-migration/`, the deep **roles/access** model (D4 left it thin), and **Attendance & Payroll** — none of these block the foundation. **Stack (ratified 25 Jun 2026 — ADR-0001):** browser-based **React (TypeScript) PWA** front end + **Python/Django** back end (gives login, roles, back-office admin and ledger transactions out of the box; same language as `code/pdf-to-pt` and the analytics/AI) + **PostgreSQL**, hosted in an India region. **No backend-as-a-service** — Supabase rejected (weak for all-or-nothing ledger transactions, complex permissions, lock-in). ERPNext (open-source India ERP with GST built in) considered and not adopted, but its GST data model is borrowed. Full reasoning: `my-understanding/system-design/consolidation/stack-decision.html`.

**Reviewed, decided & reconciled (25 June 2026).** A full design review (drift audit + India retail-ERP best-practice research) ran across the corpus, then a **16-decision Q&A** locked every open seam — GRN posts quantity / PT posts value + liability; cross-state (Bihar↔Jharkhand) transfer = taxable IGST; unit cost = P RATE directly (never strip GST); barcode = a non-unique scan-alias with stock a **count under it**; own-POS in scope behind Ten Software (one store, one POS, idempotent); booking-less direct receipt for any brand; commercial model stored as **two axes** (ownership × return-terms) with derived labels; **stack ratified (ADR-0001)**; per-user-configurable digest; **Rule 12 "variation is data, not code"**. Decisions are logged in `.context/qa-decisions.md`; the review is `consolidation/system-review-2026-06-24.html`. The **canonical doc set is now in order**: constitution (`00-system-architecture.html`) → design-of-record (`consolidation/consolidated-system-design.html`) → build artifacts (`consolidation/glossary.html`, `data-model.html`, `posting-catalog.html`, `lifecycles.html`, `integration-contracts.html`) → ratified **ADR chain** (`adr/0001`–`0007`) → D1–D8 appendices → build companion (`build-process-and-roadmap.html`, `erpnext-engineering-study.html`). **Five money-critical items await a CA ruling before the money slices**: SOR/Consignment GST single-recognition (F9), the 6-month deemed-supply clock, late-freight-after-PT, sold-before-PT, and the no-reposting rule. The distrusted `foundation.html`, old `docs/adr/*`, `docs/agents/*` and `CONTEXT.md` in the `/Users/anand/Code/KDPS` checkout are **slated for deletion (pending Anand's go + repo-remote confirmation)**; their salvage is already folded into the new ADRs + glossary.

**Pace (decided 10 June 2026): no fixed timeline — ASAP with quality.** Working plan (revised 23 Jun): lock the stack → build the **foundation** (project setup) → then **one verified vertical slice at a time** with just-in-time per-slice specs (data model, posting entries and golden files grow per slice, not all upfront). Spike the three externals (Ten Software POS API, Tally import, barcode tool) **in parallel** — they have lead time. D9 migration is designed before go-live. Never all PRDs upfront, never module-by-module to completion. Full process: the **"How we build"** section of the architecture doc.

Code work (`code/pdf-to-pt`, the Invoice → PT file maker) is **paused until the full design is done**, then resumes.

Separately, there is a recurring live duty: **month-start brand reports** (1st week of every month) in `data-from-kdps/monthly-reports-april-may-2026/`. Skills exist for this: `kdps-report`, `discount-audit-v2`, `kdps-offer`.

## Folder map

`PROJECT-MAP.html` is the human-readable index — keep it updated whenever folders or project status change.

| Folder | What it is |
|---|---|
| `my-understanding/` | **Anand's own work.** `system-design/` = the spine (architecture + D1–D9 module designs + `workflow-diagrams/`); `req-understanding-docs/` = requirement write-ups; `workflow/` = **ground truth** (`KDPS-current-workflow.pdf` = how KDPS works today, the design is derived from it; `conversations.md` = raw staff interviews). |
| `data-from-kdps/` | **Raw material received from the client.** `05-reference-data/` (PT file format + real vendor invoice/PT/ledger samples + logo), `Q&A-req-recieved/` (store list, supplier-brand details, brand offers, ~25 brand PT files, report formats), `bank-statement/`, `monthly-reports-april-may-2026/` (the report duty; `KDPS-DIRECTION.xlsx` = worked example to copy, `FORMAT_SALES_VOUCHERS.xlsx` = blank template), `store-analysis/` (Vaishnavi Deoghar deep-dive). |
| `client-requirements-docs/` | Client's asks (PRD, Definitive Plan, `client-demands.html`, `ERP-requirements-register.html`, `change-request/`). **Requirements only — not the design.** |
| `04-client-docs/` | Client-facing per-module deliverables (Vendor, Goods-Inward, Outbound, Payments, Offers, POS requirements). Living documents — they change until the architecture is final. |
| `meetings/` | One folder per meeting, named `YYYY-MM-DD-topic/` (audio + transcript + minutes). |
| `code/` | `pdf-to-pt/` Invoice→PT pipeline (see its `BLUEPRINT.md`); ~150 real invoices in `document/` for testing. `scripts/generate-pdf.mjs` = HTML→PDF helper. |
| `__archive/` | Stale material (cancelled Phase-1, old timeline, old direction doc, old drafts/decks). **Never design or build from here.** |
| root | `MOU-KDPS-Anand.pdf` (engagement/scope), `PROJECT-MAP.html` (index), `CLAUDE.md`. |

House rules: new design discussion → its own numbered folder under `my-understanding/system-design/`; new meeting → `meetings/YYYY-MM-DD-topic/`; new month's reports → month folder under `data-from-kdps/monthly-reports-april-may-2026/`; superseded docs → move to `__archive/`, don't delete.

## Domain facts that must never be violated

These are properties of the business, independent of any design choice:

- **SKU = Style × Size × Color.** Stock at style level only is wrong; size×color must survive end-to-end.
- **SOR vs Outright vs Hybrid** per brand drives ownership, return windows (60–120 days — deadlines must be tracked), margin model, and EOSS rules. First-class dimension, not a flag. (SOR/consignment: stock counted by quantity but value stays off-book until sale; vendor liability posts only on sale.)
- **Season / Collection / Age** tagging on every item; aging drives markdowns and dead-stock handling.
- **Profitability is derived** (cost from PT/invoice at stock-in, revenue from POS at sale), never hand-entered.
- **GST is mandatory** (GSTIN, HSN, tax breakup); **Tally stays the statutory book of record**. Two GSTINs — Bihar and Jharkhand are separate "distinct persons"; every store/warehouse maps to a state GSTIN; cross-state transfers are taxable supplies. Apparel GST is slab-based and date-effective — model it as data, not code.
- India context: INR with Lakh/Crore formatting (`₹28,50,000`), low-end Android phones in stores (browser/PWA, no app installs), owners live on WhatsApp, Hindi for training material.
- Offer/discount logic is brand-specific and slab/condition based (see `meetings/2026-06-01-offers-and-reporting/`): value slabs, B2G1 with lowest-item-free, gifts above thresholds, per-store applicability, start/end dates with fallback rules.

## Working norms

- **Deliverables are HTML files, never markdown**, for anything Anand will read or share (PDF via `code/scripts/generate-pdf.mjs` when needed).
- **Plain, non-technical language** in chat and client docs. Short answers; do only what's asked.
- **Understand before design:** current workflow first (`my-understanding/workflow/`), then client wants, then design.
- **Engineering-led build order:** build by architecture sequence, not the client's wishlist order.
- When details are ambiguous, check `my-understanding/workflow/KDPS-current-workflow.pdf` and meeting minutes rather than inventing.
- No build/test/lint commands exist yet at repo level; `code/pdf-to-pt` is a Python project (`pyproject.toml`, pytest). Add real commands here when serious code work resumes.

## gstack

Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.
Available skills: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /design-shotgun, /design-html, /review, /ship, /land-and-deploy,
/canary, /benchmark, /browse, /connect-chrome, /qa, /qa-only, /design-review,
/setup-browser-cookies, /setup-deploy, /setup-gbrain, /sync-gbrain, /retro, /investigate,
/document-release, /document-generate, /codex, /cso, /autoplan, /plan-devex-review,
/devex-review, /careful, /freeze, /guard, /unfreeze, /gstack-upgrade, /learn.
