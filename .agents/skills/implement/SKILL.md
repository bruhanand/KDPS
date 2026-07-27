---
name: implement
description: "Phase 5 - take one ready-for-agent issue to an open PR: implement, review and fix, CI gate, live browser QA. Never merges."
disable-model-invocation: true
---

# Implement

`/implement <issue#>`, or `/implement next` for the oldest unassigned `ready-for-agent` issue.
One issue to an open PR with evidence.
A human merges.
Scratch files (CI logs, screenshots, QA notes) go in the session scratchpad, never the repo.

## Spec and currency

The spec is `docs/features/<slug>/` (requirements, api-contract, db-design, design) when the issue belongs to a feature; otherwise the issue body.
Read the issue with its comments and check three things before starting; if any fails, comment on the issue and stop:

1. The body matches the comments - a ruling left in a comment while the body holds the old spec is two specs, and the wrong one gets built. Ask for the body to be rewritten.
2. Declared blockers are closed.
3. No open PR already touches the same files for the same reason.

## Implement

Work on a branch off fresh `main`, commit in small honest steps, and never `git stash` - the working tree may be shared with other sessions.
Use /tdd at the seams the spec names; prefer an existing seam, fewest seams wins.
Money paths: the contract's postings section is the design - every posting goes through `post_entries`; if the design is not locked, stop and say so.
While working, check only what you touched (the one test file, mypy, tsc) - that is the only local check; the full `npm run ci` suite does not run as part of this flow.

## Review and fix

Run /code-review against `main`.
Fix every Spec finding, or record a deliberate deviation and its reason in the PR body.
Fix every critical Correctness & Safety finding and every hard Standards violation; name the judgement-call smells you consciously leave.
Two rounds, then [ESCALATION.md](ESCALATION.md) - a finding that survives two honest fix attempts is telling you something about the design, and money always goes back to the human.

## Live QA

Send a **Sonnet** subagent, synchronous, to QA what you actually built in a real browser, following [LIVE-QA.md](LIVE-QA.md). Give it the issue's acceptance criteria, the branch name, and the path to LIVE-QA.md.
Ask it to return in under 300 words: pass or fail per flow, and for each fail what it clicked, what it expected, what happened, and the network or console line that proves it - screenshots referenced by path, never pasted.
The dev stack is single-tenant (one Postgres, `:8001`, `:3000`); if another session holds it, say so and wait.
A failed flow: fix it yourself, then send a **fresh** Sonnet subagent to re-drive only the failed flows. Two re-drives at most, then [ESCALATION.md](ESCALATION.md).

## Pull request

Push the branch and open a PR against `main`. The push alone triggers cloud CI (`.github/workflows/ci.yml`) - it runs on GitHub, not locally; do not wait for it before opening the PR.
PR body: what changed in plain language, review findings and what was fixed, QA flows driven with screenshot paths, deliberate deviations, anything a human must check by hand.
Comment the same summary on the issue and stop - the PR stays open, the issue stays open, nothing merges, nothing deploys.

Cloud CI is lighter than the full local `npm run ci` (it skips ruff, mypy strict, import-linter, and the migration check) - that trade is deliberate, for speed. Run `npm run ci` yourself only if you want the stricter local gate; it is not part of this flow.
