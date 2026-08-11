# AGENTS.md

Guidance for **any coding agent** working in this repository - Claude Code, Codex, Cursor, Antigravity or anything else.

Three documents run a session, in this order:

1. This file - how to operate in the repo.
2. [`CONTEXT.md`](CONTEXT.md) - the domain, the 12 rules, the kernel contracts, and the locked + CA-gated money decisions. **Read it before building anything**; its rules bind regardless of what the code says.
3. [`docs/agents/dev-process.md`](docs/agents/dev-process.md) - the phase chain. Read it before any feature work.

`README.md` is how to run the app; `DEPLOY.md` is the Render alpha.

## What this project is

Anand is the consultant/architect designing and building an operating system for **KDPS Lifestyle Pvt Ltd** - a multi-brand Indian fashion retailer (Bihar & Jharkhand, 50+ stores/warehouses, 20,000+ SKUs, 40+ brands) currently running on per-store POS + Tally + Excel.

**Anand designs the system himself.**
The client's own plans (PRD, "Definitive Plan", phasing) live in `docs/client-requirements-docs/` and are **requirements input only, not the design**.
The cancelled "Phase-1" plan is in `__archive/` - never build from it.

## The code is the truth

The system is built and live (alpha): a Django backend (`app/backend` - kernel `core` plus one app per module) and a React/TypeScript PWA (`app/frontend`), auto-deploying to a Render alpha.
**What exists and how it behaves is answered by reading the code and git history, never by a document.**
The design corpus (`docs/my-understanding/system-design/`) largely predates the build; treat it as input and background - where a document and the code disagree, the code wins, and you note the drift.
Do not add "where things stand" status prose to instruction files; it goes stale the day after it is written.

The exceptions that bind regardless of the code are all in `CONTEXT.md`: the 12 rules, the kernel contracts, the locked money decisions and the CA-gated list.
Code that breaks one of those is a bug even when it is on `main`; changing one is a conscious decision by Anand, never a drive-by edit.

New work enters through the dev process and gets its own fresh spec and design under `docs/features/<slug>/` - never a rebuild from an old corpus doc.
Pace: no fixed timeline - ASAP with quality, one verified vertical slice at a time.
Current focus: end-of-season sale (EOSS); accounting and finance comes next.
The prioritized gap register is `docs/agents/improvement-plan.md` - read it before picking new work; feature work is paused until its Phase 0 closes.

One recurring live duty sits outside feature work: **month-start brand reports** (1st week of every month) in `docs/data-from-kdps/monthly-reports-april-may-2026/`, via the `kdps-report`, `discount-audit-v2`, `kdps-offer` and `store-dashboard` skills.

## Folder map

`docs/PROJECT-MAP.html` is the human-readable index - keep it updated whenever folders or project status change.

| Folder | What it is |
|---|---|
| `docs/my-understanding/` | **Anand's design work.** `system-design/` = the design corpus (architecture + D1-D9 module designs + ADRs) - input, may lag the code; `workflow/` = how KDPS works today (`KDPS-current-workflow.pdf`, staff interviews) - the business ground truth. |
| `docs/data-from-kdps/` | **Raw material from the client:** reference data (PT formats, real invoices), Q&A answers, bank statements, the monthly-report duty folder, per-store analyses, transfer data. |
| `docs/client-requirements-docs/` | Client's asks (PRD, Definitive Plan, demand registers). **Requirements only - not the design.** |
| `docs/04-client-docs/` | Client-facing per-module deliverables. Living documents until the architecture is final. |
| `docs/meetings/` | One folder per meeting, named `YYYY-MM-DD-topic/` (audio + transcript + minutes). |
| `code/` | `pdf-to-pt/` Invoice-to-PT pipeline (see its `BLUEPRINT.md`); `scripts/generate-pdf.mjs` = HTML-to-PDF helper; `scripts/trace-logo.py` = logo tracer. |
| `app/` | **The built system.** `backend/` = Django, `frontend/` = React/TS PWA. Run: `README.md`; deploy: `DEPLOY.md` + `render.yaml`. |
| `__archive/` | Stale material. **Never design or build from here.** |
| `docs/agents/` | **The dev process, tool-neutral:** phase chain, tracker commands, labels, domain-doc layout, CI notes, gap register. |
| `.agents/skills/` | **The skills, tool-neutral.** One folder per skill; `.claude/skills/` symlinks here so Claude Code sees the same set. |
| root | `MOU-KDPS-Anand.pdf` (engagement), `CONTEXT.md`, `README.md`, `DEPLOY.md`, `DASHBOARD.html`, `docs/PROJECT-MAP.html`, `AGENTS.md` (this file; `CLAUDE.md` symlinks to it), `memory/PRD.md` + `memory/test_credentials.md`. |

House rules: new design discussion → its own numbered folder under `docs/my-understanding/system-design/`; new meeting → `docs/meetings/YYYY-MM-DD-topic/`; new month's reports → month folder under `docs/data-from-kdps/monthly-reports-april-may-2026/`; superseded docs → move to `__archive/`, don't delete.

## Working norms

- **Deliverables are HTML files, never markdown**, for anything Anand will read or share (PDF via `code/scripts/generate-pdf.mjs` when needed).
- **Plain, non-technical language** in chat and client docs. Short answers; do only what's asked.
- **Understand before design:** current workflow first (`docs/my-understanding/workflow/`), then client wants, then design. When details are ambiguous, check `KDPS-current-workflow.pdf` and meeting minutes rather than inventing.
- **Engineering-led build order:** build by architecture sequence, not the client's wishlist order.
- **`npm run ci` is the local acceptance gate**; cloud CI runs the same ground on push. The gate's job list, its traps, and the API-client drift rule live in [`docs/agents/ci.md`](docs/agents/ci.md) - read that before touching CI config, the `mypy` scope, or any serializer/view/URL.

## Where the instructions live

Three tiers, each written once:

| Tier | Where | Read by |
|---|---|---|
| Repo instructions | `AGENTS.md` (this file); `CLAUDE.md` is a symlink to it | every agent, always |
| The dev process | `docs/agents/dev-process.md` + `docs/agents/phases/*.md`, `labels.md`, `issue-tracker.md`, `domain.md`, `ci.md` | every agent, when a phase runs |
| The skills | `.agents/skills/<name>/SKILL.md`; `.claude/skills/<name>` is a symlink to each | every agent; Claude Code discovers them through the symlinks |

- **Never edit through a symlink's name.** Edit `AGENTS.md`, not `CLAUDE.md`; edit `.agents/skills/<name>/`, not `.claude/skills/<name>/`.
- **A new skill needs its symlink:** create `.agents/skills/<name>/`, then `ln -s ../../.agents/skills/<name> .claude/skills/<name>` in the same commit.

## The dev process

**`docs/agents/dev-process.md` is the whole process** - the chain (`triage` → `spec` → `design` → `to-tickets` → `implement` per issue → `closeout`), the label rules, the money-slice rules, and the model policy.
Each phase's method is a document under `docs/agents/phases/`; a skill file is only a pointer at one, so read the phase document, not the skill.

Issues live in GitHub Issues on `bruhanand/KDPS`, used via the `gh` CLI: commands in `docs/agents/issue-tracker.md`, labels in `docs/agents/labels.md`.
Domain docs are single-context: one root `CONTEXT.md`, ADRs in `docs/my-understanding/system-design/adr/` - see `docs/agents/domain.md`.

## QA and browsers

**QA'ing a screen means writing a Playwright spec, not driving a browser by hand.**
Specs live in `app/frontend/e2e/`, are committed with the change they QA, and run with `npm run e2e` against the stack `npm run dev` owns.
The method and toolkit are in `docs/agents/phases/live-qa.md`.
Interactive browser tooling (`mcp__claude-in-chrome__*`, `mcp__chrome-devtools__*`) is for exploring - reproducing a report, looking before you know what to assert - never for recording a verdict. A verdict is a spec.
