# Coding Standards

Loaded by the reviewer agent via `@.sandcastle/CODING_STANDARDS.md`. These are the
rules that hold across every slice of the KDPS system. Slice-specific design lives
in `CONTEXT.md` and the ADRs — read those too; this file is only the house style.

## The kernel is not negotiable

`app/backend/core` is the kernel. A business module may use it; it may never work
around it. Reject a change that does any of the following:

- **Writes a ledger directly.** Documents write ledgers. A module that inserts a
  stock or financial ledger row without a `core.Document` behind it is wrong,
  even if the numbers come out right.
- **Bypasses `post_entries`.** Financial postings go through the balanced GL
  helper. Single-entry "running balance" updates are a known alpha debt, not a
  pattern to copy.
- **Stores money as anything but integer paise.** No floats, no `Decimal` rupees,
  no `float(...)` anywhere near a money path.
- **Mutates or deletes a posted ledger row.** The ledgers are append-only and the
  database enforces it with triggers. Corrections are new reversing entries.
- **Sets a document status by assignment.** `docstatus` moves through the FSM.
  Derived status is derived — if the kernel forbids storing it, don't store it.
- **Imports `config` from `core`.** The kernel knows nothing about the project
  wiring layer. `lint-imports` enforces this and two other contracts; a change
  that "fixes" a contract violation by editing `pyproject.toml` is a red flag.

## Domain invariants

- **SKU = Style × Size × Color.** Anything that collapses stock to style level is
  a defect, however convenient.
- **Ownership × return-terms are two axes**, not one enum. Labels like
  "SOR"/"Outright"/"Hybrid" are derived from the pair, never stored as the truth.
- **GST is date-effective, slab-based data** — never a constant in code.
  Bihar and Jharkhand are distinct persons; cross-state movement is a taxable supply.
- **Cost comes from P RATE directly.** Never strip GST out of it to "derive" a cost.
- **Profitability is derived** — cost at stock-in, revenue at sale. Never a field
  someone types.
- **Flag, don't block.** Anomalies get surfaced for a human; they do not stop the
  store from trading.
- **Variation is data, not code.** A new brand, offer shape or commercial model
  must be a row, not a branch.

## Python (app/backend)

- Ruff is the formatter and the linter — `ruff format --check` and `ruff check`
  both gate. Line length 100, target py312.
- `mypy --strict` covers `core` and `config`. The strict surface grows with the
  code and never shrinks; don't move a module out of it to make a check pass.
- No `# type: ignore` or `Any` on a money path without a comment saying why.
- Every model change ships its migration in the same commit.
  `makemigrations --check --dry-run` is part of the gate.
- Keep business rules in the module, not in views. Views validate and delegate.

## TypeScript (app/frontend)

- `tsc --noEmit` gates. No `any`, no non-null `!` to silence the compiler, no
  `@ts-expect-error` without a reason on the line above.
- Money is formatted for India — `₹28,50,000`, Lakh/Crore grouping, never a bare
  `toLocaleString()` default.
- Colours and spacing come from the design tokens. `--navy` is text; `--navy-fill`
  is a background — they are not interchangeable, and hard-coded hex breaks the
  Light/Dark theme.
- Components stay presentational; fetch and transform above them.

## Tests

- Postgres or nothing. The kernel's guarantees are database triggers, so a test
  that passes on SQLite has proved nothing.
- A behaviour change without a test that fails before it and passes after it is
  not done.
- Test names say the expected behaviour, not the function name.
- Never weaken an existing assertion to make a suite green. If a kernel
  anti-cheat test now fails, the change is wrong, not the test.

## Commits

- `scope: subject` in the imperative — `outbound: add in-transit stock bucket`.
  Scopes in use: `core`, `masters`, `inbound`, `outbound`, `ptmapper`,
  `stockledger`, `finledger`, `sell`, `storefront`, `frontend`, `agents`,
  `docs`, `ci`.
- One concern per commit. Say what changed and why; skip the file list, git has it.

## General

- Match the surrounding code — its naming, its comment density, its idiom.
- Comments explain *why*, never *what*. Delete a comment that restates the line.
- No commented-out code and no dead branches left "for later".
- Deliverables a human reads are HTML, never markdown.
