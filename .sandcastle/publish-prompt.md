# TASK

Open a pull request for each of these branches. **Do not merge anything.**

{{BRANCHES}}

A human reviews and merges. That is the whole point of this phase: the work
arrives as a proposal, not as a fait accompli.

# FOR EACH BRANCH

1. **Check whether the reviewer handed it back.** If its issue carries the
   `ready-for-human` label, the reviewer found something it would not fix on its
   own — money, a broken rule, or a question the design does not answer.

   Open the PR as a **draft**, title it `WIP: <what was attempted> (#<id>)`, and
   say in the body which finding stopped it and where the reviewer's comment is.
   Then move to the next branch. Do not try to fix it yourself.

2. **Otherwise, verify the gate.** Check out the branch and run `npm run ci` —
   the repo's full acceptance gate (backend: ruff, mypy strict,
   `makemigrations --check`, import-linter, pytest; frontend: tsc, vitest).

   PostgreSQL is already running in this sandbox and `DATABASE_URL` is set.
   Backend commands go through `uv` from `app/backend`. The frontend uses
   **yarn**, never npm. The nine live-API suites under `app/backend/tests/`
   report as *skipped* without a running server — expected, not a failure.

   Two things you must never do to get a green gate: weaken or skip an existing
   assertion, and drop one side's behaviour. If the gate is red and the fix is
   not obvious, open the PR as a draft saying so.

3. **Push and open the PR** against `main`:

   ```bash
   git push -u origin <branch>
   gh pr create -R bruhanand/KDPS --base main --title "<type>: <what changed> (#<id>)" --body-file <file>
   ```

   Body:

   ```markdown
   Closes #<id>

   ## What changed
   <plain language, two or three sentences>

   ## Gates
   - `npm run ci`: green
   - Review: <what the reviewer changed, or "no findings">

   ## Not covered
   <anything a human must check by hand, especially anything on a screen —
   nothing in this sandbox opens a browser. Delete if none.>
   ```

# DO NOT

- Do not merge any branch.
- Do not close any issue. The PR's `Closes #<id>` does that when a human merges.
- Do not resolve conflicts with `main` by dropping either side. If a branch
  cannot rebase cleanly, open the PR anyway and say what conflicts.

# ISSUES

{{ISSUES}}

Once every branch has a PR, output <promise>COMPLETE</promise>.
