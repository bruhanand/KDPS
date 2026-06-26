# ADR-0005 — CI gate & build-loop scripts

**Status:** Accepted 2026-06-25

## Context

The build loop gates on a root `test` and `typecheck`, but the stack is polyglot (TypeScript
frontend + Python/Django backend, ADR-0001). The gate must cover both sides — either failing
fails the command — and must encode the money anti-cheat: the ledger invariants, the cross-store
isolation proof, and the golden-file regression over the ~150 real invoices. The old (distrusted)
ADR-0005 reasoning is salvaged here; the decision is ratified under the confirmed stack and the
two-step posting (ADR-0004). One known stale reference in the old ADR — the GitHub remote
`bruhanand/KDPS` — is **UNCONFIRMED** and must be verified before CI runs against it.

## Decision

**The root `package.json` is the single entry point** that orchestrates both ecosystems. No heavy
monorepo tool (Nx / Turborepo / Bazel) — overkill for one dev + two apps; a light root-script
orchestrator suffices.

### Root scripts
- **`typecheck`** — `tsc --noEmit` (frontend) · **`mypy` + `django-stubs`** (backend) ·
  `import-linter` (ADR-0002 seam contracts) · `manage.py makemigrations --check` (migrations in
  sync) · **generated-API-client-in-sync check** (OpenAPI → TS client not stale, ADR-0001/0002).
- **`test`** — `vitest` (frontend) · `pytest` + `pytest-django` (backend) against a **real
  PostgreSQL** (not SQLite — SQLite hides the append-only triggers, integer-paise math and GST
  rounding). Includes the four money anti-cheat suites below.
- **`lint`** — ESLint + Prettier (frontend) · `ruff` (backend).
- **`ci`** — `typecheck && lint && test`. **Green is required to merge** — the loop's definition
  of "done."

### The four money anti-cheat test suites (foundation scope, real Postgres)
1. **Balanced postings — Σdebits = Σcredits.** Every posted document's legs sum to zero in
   integer paise; an unbalanced post is rejected (this is the `post_entries` contract, ADR-0006).
2. **Append-only enforced.** Tests run **as the restricted app DB role, not superuser** (otherwise
   the `REVOKE UPDATE/DELETE` is never exercised and CI goes false-green) and prove that UPDATE /
   DELETE on a ledger row is blocked by both the trigger and the grants; corrections are reversing
   posts.
3. **Cross-store / cross-entity isolation.** A Store User's queryset is provably unable to read
   another store's / entity's rows — the fail-closed scoping guarantee (ADR-0003), resolved
   against `LegalEntity → GSTIN → Store` (ADR-0007). Mandatory foundation coverage.
4. **Golden-file regression — the ~150 real invoices.** Each real invoice → its known PT /
   postings (Dr/Cr legs per commercial model). The golden set grows per vertical slice; a slice is
   not done until its events have golden files. **Money diffs are human-read** — a golden-file
   change that touches a rupee is never auto-accepted; it is reviewed by a person before the
   golden is updated.

### Typechecker choice
**mypy + django-stubs is the CI gate** (it understands Django model-field / Manager types via its
plugin, which pyright cannot). Pyright / Pylance is used in the IDE for speed only.

### The gate
CI (GitHub Actions) runs `ci` on every PR / branch push, with a **Postgres service container**;
green is required to merge. **The remote must be confirmed before this is wired** — the old ADR
hardcoded `bruhanand/KDPS`, which is unverified.

### Two speeds (process, on top of CI)
- **Money-touching code gets a mandatory human read + AI review even when green.**
- **Golden-file + ledger-invariant tests are written before the posting code** (TDD for money), so
  a passing suite means the rules held, not just that code ran.

## Consequences

- A single `test` failing on either ecosystem blocks the merge — seam checks (import-linter) and
  money correctness (golden / invariants / isolation) are part of "green."
- Tests run on real Postgres, so append-only triggers, integer-paise math and GST rounding are
  exercised exactly as in production.
- Money + GST-rounding + discount-split-back-to-lines golden tests are **foundation scope** (pure,
  cross-cutting, load-bearing) — built and exhaustively tested in `core` now, not deferred.
- The Tally tie-out + failure queue is itself a first-class slice (slice 7), and its reconciliation
  invariants extend these CI suites when it lands.

## Alternatives rejected

- **Pyright in CI** — cannot infer Django ORM types without the mypy plugin; kept to the IDE.
- **SQLite for tests** — hides the append-only triggers, integer-paise behaviour and GST rounding;
  real Postgres is mandatory.
- **Auto-accepting golden-file diffs** — a money regression would slip through silently; money
  diffs are human-read.
- **Nx / Turborepo / Bazel** — task-graph orchestration unneeded at one dev + two apps.

## Sources

- Kraken Engineering — static typing Python at scale with mypy + Django.
- Java Code Geeks / Django-CFG — mypy vs pyright trade-offs with Django.
- Graphite — managing multiple languages in a monorepo; monorepo.tools.
- Decision log (25 Jun): Q11 typed both ends, golden-file over the ~150 invoices, Tally tie-out as
  slice 7; remote `bruhanand/KDPS` unconfirmed.
