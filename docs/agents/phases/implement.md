# Phase 4 - Implement

One `ready` issue to an open PR, with evidence. A human merges.
Run one issue per session. Scratch files - CI logs, screenshots, QA notes - go in the session
scratchpad, never in the repo.

Cost discipline is part of this phase, not a nice-to-have. The whole pipeline is **two subagents**
normally, three on a money slice, four at worst with a QA retry. If you find yourself spawning a fifth,
something upstream was wrong and you should stop rather than spend your way past it.

## 1. Check the spec before you touch anything

The spec is `docs/features/<slug>/` when the issue names a feature folder, otherwise the issue body.
Read the issue with its comments and check four things. If any fails, comment on the issue and stop.

1. **The body matches the comments.** A ruling in a comment while the body holds the old spec is two
   specs, and the wrong one gets built. Ask for the body to be rewritten.
2. **Declared blockers are closed.**
3. **No open PR already touches the same files for the same reason.**
4. **The design document passes its completeness gate** - the checklist at the bottom of
   [design.md](design.md). A thin design is a design-phase failure. Send it back to `design`; do not
   compensate by thinking harder here, and do not reach for a stronger model to paper over it.

Check 4 does not apply to a self-contained issue with no feature folder. There the issue body is the
spec, and it either specifies the work or it does not - if it does not, the issue belongs in `blocked`.

## 2. Implement

Branch off fresh `main`. Commit in small honest steps. **Never `git stash`** - the working tree may be
shared with another session, and a stash has swapped a whole diff before.

Use `tdd` at the seams the spec names. Prefer an existing seam; fewest seams wins.

On money paths the design's postings section **is** the design: every posting goes through
`post_entries`. If the design is not locked, stop and say so.

While working, check only what you touched - the one test file, mypy, tsc. That is the only local
check. The full `npm run ci` suite does not run in this flow; cloud CI covers the same ground at push
time, in parallel shards, without making you wait.

**Model:** a mid-tier model writes all the code, money slices included. That is what the completeness
gate in step 1 buys.

## 3. Review, once

Run the review in [review.md](review.md): **one subagent** on the strongest model available, plus a
**second** on the ledger axis if the issue carries `money`.

Then fix, **once**:

- Fix every Spec finding, or record a deliberate deviation and its reason in the PR body.
- Fix every critical Correctness and Safety finding.
- Name the judgement calls you consciously leave.

A finding that survives one honest attempt is telling you something about the design, not asking for a
second attempt. It goes in the PR body under "needs a human", or through
[escalation.md](escalation.md). Money always goes back to Anand.

## 4. Live QA, once

Send **one subagent** on a mid-tier model, synchronous, to write and run a Playwright spec against
what you actually built, following [live-qa.md](live-qa.md). Give it the issue's acceptance criteria,
the branch name, and the path to that document.

The spec goes in `app/frontend/e2e/<issue-slug>.spec.ts` and is **committed with the change**. That is
what makes this the cheapest step in the phase rather than the most expensive one: the QA that passed
for this issue reruns for free on the next one, and the guards in the toolkit fail the run on a console
error or an undeclared 4xx, so a pass cannot be a pass by inattention.

Ask it to return in under 300 words: pass or fail per test, and for each fail what it clicked, what it
expected, what happened, and the console or network line that proves it. Trace and screenshot paths
from the HTML report, never pasted - a screenshot in the transcript is the single most expensive thing
this phase can do to your context.

Then do the visual pass yourself: **two or three screenshots** from the report, read and judged. That is
the one thing a spec cannot do, and the tenth screenshot tells you nothing the third did not.

A failed test: fix it yourself, then re-run that spec. **One re-run**, then
[escalation.md](escalation.md).

## 5. Pull request

Push the branch and open a PR against `main`. Rebase onto `origin/main` first and re-run the tests
after the rebase, even if nothing conflicted - two individually green PRs have broken `main` at the
RBAC and nav contract tests before.

The push alone triggers cloud CI ([../ci.md](../ci.md)). It runs on GitHub, not locally; do not wait
for it before opening the PR. It runs the same gate as local `npm run ci`, so a green run there means
what a green run here means.

PR body: what changed in plain language; review findings and what was fixed; QA flows driven with
screenshot paths; deliberate deviations; anything a human must check by hand.

Comment the same summary on the issue and stop. The PR stays open, the issue stays open, nothing
merges, nothing deploys.
