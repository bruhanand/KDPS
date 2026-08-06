# KDPS improvement plan - the gap register

Compiled 7 August 2026 from a full repo review plus the open issue queue.
This is the single document listing every known gap between the current build and the goal.
It was agreed with Anand that no new feature work starts until Phase 0 below is done.

**Audience: Claude Code agents.**
Read [`CONTEXT.md`](../../CONTEXT.md) (domain + kernel rules) and [`docs/agents/dev-process.md`](dev-process.md) (how work flows) before acting on anything here.
This document tells you *what* needs doing and in *what order*; those documents tell you *how*.

## The goal

KDPS stores running their daily business on this system with real money, fully off the old per-store POS + Tally-only + Excel setup.
Concretely: pilot one store first, then go live across stores, with Tally remaining the statutory book of record fed by sync.

## How to use this document

- Work top-down: Phase 0 before Phase 1, Phase 1 before Phase 2.
- One issue per session via `/implement`, per the dev process.
- Items marked **BLOCKED-ON-HUMAN** must not be implemented until Anand (or the CA) rules.
  Do not guess a ruling and build on it.
- Issue numbers refer to GitHub Issues on `bruhanand/KDPS` (use `gh`).

## Ticket map (published 7 Aug 2026)

Every gap below now exists as a GitHub issue, grouped under three milestones: "Phase 0 - the pause (correctness + hygiene)", "Phase 1 - pilot readiness", "Phase 2 - live money / go-live".
Each ticket carries the approach, acceptance criteria, its process route (`/implement` directly vs the full dev-process chain), and its blocking edges, so it is a self-contained discussion unit.

New tickets created from this register: #290 (CA session - the five money rulings + GST posting split), #291 (rulings roll-up - eight product decisions), #292 (CI full gate), #293 (auto-commits on main, decision), #294 (auth hardening for pilot), #295 (retire demo credentials), #296 (store open/close, full chain), #297 (Tally sync, spike now + chain after #290), #298 (payments & settlement, full chain), #299 (D9 migration design), #300 (data residency decision).

#158 was retitled as the seed umbrella; #205, #251, #252 and #256 are folded into it as duplicates and close when it lands.
Ruling-gated tickets carry `needs-info` (#262, #215) or `ready-for-human` (#200); every other Phase 0 ticket is `ready-for-agent`.
Agents pick work with `gh issue list --label ready-for-agent --milestone "Phase 0 - the pause (correctness + hygiene)"`.

## Phase 0 - the pause: correctness and hygiene (do these before any new feature)

### 0.1 Money integrity (highest priority)

- **#220 - Cancelling a sale or a return leaves its credit note live and its ledger legs standing.**
  The ledger is append-only by DB trigger, so the only correct cure is posting reversal legs and closing the credit note; today neither happens.
  Done when: cancelling a sale/return posts balancing reversal entries through `core.posting.post_entries`, voids the credit note, and a regression test proves the trial balance and stock both return to the pre-document state.
  This is the worst open defect in the system.

### 0.2 Scope and RBAC leaks (treat as one class, not three point-fixes)

This fail-open class has recurred (see memory `scope-gate-must-match-its-rows` and the #146 hotfix history).
When fixing any one of these, sweep sibling endpoints for the same pattern and add the `X-KDPS-Unit` switcher test.

- **#234 - Booking list shows every store's bookings to any store login.** Read-scope fail-open.
- **#236 - finledger/health fires and 403s for brand_manager (Books Health widget).** The widget must not render (or the endpoint must be permitted) for roles that cannot read it; a 403 in the console on every dashboard load is not acceptable.
- **#200 - Store manager cannot approve anything at the till.** Related to the open store-manager Sell-rung decision (see Open Rulings below); triage carefully - part of this may be BLOCKED-ON-HUMAN.

### 0.3 POS counter reliability

- **#257 - Billing scan box can silently drop a scan under rapid back-to-back scans.** A dropped scan is silently lost money.
- **#168 - Scanning the same new barcode rapidly duplicates its row on the scan screen.** Same race family, on the inbound scan screen.
- **#262 - A mistyped GSTIN still prints a tax split on the bill.** GST correctness on paper; validate GSTIN (checksum + state code) before printing a split.

### 0.4 Governance integrity

- **#224 - Re-running the seed silently undoes an access change two administrators agreed.**
  Seeds must never overwrite the live RBAC matrix (access changes are two-admin approved and instant; see memory `access-changes-are-instant` and `sheet-cells-are-not-yours-to-override`).

### 0.5 The demo seed is broken five ways

`seed_demo_data` currently cannot stand up a fresh whole system, which also blocks honest end-to-end QA.
Fix as one piece of work if possible; the failures interlock:

- **#251** - RTV seeding fails (PE-CHK-BLU-42 not receivable at DEO), rolling back all demo data.
- **#252** - RTV and V-flip steps crash on unpriced SKUs, rolling back the whole seed.
- **#256** - RTV/V-flip steps price SKUs at stores that never received them.
- **#205** - a store-scoped user cannot post the demo PT.
- **#158** - a warehouse person cannot post value, stopping the seed halfway.
  Done when: `seed_demo_data` runs green on a fresh database, twice in a row (idempotent), without violating #224.

### 0.6 Engineering gate (make green mean green)

- ~~Local `npm run ci` is red: 30 ruff errors in `app/backend`.~~ **Fixed 7 Aug** together with main's red CI (see below).
- **Correction (7 Aug):** the long-standing caveat that "cloud CI runs only pytest + frontend build" is **wrong**, and was inherited from a stale line in `CLAUDE.md`.
  `.github/workflows/ci.yml` has four jobs: `lint` (ruff format, ruff check, `mypy core config`, import-linter), `backend-kernel` (kernel anti-cheat suites), `backend-live` (migrate + seed + uvicorn + the API regression suites) and `frontend`.
  Main was red on 4-6 Aug *because* that gate works. Delete the stale caveat from `CLAUDE.md`.
- The two real gate holes that remain, both on **#292**:
  - The `frontend` job runs `yarn build` (tsc + bundle) and **never runs vitest**, so 850 tests in 58 files - including the shared offer/GSTIN/refund vector suites that stop the till's offline rules drifting from the server's - are invisible to CI. `package.json` already has `yarn ci` for this, and the whole suite runs in 9 seconds.
  - `mypy` covers only `core config`; every other app is untyped as far as CI is concerned.
- **#192 - The generated API client is about a thousand lines out of date.** Regenerate, diff-review, and add a CI drift check so it cannot silently rot again.

### 0.7 Declared-standard polish

- **#155** - Stock screens show money as plain numbers, not Indian format.
- **#198** - Ledger pages show raw rupee strings instead of Indian-grouped money.
  All money display must use the Lakh/Crore formatter (`₹28,50,000` style); sweep for other screens while there.
- **#215** - Label the POS Dashboard's collections card with the till's last sync time.

### 0.8 Process hygiene (needs a human decision, flag do not fix)

- Recent history on `main` is entirely `auto-commit for <uuid>` / `Auto-generated changes` commits, outside the PR flow.
  **BLOCKED-ON-HUMAN** (#293): Anand must decide whether direct auto-commits on `main` are intended; agents should not "fix" this unilaterally.
  **This is no longer theoretical.** Those commits broke main's CI on 4 Aug and it stayed red for two days: Emergent auto-commits carrying the bank-reconciliation / partner-settlement work landed on main unformatted (failing `ruff format --check` on the very files they touched) and added a `PARTNER_RECEIVABLE` GL account without a side in `finledger.health.ACCOUNTS`, failing the books-health guard. The PR flow would have caught both before main. Nothing announced the breakage either - main going red deserves a notification whichever way #293 is decided.
- ~~`docs/invoices/July-2026/` untracked~~ - committed 7 Aug alongside the tracked April and June invoices.

## Phase 1 - before a pilot store

### 1.1 Security hardening (consciously deferred for alpha; must close now)

- Remove/rotate demo credentials; real user provisioning for the pilot store.
- Close the JWT-in-`localStorage` deferral.
- Resolve the cookie/CSRF/SameSite trap: Render's split-origin deploy forces `SameSite=None`, which guts cookie-based CSRF protection (see memory `cookie-auth-csrf-samesite`).
  The likely right shape is serving the PWA and API from one origin; this is an architecture decision - propose, get Anand's sign-off, then build.

### 1.2 Hardware

- **#190 - Printer spike: browser to thermal receipt printing.** `ready-for-human`, has hardware lead time; no counter runs without receipts.
  Barcode label printing rides on the same spike's findings.

### 1.3 Outbound leftovers

- **#73** - warehouse distribution allocation grid (slice 6, `ready-for-human`).
- **#77** - alerts job: in-transit aging + return-window 30/15/7 (slice 9).
- **#79** - role-based landing + outbound navigation rework (slice 12).
- **#105** - fold Write-off into Stock Adjustment: one correction document, reason-coded (`ready-for-human`; write-off was never designed and is already broken - see memory `writeoff-was-never-designed`).

### 1.4 Missing module

- **Store open/close** - the one true gap the June completeness audit found; still undesigned and unbuilt.
  Needs the dev-process chain from `/feature-analyst` onward, not a direct build.

## Phase 2 - before live money / go-live

### 2.1 CA rulings (BLOCKED-ON-HUMAN, all five; highest-leverage single action is scheduling the CA meeting)

1. SOR/Consignment GST single-recognition (F9).
2. The 6-month deemed-supply clock.
3. Late freight arriving after PT.
4. Sold-before-PT.
5. The no-reposting rule.

Plus: the CGST/SGST/IGST posting split - bills print the split but the ledger posts one OUTPUT_GST (see memory `gst-split-prints-but-does-not-post`); settle with the CA together with the Tally slice design.

### 2.2 Remaining builds (designed, not built)

- **Tally sync** (D6, locked 20 Jun 2026) - the statutory book depends on it.
- **Payments & settlement** (D4, locked 18 Jun 2026).
- **D9 - migration & rollout design**: data migration from old POS/Tally/Excel, store onboarding sequence, Hindi training material.
  Must be designed before any go-live date is real.

### 2.3 Infrastructure decisions (BLOCKED-ON-HUMAN)

- Data residency: the alpha runs on Render Singapore; the in-India decision was deferred to exactly this milestone.

## Phase 3 - later / only if the sellable-product ambition becomes a plan

- D7 analytics/AI depth beyond what is built (agents, digests).
- Attendance & payroll (deferred by decision).
- Multi-tenancy retrofit: the build is deliberately single-tenant (zero tenant references in the backend); a sellable product would need `tenant_id` throughout, and the cost of retrofitting grows with every table added.

## Open rulings owed by Anand (do not implement without them)

- UPI charge-card amount-pin ruling (memory `upi-charge-card-and-the-wedge-patrol`).
- Day-summary two dials (memory `day-summary-and-daily-check`).
- Returns/exchanges three rulings (memory `returns-and-exchanges`).
- Plan-vs-scan on transfers (memory `transfer-approval-gate`).
- Store-manager Sell rung (memory `sheet-cells-are-not-yours-to-override`; interacts with #200).
- Customer-rail height/frame ruling (memory `customer-typeahead-and-the-rail-height`).

## Known-good - do not re-fix

- The double-entry spine is now broad: `post_entries` runs from `sell`, `outbound`, `finledger`, and `stockledger`, not just the PT-inward path.
  The old "vendor/cash ledgers are single-entry" caveat in `CLAUDE.md` is largely stale; the remaining holes are on the *reversal* side (#220).
- Append-only is DB-enforced (triggers reject UPDATE/DELETE/TRUNCATE on ledger + GL tables); money is integer paise; module boundaries are import-linter-enforced in `app/backend/pyproject.toml`.
- PRD issues **#67, #84, #104** are open as specs on purpose; they are reference material, not work items.

## Traps that have bitten before (read before touching related code)

- `app/frontend` uses **yarn**, never `npm install` there.
- Rebase onto `origin/main` and re-run the full suite (especially RBAC + nav contract tests) before every push; two green PRs have broken main before.
- Never `git stash` in this workspace; other agents share the tree.
- Any new till table = a new Dexie version.
- Till date logic must use `tillToday()` (IST), never the UTC day.
- Rules the till computes offline and the server recomputes must share ONE JSON vector file (`offers/vectors/`, `sell/vectors/`, mirrored in `src/till/*.vectors.test.ts`).
- A ruling posted as an issue comment is not a spec; rewrite the issue body before implementing.

## Verifying current state

```bash
gh issue list --state open --limit 60
```

```bash
cd app/backend && uv run ruff check .
```

```bash
npm run ci
```

Update this document as items close: strike the line, add the PR number, and keep the phase ordering intact.
When every Phase 0 item is closed, tell Anand; Phase 1 starts only on his go.
