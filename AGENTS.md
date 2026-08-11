# AGENTS.md

Guidance for **any coding agent** working in this repository - Claude Code, Codex, Cursor, Antigravity or anything else.

> **Before building anything, read [`CONTEXT.md`](CONTEXT.md) (repo root)** - the domain language, the 12 rules, the kernel contracts, and the money-critical locked + CA-gated decisions.
> This file is workflow and project guidance; `CONTEXT.md` is the domain and kernel context; `README.md` is how to run it.

## What this project is

Anand is the consultant/architect designing and building an operating system for **KDPS Lifestyle Pvt Ltd** — a multi-brand Indian fashion retailer (Bihar & Jharkhand, 50+ stores/warehouses, 20,000+ SKUs, 40+ brands) that currently runs on per-store POS + Tally + Excel.

**Anand designs the system himself.** The client supplied their own plans (PRD, "Definitive Plan" with 10 AI agents, an 8-month phasing) — those are in `docs/client-requirements-docs/` and are **requirements input only, not the design**. Do not treat the client's architecture, agent list, tech stack, or phasing as decisions. The cancelled "Phase-1" plan is in `__archive/` — never build from it.

## The code is the truth

The system is built and live (alpha): a Django backend (`app/backend` - kernel `core` plus one app per module) and a React/TypeScript PWA (`app/frontend`), auto-deploying to a Render alpha (Postgres 16, Singapore region).
Stack ratified in ADR-0001: no backend-as-a-service; ERPNext not adopted, but its GST data model is borrowed.

**What exists and how it behaves is answered by reading the code and git history, never by a document.**
The design corpus (`docs/my-understanding/system-design/`) largely predates the build; requirements changed during it and not every change was written back, so parts of it are stale.
Treat it as input and background: where a document and the code disagree, the code wins - note the drift instead of building from the doc.
Do not add "where things stand" status prose to this file or the other instruction files; it goes stale the day after it is written.

What stays binding regardless of the code: the 12 rules, the kernel contracts, the locked money decisions and the CA-gated list, all in `CONTEXT.md`.
Code that breaks one of those is a bug even when it is on `main`; changing one is a conscious decision by Anand, never a drive-by edit.

New work enters through the dev process below and gets its own fresh spec and design under `docs/features/<slug>/` - never a rebuild from an old corpus doc.
Pace: no fixed timeline - ASAP with quality, one verified vertical slice at a time.
Current focus: end-of-season sale (EOSS); accounting and finance comes next, as a new design discussion.
The prioritized gap register is `docs/agents/improvement-plan.md`.

One recurring live duty sits outside feature work: **month-start brand reports** (1st week of every month) in `docs/data-from-kdps/monthly-reports-april-may-2026/`, via the `kdps-report`, `discount-audit-v2`, `kdps-offer` and `store-dashboard` skills.

## Folder map

`docs/PROJECT-MAP.html` is the human-readable index — keep it updated whenever folders or project status change.

| Folder | What it is |
|---|---|
| `docs/my-understanding/` | **Anand's design work.** `system-design/` = the design corpus (architecture + D1–D9 module designs + ADRs) - **input, may lag the code**; `workflow/` = how KDPS works today (`KDPS-current-workflow.pdf`, staff interviews) - the business ground truth the design was derived from. |
| `docs/data-from-kdps/` | **Raw material received from the client:** reference data (PT formats, real invoices, samples), Q&A answers, bank statements, the monthly-report duty folder, per-store analyses, transfer data. |
| `docs/client-requirements-docs/` | Client's asks (PRD, Definitive Plan, `client-demands.html`, `ERP-requirements-register.html`, `change-request/`). **Requirements only — not the design.** |
| `docs/04-client-docs/` | Client-facing per-module deliverables (Vendor, Goods-Inward, Outbound, Payments, Offers, POS requirements). Living documents — they change until the architecture is final. |
| `docs/meetings/` | One folder per meeting, named `YYYY-MM-DD-topic/` (audio + transcript + minutes). |
| `code/` | `pdf-to-pt/` Invoice→PT pipeline (see its `BLUEPRINT.md`); ~150 real invoices in `document/` for testing. `scripts/generate-pdf.mjs` = HTML→PDF helper; `scripts/trace-logo.py` = traces the client's logo PNG into the app's vector logo component and app icons. |
| `app/` | **The built system** (on `main`, deployed to a Render alpha). `backend/` = Django, kernel `core` + one app per module; `frontend/` = React/TS PWA. Run: `README.md`; deploy: `DEPLOY.md` + `render.yaml`. |
| `__archive/` | Stale material (cancelled Phase-1, old timeline, old direction doc, old drafts/decks). **Never design or build from here.** |
| `docs/agents/` | **The dev process, tool-neutral.** The phase chain, the issue tracker's commands, the triage labels, the domain-doc layout, and the go-live gap register. Plain markdown any agent can read. |
| `.agents/skills/` | **The skills, tool-neutral.** One folder per skill, each with a `SKILL.md`. `.claude/skills/` is a directory of symlinks pointing here, so Claude Code sees the same set - see "Where the instructions live" below. |
| root | `MOU-KDPS-Anand.pdf` (engagement/scope), `CONTEXT.md` (build-context briefing), `README.md` (how to run), `DEPLOY.md` (Render alpha steps + seeded logins), `DASHBOARD.html` (project command centre), `docs/PROJECT-MAP.html` (index), `AGENTS.md` (this file; `CLAUDE.md` symlinks to it), `memory/PRD.md` + `memory/test_credentials.md` (build log + seeded test logins). |

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
- Repo-level commands exist now. `npm run ci` (ruff · mypy strict · migration check · schema-drift check · import-linter · pytest · **API-client drift** · tsc · vitest) is the **local acceptance gate**; `.github/workflows/ci.yml` runs the same ground on push (see the job list below); `docker-compose` gives a local Postgres and pre-commit hooks run ruff/mypy. `npm run api:client` regenerates the PWA's typed API client from the backend's own OpenAPI document, and must be run in the same commit as any serializer/view/URL change - it is generated, never hand-edited (#192). See `README.md` (run) and `DEPLOY.md` (Render).

Cloud CI (`.github/workflows/ci.yml`) triggers on **push only** - no `pull_request` (the push run already covers the PR head) and, deliberately, **no `paths-ignore` on the trigger**: a run a path filter suppresses reports no check at all, which is indistinguishable from a run GitHub silently dropped and makes the workflow useless as a required check (#301). The workflow therefore always starts, and filtering happens per job. Jobs: `changes` (which trees moved), `lint` (ruff format · ruff check · `mypy .` · import-linter), `backend-kernel` (kernel anti-cheat + migration-drift guards), `backend-suite` (**8 parallel shards** via `pytest-split`, each with its own Postgres + seed + uvicorn), `api-client` (regenerates `app/frontend/src/lib/api-schema.ts` from the backend's own OpenAPI document and refuses a difference - #192), `frontend` (build + tsc + vitest), and `ci` - an always-run job that aggregates the rest and is **the single required check on `main`**. Typical full run ~4-5 min; a push touching neither tree finishes green in well under a minute.

Shard balance comes from `app/backend/.test_durations`. Regenerate it when the suite's shape changes materially: `uv run pytest tests --store-durations`.

The `lint` job runs **`mypy .`** - the whole backend, not a list of apps (#292 closed the `core config` hole). Keep that string identical in the four places it lives: `package.json` (`ci:backend`, `ci:backend:fast`), this workflow, and `.pre-commit-config.yaml`. Two traps worth knowing before you widen or narrow it. Django's `admin.ModelAdmin` is **not subscriptable at runtime**, so `class FooAdmin(ModelAdmin[Foo])` raises `TypeError` and crashes admin autodiscover at import - DRF's serializers and generic views, and Django's `Manager`, *are* subscriptable; and `from __future__ import annotations` does not defer **base-class** expressions, only annotations, so a bad base class is an import-time crash rather than a type error.

## Agent instructions

### Where the instructions live

Three tiers, and the rule is that each tier is written once:

| Tier | Where | Read by |
|---|---|---|
| Repo instructions | `AGENTS.md` (this file); `CLAUDE.md` is a symlink to it | every agent, always |
| The dev process | `docs/agents/dev-process.md` plus `docs/agents/phases/*.md`, `labels.md`, `issue-tracker.md`, `domain.md` | every agent, when a phase runs |
| The skills | `.agents/skills/<name>/SKILL.md`; `.claude/skills/<name>` is a symlink to each | every agent; Claude Code discovers them through the symlinks |

Consequences worth knowing before you edit anything here:

- **Never edit through a symlink's name.** Edit `AGENTS.md`, not `CLAUDE.md`; edit `.agents/skills/<name>/`, not `.claude/skills/<name>/`. They are the same file, but naming the real path keeps the diff honest.
- **A new skill needs its symlink.** Create it under `.agents/skills/<name>/`, then `ln -s ../../.agents/skills/<name> .claude/skills/<name>` in the same commit, or Claude Code will not see it.

### The dev process

**`docs/agents/dev-process.md` is the whole process.** Read it before any feature work. Each phase's
method is a document under `docs/agents/phases/`; a skill file is only a pointer at one of them, so read
the phase document, not the skill.

The chain, each phase invoked by hand and stopping for approval:
`triage` → `spec` → `design` → `to-tickets` → `implement` per issue → `closeout`.
Those are skill names; invoke them however your tool does (Claude Code: `/spec`). `spec` and `design`
write to `docs/features/<slug>/`; a bug fix or small tweak skips the chain and goes straight to
`implement`.

Two rules bind every phase, and both have cost real work in this repo:

- **The issue body is the spec.** A ruling in a comment while the body holds the old spec is two specs
  on one issue, and an agent will faithfully build the wrong one (#96). Rewrite the body first.
- **Implement with a mid-tier model, review with the strongest one available**, and never let the model
  that wrote the code be the only one grading it. A thin design document is a design-phase failure, not
  a reason to reach for a stronger model: send it back to `design`.

`implement` stops at an open PR and never merges. Run one issue per session; sessions do not queue,
because every Conductor workspace has its own Postgres, ports and database (`npm run dev:where`).
Rebase onto `origin/main` and re-run the tests after the rebase before pushing, even if nothing
conflicted - two individually green PRs have broken main at the RBAC and nav contract tests before
(the #146 hotfix).

### Issue tracker

Issues live in **GitHub Issues** on `bruhanand/KDPS`, used via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Gap register

`docs/agents/improvement-plan.md` (7 Aug 2026) is the single prioritized register of every known gap between the current build and go-live, phased Phase 0 (pause: correctness + hygiene) → pilot → go-live.
Read it before picking new work; it marks which items are blocked on human/CA rulings. Feature work is paused until its Phase 0 is closed.

### Issue labels

A label answers one question: may an agent start on this right now. **No label** means nobody has
looked, so no agent may start; **`ready`** means the body is a complete spec and any agent can pick it
up; **`blocked`** means it needs Anand, with the last comment saying what for. **`money`** is an
orthogonal tag for ledgers, postings, GST, valuation and the document FSM - it changes the review shape
and the escalation rule, so `implement` reads it before opening any document. See `docs/agents/labels.md`,
which also carries the migration mapping from the older five-state scheme still live on the tracker.

### Domain docs

**Single-context**: one root `CONTEXT.md`, ADRs in `docs/my-understanding/system-design/adr/`. See `docs/agents/domain.md`.

## Browser use

QA'ing an ERP screen needs a driver that can click the page, screenshot it, and read network requests
and console messages. Use whichever one your session has; if it cannot do all four, say so rather than
claiming a pass you could not verify.

Three rules hold whatever the tool:

- **A fresh session per role.** Log out or use a clean profile before testing a role. A pass that ran as
  whoever happened to be signed in proves nothing.
- **A new tab, never someone else's.** The driver may be attached to Anand's own browser.
- **Never trigger an alert or confirm dialog.** It freezes the session until a human dismisses it by hand.

In practice: Anand develops in the **Claude app**, so `mcp__claude-in-chrome__*` is the normal case and
`mcp__chrome-devtools__*` is the terminal equivalent. Both satisfy the four capabilities above.

The recipe (preconditions, flows, what to assert) is `docs/agents/phases/live-qa.md`.
