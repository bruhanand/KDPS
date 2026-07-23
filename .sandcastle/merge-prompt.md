# TASK

Merge the following branches into the current branch:

{{BRANCHES}}

For each branch:

1. Run `git merge <branch> --no-edit`
2. If there are merge conflicts, resolve them intelligently by reading both sides and choosing the correct resolution
3. After resolving conflicts, run `npm run ci` to verify everything works —
   that is the repo's full acceptance gate (backend: ruff, mypy strict,
   `makemigrations --check`, import-linter, pytest; frontend: tsc, vitest)
4. If it fails, fix the issues before proceeding to the next branch

Notes on this sandbox: PostgreSQL is already running and `DATABASE_URL` is set.
Backend commands go through `uv` from `app/backend`. The frontend uses **yarn**,
never npm. The nine live-API suites under `app/backend/tests/` report as
*skipped* without a running server — that is expected and is not a failure.

Two things you must not do to get a green gate: weaken or skip an existing
assertion, and resolve a conflict by dropping one side's behaviour. If a merge
genuinely cannot be reconciled without a design decision, stop merging that
branch, leave it unmerged, and say so in your final output.

After all branches are merged, make a single commit summarizing the merge, using
the repo's `scope: subject` form.

# CLOSE ISSUES

For each branch that was **successfully merged with a green `npm run ci`**, close
its issue:

`gh issue close <ID> -R bruhanand/KDPS --comment "Completed by Sandcastle"`

Do not close the issue for a branch you left unmerged or could not get green.
Comment on it instead, explaining what blocked it:

`gh issue comment <ID> -R bruhanand/KDPS --body "..."`

Here are all the issues:

{{ISSUES}}

Once you've merged everything you can, output <promise>COMPLETE</promise>.
