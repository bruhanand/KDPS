# CLAUDE.md

Guidance for Claude Code when working in this repository.

> **Before building any slice, read [`CONTEXT.md`](CONTEXT.md) (repo root)** — the single machine-read briefing: the domain language, the 12 rules, the kernel contracts, and the money-critical locked + CA-gated decisions. **It is the one build-context file** — skills (`/to-spec`, `/tdd`, `/code-review`, `/grill-with-docs`) read it; don't fork it. This `CLAUDE.md` is *workflow/project* guidance; `CONTEXT.md` is the *domain/kernel* context; `README.md` is how to run it.

## What this project is

Anand is the consultant/architect designing and building an operating system for **KDPS Lifestyle Pvt Ltd** — a multi-brand Indian fashion retailer (Bihar & Jharkhand, 50+ stores/warehouses, 20,000+ SKUs, 40+ brands) that currently runs on per-store POS + Tally + Excel.

**Anand designs the system himself.** The client supplied their own plans (PRD, "Definitive Plan" with 10 AI agents, an 8-month phasing) — those are in `docs/client-requirements-docs/` and are **requirements input only, not the design**. Do not treat the client's architecture, agent list, tech stack, or phasing as decisions. The cancelled "Phase-1" plan is in `__archive/` — never build from it.

## Where things stand (2 July 2026)

**The master architecture is `docs/my-understanding/system-design/00-system-architecture.html`** — the whole system on one page (5 layers: master data → documents → ledgers → controls → intelligence), the 12 rules every module must obey (documents-write-ledgers, snapshot masters, flag-don't-block, AI at edges only, variation-is-data-not-code, etc.), and the ordered discussion plan D3–D9. **Read it before any design discussion; designs that break a rule must change the rule consciously on that page first.**

The system design ("the spine") is built in process order, one discussion at a time. Each design lives in its own folder under `docs/my-understanding/system-design/`:

1. **D1 · Vendor management & booking** — designed → `01-vendor-management/`
2. **D2 · Inbound** (goods arrival → data injection → sellable in store) — designed → `02-inbound/`
3. **D3 · Outbound + stocktake** (sale, exchange, transfer, returns out, EOSS, counting) — designed → `03-outbound/`
4. **D4 · Payments & roles** — designed (locked 18 Jun 2026) → `04-payments/`
5. **D5 · Offer rulebook** — designed → `05-offers/`
6. **D7 · Analytics & AI** (the intelligence layer) — designed → `07-analytics-ai/`
7. **D6 · Tally sync** — designed (locked 20 Jun 2026) → `06-tally-sync/`
8. **D8 · Master-data & users consolidation** — designed (locked 21 Jun 2026) → `08-master-data/`

**Built and live (alpha).** All module designs (D1–D8) are done, and the **foundation plus the first business layer are now built and merged to `main`** — the Emergent build, landed via PRs #31 / #33 / #34 / #35 — auto-deploying to a **Render alpha** (Postgres 16 + Django API + React PWA). Ten Django apps exist: the kernel `core` (money-as-paise, append-only ledgers with DB triggers, docstatus FSM + gap-free voucher numbering, a value GL + balanced `post_entries`, Indian FY) plus `masters`, `accounts`, `files`, `vendors`, `inbound`, `ptmapper`, `stockledger`, `finledger`, `aiagents`. The PWA has ~12 wired screens (Bookings, Inbound/GRN, PT-Mapper + review queue, Stock/Vendor/Cash ledgers, Master Data) + ~20 "coming soon" stubs. The 30-Jun code review's money-path defects were **remediated** (Phases A–F: P-RATE valuation, commercial-model liability branching, GRN/PtFile reparented onto the `core.Document` FSM, a Books-Health/trial-balance endpoint). **Active dev moved from Emergent to Claude Code** (Emergent parked, not cut). *Alpha caveats:* the vendor/cash ledgers are still single-entry running balances (only the PT-inward path is true double-entry); demo creds + JWT-in-`localStorage` are consciously deferred for the alpha. **Not built yet:** selling/POS, offers, payments/settlement, transfers, returns, Tally sync, analytics, and store open/close. **Deferred by decision (revisit before go-live):** D9 · migration & rollout → `09-migration/`, the deep **roles/access** model (D4 left it thin), and **Attendance & Payroll**. Current build state is also recorded in `memory/PRD.md` and the `emergent-build-on-main` memory.

**Stack (ratified 25 Jun 2026 — ADR-0001):** browser-based **React (TypeScript) PWA** front end + **Python/Django** back end (gives login, roles, back-office admin and ledger transactions out of the box; same language as the analytics/AI) + **PostgreSQL** (deployed on a **Render alpha, Singapore region**; true in-India data residency deferred). **No backend-as-a-service** — Supabase rejected (weak for all-or-nothing ledger transactions, complex permissions, lock-in). ERPNext (open-source India ERP with GST built in) considered and not adopted, but its GST data model is borrowed. Full reasoning: `docs/my-understanding/system-design/consolidation/stack-decision.html`; how to run/deploy: `README.md` + `DEPLOY.md`.

**Reviewed, decided & reconciled (25 June 2026).** A full design review (drift audit + India retail-ERP best-practice research) ran across the corpus, then a **16-decision Q&A** locked every open seam — GRN posts quantity / PT posts value + liability; cross-state (Bihar↔Jharkhand) transfer = taxable IGST; unit cost = P RATE directly (never strip GST); barcode = a non-unique scan-alias with stock a **count under it**; own-POS in scope (**superseded 26 Jun→26 Jul 2026: the third-party-POS route is dropped — KDPS builds its own POS, designed later**); booking-less direct receipt for any brand; commercial model stored as **two axes** (ownership × return-terms) with derived labels; **stack ratified (ADR-0001)**; per-user-configurable digest; **Rule 12 "variation is data, not code"**. Decisions are logged in `.context/qa-decisions.md`; the review is `consolidation/system-review-2026-06-24.html`. The **canonical doc set is now in order**: constitution (`00-system-architecture.html`) → design-of-record (`consolidation/consolidated-system-design.html`) → build artifacts (`consolidation/glossary.html`, `data-model.html`, `posting-catalog.html`, `lifecycles.html`, `integration-contracts.html`) → ratified **ADR chain** (`adr/0001`–`0007`) → D1–D8 appendices → build companion (`build-process-and-roadmap.html`, `erpnext-engineering-study.html`). **Five money-critical items still await a CA ruling before the alpha handles live money**: SOR/Consignment GST single-recognition (F9), the 6-month deemed-supply clock, late-freight-after-PT, sold-before-PT, and the no-reposting rule. The distrusted `foundation.html`, old `docs/adr/*` and `docs/agents/*` in the checkout are **slated for deletion (pending Anand's go)**; their salvage is already folded into the new ADRs + glossary. (`CONTEXT.md` is **not** in that list — it is now the canonical build-context briefing; see the top of this file.)

**Pace (decided 10 June 2026): no fixed timeline — ASAP with quality.** Working plan (revised 23 Jun): lock the stack → build the **foundation** (project setup) → then **one verified vertical slice at a time** with just-in-time per-slice specs (data model, posting entries and golden files grow per slice, not all upfront). Spike the two externals (Tally import, barcode tool) **in parallel** — they have lead time. (A third, the incumbent POS's API, was dropped on 26 Jul 2026 when KDPS decided to build its own POS.) D9 migration is designed before go-live. Never all PRDs upfront, never module-by-module to completion. Full process: the **"How we build"** section of the architecture doc.

The in-app **PT-mapper** (`app/backend/ptmapper`, the brand-PT → KDPS mapper) is built and live — 9 brand profiles + seeded lookups + a human review queue; fed and hardened 1 Jul, seeded on Render. The separate standalone `code/pdf-to-pt` Invoice→PT maker is regenerated per-need (weekly), not restored.

Separately, there is a recurring live duty: **month-start brand reports** (1st week of every month) in `docs/data-from-kdps/monthly-reports-april-may-2026/`. Skills exist for this: `kdps-report`, `discount-audit-v2`, `kdps-offer`. A `store-dashboard` skill (added 2 Jul) generates the 16-measure per-store business dashboard from a store's sales + SOH exports (first run: JSL).

## Folder map

`docs/PROJECT-MAP.html` is the human-readable index — keep it updated whenever folders or project status change.

| Folder | What it is |
|---|---|
| `docs/my-understanding/` | **Anand's own work.** `system-design/` = the spine (architecture + D1–D9 module designs + `workflow-diagrams/`); `req-understanding-docs/` = requirement write-ups; `workflow/` = **ground truth** (`KDPS-current-workflow.pdf` = how KDPS works today, the design is derived from it; `conversations.md` = raw staff interviews). |
| `docs/data-from-kdps/` | **Raw material received from the client.** `05-reference-data/` (PT file format + real vendor invoice/PT/ledger samples + logo), `Q&A-req-recieved/` (store list, supplier-brand details, brand offers, ~25 brand PT files, report formats), `bank-statement/`, `monthly-reports-april-may-2026/` (the report duty; `KDPS-DIRECTION.xlsx` = worked example to copy, `FORMAT_SALES_VOUCHERS.xlsx` = blank template), `store-analysis/` (per-store deep-dives: Vaishnavi Deoghar + JSL — the JSL one produced via the `store-dashboard` skill), `store-requirements-users/`, `transfer-data/`. |
| `docs/client-requirements-docs/` | Client's asks (PRD, Definitive Plan, `client-demands.html`, `ERP-requirements-register.html`, `change-request/`). **Requirements only — not the design.** |
| `docs/04-client-docs/` | Client-facing per-module deliverables (Vendor, Goods-Inward, Outbound, Payments, Offers, POS requirements). Living documents — they change until the architecture is final. |
| `docs/meetings/` | One folder per meeting, named `YYYY-MM-DD-topic/` (audio + transcript + minutes). |
| `code/` | `pdf-to-pt/` Invoice→PT pipeline (see its `BLUEPRINT.md`); ~150 real invoices in `document/` for testing. `scripts/generate-pdf.mjs` = HTML→PDF helper; `scripts/trace-logo.py` = traces the client's logo PNG into the app's vector logo component and app icons. |
| `app/` | **The built system** (Emergent build, on `main`, deployed to a Render alpha). `backend/` = Django (kernel `core` + 9 apps: masters/accounts/files/vendors/inbound/ptmapper/stockledger/finledger/aiagents); `frontend/` = React/TS PWA. Run: `README.md`; deploy: `DEPLOY.md` + `render.yaml`. |
| `__archive/` | Stale material (cancelled Phase-1, old timeline, old direction doc, old drafts/decks). **Never design or build from here.** |
| root | `MOU-KDPS-Anand.pdf` (engagement/scope), `CONTEXT.md` (build-context briefing), `README.md` (how to run), `DEPLOY.md` (Render alpha steps + seeded logins), `DASHBOARD.html` (project command centre), `docs/PROJECT-MAP.html` (index), `CLAUDE.md`, `memory/PRD.md` + `memory/test_credentials.md` (build log + seeded test logins). |

House rules: new design discussion → its own numbered folder under `docs/my-understanding/system-design/`; new meeting → `docs/meetings/YYYY-MM-DD-topic/`; new month's reports → month folder under `docs/data-from-kdps/monthly-reports-april-may-2026/`; superseded docs → move to `__archive/`, don't delete.

## Domain facts that must never be violated

These are properties of the business, independent of any design choice:

- **SKU = Style × Size × Color.** Stock at style level only is wrong; size×color must survive end-to-end.
- **SOR vs Outright vs Hybrid** per brand drives ownership, return windows (60–120 days — deadlines must be tracked), margin model, and EOSS rules. First-class dimension, not a flag. (SOR/consignment: stock counted by quantity but value stays off-book until sale; vendor liability posts only on sale.)
- **Season / Collection / Age** tagging on every item; aging drives markdowns and dead-stock handling.
- **Profitability is derived** (cost from PT/invoice at stock-in, revenue from POS at sale), never hand-entered.
- **GST is mandatory** (GSTIN, HSN, tax breakup); **Tally stays the statutory book of record**. Two GSTINs — Bihar and Jharkhand are separate "distinct persons"; every store/warehouse maps to a state GSTIN; cross-state transfers are taxable supplies. Apparel GST is slab-based and date-effective — model it as data, not code.
- India context: INR with Lakh/Crore formatting (`₹28,50,000`), stores run the system in the browser/PWA (no app installs), owners live on WhatsApp, Hindi for training material.
- Offer/discount logic is brand-specific and slab/condition based (see `docs/meetings/2026-06-01-offers-and-reporting/`): value slabs, B2G1 with lowest-item-free, gifts above thresholds, per-store applicability, start/end dates with fallback rules.

## Working norms

- **Deliverables are HTML files, never markdown**, for anything Anand will read or share (PDF via `code/scripts/generate-pdf.mjs` when needed).
- **Plain, non-technical language** in chat and client docs. Short answers; do only what's asked.
- **Understand before design:** current workflow first (`docs/my-understanding/workflow/`), then client wants, then design.
- **Engineering-led build order:** build by architecture sequence, not the client's wishlist order.
- When details are ambiguous, check `docs/my-understanding/workflow/KDPS-current-workflow.pdf` and meeting minutes rather than inventing.
- Repo-level commands exist now. `npm run ci` (ruff · mypy strict · migration check · import-linter · pytest · tsc) is the **local acceptance gate**; `.github/workflows/ci.yml` runs pytest (kernel anti-cheat + API regression) on **real Postgres** + the frontend build on push; `docker-compose` gives a local Postgres and pre-commit hooks run ruff/mypy. See `README.md` (run) and `DEPLOY.md` (Render). Caveat: cloud CI runs only a subset (pytest + build), so the deployed alpha currently carries ~54 ruff findings + un-gated mypy strict — green cloud CI ≠ a green `npm run ci`.

## Agent skills

### The dev process

Feature work runs through the phase chain in `docs/agents/dev-process.md`, each phase invoked by hand and stopping for approval:
`/feature-analyst` → grill (`/grilling`, money: `/grill-with-docs`) → `/contract-designer` → `/system-designer` → `/to-tickets` → `/implement` per issue → `/closeout`.
Phases 0–3 write their artifacts to `docs/features/<slug>/`; small fixes skip the chain and go straight to `/implement`.

`/implement <issue#>` takes one `ready-for-agent` issue to an open PR:
spec check → branch → `/tdd` → `/code-review` + fix → live browser QA → push (triggers cloud CI) → PR.
The full local `npm run ci` gate is not run as part of this flow - only cloud CI, at push/PR time - to keep the loop fast; run it by hand if you want the stricter local gate.
It stops at the PR and never merges. Run one issue per session - but sessions no longer queue behind
each other: every Conductor workspace gets its own Postgres, its own ports and its own database
(`npm run dev:where`), so issues can be implemented and browser-QA'd in parallel.

Because issues run in parallel, main may move while you work. Before pushing, rebase your branch onto
`origin/main` and re-run the full test suite after the rebase - especially the RBAC and nav contract
tests - even if none of your own files conflicted. Two individually green PRs have broken main at those
tests before (the #146 hotfix); rebase-then-retest catches that class before the PR does.

### Issue tracker

Issues live in **GitHub Issues** on `bruhanand/KDPS`, used via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five triage states each map to a repo label of the same name: `needs-triage`, `needs-info`, **`ready-for-agent`**, `ready-for-human`, `wontfix`. `ready-for-agent` is tool-neutral — any AI agent picks up work with `gh issue list --label ready-for-agent`. (It replaced the tool-specific `Sandcastle` label on 25 Jul 2026.) See `docs/agents/triage-labels.md`.

### Domain docs

**Single-context**: one root `CONTEXT.md`, ADRs in `docs/my-understanding/system-design/adr/`. See `docs/agents/domain.md`.

## Browser use

Drive the app with whichever browser tooling the session has. Anand develops in the **Claude app**, so
`mcp__claude-in-chrome__*` is the normal case; `mcp__chrome-devtools__*` is the terminal equivalent.
Both can drive the page, screenshot it, and read network requests and console messages, which is what
QA'ing an ERP screen needs.

Claude in Chrome drives Anand's own browser: open a **new tab**, never reuse one, log out or use a fresh
profile before testing a role (a pass that ran as whoever was signed in proves nothing), and never trigger
an alert or confirm dialog - it freezes the session until he dismisses it by hand.

The recipe (preconditions, flows, what to assert) is `.claude/skills/implement/LIVE-QA.md`.

*(gstack is no longer installed in this project; its `/browse` rule was removed on 26 Jul 2026.)*
