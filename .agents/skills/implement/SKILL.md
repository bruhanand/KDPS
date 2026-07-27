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
While working, check only what you touched (the one test file, mypy, tsc); the full gate runs once, at the end.

## Review and fix

Run /code-review against `main`.
Fix every Spec finding, or record a deliberate deviation and its reason in the PR body.
Fix every critical Correctness & Safety finding and every hard Standards violation; name the judgement-call smells you consciously leave.
Two rounds, then [ESCALATION.md](ESCALATION.md) - a finding that survives two honest fix attempts is telling you something about the design, and money always goes back to the human.

## Gate and live QA

`npm run ci` is the acceptance gate and runs once, at the end.
Green means green - cloud CI runs a subset and does not substitute.
Then QA what you actually built in a real browser, following [LIVE-QA.md](LIVE-QA.md).
The dev stack is single-tenant (one Postgres, `:8001`, `:3000`); if another session holds it, say so and wait.
A failed flow: fix, re-run the gate, re-drive only the failed flows; two re-drives at most, then [ESCALATION.md](ESCALATION.md).

## Pull request

Open a PR against `main`: what changed in plain language, gate results, review findings and what was fixed, QA flows driven with screenshot paths, deliberate deviations, anything a human must check by hand.
Comment the same summary on the issue and stop - the PR stays open, the issue stays open, nothing merges, nothing deploys.
