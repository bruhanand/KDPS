# TASK

Build issue {{TASK_ID}}: {{ISSUE_TITLE}}, on branch {{BRANCH}} (already checked
out).

Your brief is **`{{ART_DIR}}/slice-plan.md`** — read it first, whole. It
carries the acceptance criteria, the seams to build at, and the quoted rules
that bind this slice. It was written by an agent that read the full design
corpus so that you don't have to.

If the plan is silent on something you genuinely need, the sources are
`CONTEXT.md` (repo root) and the ADRs under
`docs/my-understanding/system-design/adr/` — go there for that specific
question only, not for a general read.

Only work on this issue.

# CONTEXT

Here are the last 10 commits:

<recent-commits>

!`git log -n 10 --format="%H%n%ad%n%B---" --date=short`

</recent-commits>

# EXECUTION

Use RGR at the seams the plan names:

1. RED: write one test
2. GREEN: write the implementation to pass that test
3. REPEAT until the acceptance criteria are covered
4. REFACTOR the code

Model changes ship with their migration in the same commit — the pipeline's
CI gate runs `makemigrations --check`, so a missing migration blocks the
merge.

# CHECKS — touched only, never the full gate

While working, check **only what you touched**:

- the test file(s) you wrote or extended: `uv run pytest <path> -q` from
  `app/backend`
- `uv run mypy core config` if you touched core or config
- `cd app/frontend && yarn typecheck` (and `yarn test` for suites you touched)
  if you touched the frontend

**Never run `npm run ci`.** The full gate takes ~16 minutes; in this pipeline
a dedicated ci-check phase runs `npm run ci:fast` after QA, and the host runs
it again on merged main. That is deliberate — your job is the touched files.

Sandbox notes:

- PostgreSQL is already running and `DATABASE_URL` is set. The kernel's
  append-only ledgers and docstatus FSM are enforced by database triggers, so
  never reach for SQLite or an in-memory database to make a test pass.
- Backend commands go through `uv` from `app/backend`. The frontend uses
  **yarn**, never npm.
- The live-API suites under `app/backend/tests/` report as *skipped* without a
  running server — expected, not a failure, not something to "fix".
- Never weaken an assertion to make a suite green. If a kernel anti-cheat test
  starts failing, your change is wrong, not the test.

# COMMIT

Small honest commits as you go, not one at the end. Each message:

1. The repo's `scope: subject` form in the imperative — e.g.
   `outbound: add in-transit stock bucket`. Scopes in use: `core`, `masters`,
   `inbound`, `outbound`, `sell`, `storefront`, `offers`, `pos`, `ptmapper`,
   `stockledger`, `finledger`, `frontend`, `agents`, `docs`, `ci`.
2. Reference the issue and its parent PRD.
3. State the key decisions made, and any rule or ADR they lean on (the plan's
   Binding rules section has the quotes).

Keep it concise. Skip the file list — git already has it.

# WHEN DONE OR STUCK

If the task cannot be completed, comment on the issue with what was done, what
is left, and anything a human needs to rule on:
`gh issue comment {{TASK_ID}} -R bruhanand/KDPS --body "..."`.
Do not close the issue.

Once complete, output <promise>COMPLETE</promise>.

# FINAL RULES

ONLY WORK ON A SINGLE TASK.
