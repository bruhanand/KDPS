# TASK

Open one pull request per branch below. **Do not merge anything. Do not close
any issue.** A human reviews and merges — the work arrives as a proposal, not
as a fait accompli.

{{BRANCHES}}

Each line carries the branch, its issue, its state (`ready` or `handed-back`),
and its artifacts directory — the pipeline's slice plan, review findings,
deviations, QA report and screenshots live there. Read them; the PR body is
written **from** them, never invented.

# FOR EACH BRANCH

1. **Push it**: `git push -u origin <branch>`.
   **The push is the CI.** Cloud CI (`.github/workflows/ci.yml`) runs the full
   gate on GitHub for every push — nothing is gated locally in this pipeline,
   and you never run `npm run ci` here. That is deliberate: the gate takes ~16
   minutes and GitHub runs it for free while the human reads the PR.

2. **State `handed-back`** → open the PR as a **draft**, titled
   `WIP: <what was attempted> (#<id>)`. Say in the body which finding stopped
   it and where the question for the human is (the issue comment). Confirm the
   issue carries the `ready-for-human` label; add it if missing
   (`gh issue edit <id> -R bruhanand/KDPS --add-label ready-for-human
   --remove-label ready-for-agent`). Do not try to fix anything yourself.

3. **State `ready`** → open a real PR:

   ```bash
   gh pr create -R bruhanand/KDPS --base main --title "<type>: <what changed> (#<id>)" --body-file <file>
   ```

   Body, drawn from the artifacts:

   ```markdown
   Closes #<id>

   ## What changed
   <plain language, two or three sentences>

   ## Review
   <findings per axis and what was fixed; deliberate deviations from
   deviations.md, with their reasons. "No findings" if the files say so.>

   ## QA
   <the flows driven and their verdicts, from qa-report.md; screenshots live
   on the run host under ~/.cache/sandcastle-kdps/artifacts/issue-<id>/>

   ## CI
   Cloud CI runs on this push — check the Checks tab before merging. Nothing
   was gated locally.

   ## Not covered
   <anything a human must check by hand. Delete if none.>
   ```

# DO NOT

- Do not merge any branch.
- Do not close any issue. The PR's `Closes #<id>` does that when a human
  merges.
- Do not resolve conflicts with `main` by dropping either side. If a branch
  cannot rebase cleanly, open the PR anyway and say what conflicts.

# ISSUES

{{ISSUES}}

Once every branch has a PR, output <promise>COMPLETE</promise>.
