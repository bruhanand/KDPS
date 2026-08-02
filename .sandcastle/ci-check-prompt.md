# TASK

Issue {{TASK_ID}} ({{ISSUE_TITLE}}) has been built, reviewed and QA'd on
branch {{BRANCH}}, which is checked out in this sandbox. This check is the
branch's pre-merge filter: nothing is pushed to GitHub and no PR is opened
in this pipeline. The same command runs again on the host after the merge —
a wrong PASS here does not land broken code, it just wastes a wave.

# RUN THE FAST CI GATE

**Never run `npm run ci:fast` as a single command.** Your Bash tool has a
hard 10-minute cap per command; the whole suite takes longer, gets
backgrounded, and you never see a verdict — issue #241's gate "failed"
twice this way with a green suite. Ending your turn to "wait for a
notification" ends the agent: there is no later. Every command you run must
finish inside the cap, in the foreground.

Instead, mirror the gate's stages as separate commands (read the `ci:fast`,
`ci:backend:fast` and `ci:frontend` scripts in the root and
`app/frontend/package.json` to confirm), roughly:

1. `cd app/backend && uv run mypy core config`
2. `cd app/backend && uv run python manage.py makemigrations --check --dry-run && uv run python manage.py check_db_drift && uv run lint-imports`
3. Backend `uv run pytest`, split by top-level app directory into chunks so
   no single call risks the cap (e.g. 3-4 chunks; `ls app/backend` for the
   app list). Every test directory must run exactly once across the chunks —
   a skipped directory makes a PASS a lie.
4. The frontend gate, stage by stage the same way (typecheck, then tests).

PASS only if every stage ran and passed.

This runs `mypy core config`, the migration/DB-drift checks
(`makemigrations --check --dry-run`, `check_db_drift`), `lint-imports`, and
both test suites (backend `pytest`, frontend `tsc --noEmit` + `vitest`). It
deliberately skips `ruff` — formatting is the review agents' Standards axis,
and this check exists to catch actual breakage fast, not style.

PostgreSQL is already running in this sandbox (same setup QA uses).

# DO NOT

- Do not fix failures. If `npm run ci:fast` fails, report exactly what failed
  (the command, the failing test names or migration diff) and stop — a human
  reviews a failed gate, this pipeline does not retry it.
- Do not modify test files to make them pass.
- Do not run the full `npm run ci` (ruff/mypy/import-linter) — it is not part
  of this gate and only costs time.

# OUTPUT

**The harness stops your run at the first occurrence of the verdict tag
anywhere in your output — including in a sentence describing what you are
about to do.** Never write the tag, in any form, before `npm run ci:fast`
has actually finished. Announce your plan without it ("running the gate
now"), then end with the verdict as your very last line.

Exactly one of:

```
<ci>PASS</ci>
```

```
<ci>FAIL: <one line — command and what failed></ci>
```
