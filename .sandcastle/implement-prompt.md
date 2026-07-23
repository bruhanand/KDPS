# TASK

Fix issue {{TASK_ID}}: {{ISSUE_TITLE}}

Pull in the issue using `gh issue view {{TASK_ID}} -R bruhanand/KDPS --comments`.
Every outbound slice has a parent PRD issue — pull that in too, and read the
whole thing, not just the section that names your slice.

Only work on the issue specified.

Work on branch {{BRANCH}}. Make commits and run tests.

# CONTEXT

Here are the last 10 commits:

<recent-commits>

!`git log -n 10 --format="%H%n%ad%n%B---" --date=short`

</recent-commits>

# READ BEFORE YOU DESIGN ANYTHING

This is a money system for a real retailer. Read these first, in this order:

1. **`CONTEXT.md`** at the repo root — the domain language, the 12 rules, the
   kernel contracts, and the locked money decisions. This is the build briefing.
2. **`docs/my-understanding/system-design/adr/`** — the ratified ADRs touching
   the area you are about to change.
3. The design folder for the module your slice belongs to, under
   `docs/my-understanding/system-design/` (outbound work is `03-outbound/`).

Two hard rules that override anything you might infer from the code:

- **A design that breaks one of the 12 rules must change the rule consciously
  first**, on `docs/my-understanding/system-design/00-system-architecture.html`.
  You are not authorised to do that. If your slice appears to require it, stop,
  comment on the issue explaining the conflict, and make no further changes.
- **If your change contradicts a ratified ADR, say so explicitly** in your issue
  comment and in the commit body. Never override one silently.

Use the vocabulary the glossary defines. If the concept you need has no term
yet, that usually means you are inventing language the project doesn't use.

# EXPLORATION

Explore the repo and fill your context window with relevant information that will
allow you to complete the task.

Pay extra attention to test files that touch the relevant parts of the code, and
to `app/backend/core` — the kernel — whose contracts your slice must go through
rather than around.

# EXECUTION

If applicable, use RGR to complete the task.

1. RED: write one test
2. GREEN: write the implementation to pass that test
3. REPEAT until done
4. REFACTOR the code

Model changes ship with their migration in the same commit. `makemigrations
--check --dry-run` is part of the gate, so a missing migration fails the build.

# FEEDBACK LOOPS

The acceptance gate is:

```
npm run ci
```

That is the whole thing — backend (`ruff format --check`, `ruff check`, `mypy`
strict on core+config, `makemigrations --check`, `lint-imports`, `pytest`) and
frontend (`tsc --noEmit`, `vitest run`). Run it before every commit, and again
before you declare the task complete.

While iterating you can run the halves separately — `npm run ci:backend` and
`npm run ci:frontend` — but the full gate has to be green at the end.

Notes on this sandbox:

- PostgreSQL is already running and `DATABASE_URL` is set. The kernel's
  append-only ledgers and docstatus FSM are enforced by database triggers, so
  never reach for SQLite or an in-memory database to make a test pass.
- Backend commands go through `uv` from `app/backend` (e.g.
  `uv run pytest core/tests -q`, `uv run python manage.py migrate`).
- The frontend uses **yarn**, not npm. Never run `npm install` in `app/frontend`.
- Nine suites under `app/backend/tests/` are black-box tests against a live API
  and will report as *skipped* unless a server is running. That is expected and
  correct — it is not a failure, and it is not something to "fix". If your slice
  needs them, boot the server yourself:
  `cd app/backend && uv run uvicorn server:app --host 0.0.0.0 --port 8001 &`

Never weaken an assertion to make a suite green. If a kernel anti-cheat test
starts failing, your change is wrong, not the test.

# COMMIT

Make a git commit. The commit message must:

1. Use the repo's `scope: subject` form in the imperative — e.g.
   `outbound: add in-transit stock bucket`. Scopes in use: `core`, `masters`,
   `inbound`, `outbound`, `ptmapper`, `stockledger`, `finledger`, `frontend`,
   `agents`, `docs`, `ci`.
2. Reference the issue and its parent PRD.
3. State the key decisions made, and any ADR or rule they lean on.
4. Note blockers or anything left for the next iteration.

Keep it concise. Skip the file list — git already has it.

# THE ISSUE

If the task is not complete, leave a comment on the issue with what was done,
what is left, and anything a human needs to rule on:
`gh issue comment {{TASK_ID}} -R bruhanand/KDPS --body "..."`

Do not close the issue - this will be done later.

Once complete, output <promise>COMPLETE</promise>.

# FINAL RULES

ONLY WORK ON A SINGLE TASK.
