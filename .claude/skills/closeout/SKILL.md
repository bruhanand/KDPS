---
name: closeout
description: "Phase 6 - after every ticket of a feature is merged, verify the built feature against its phase 0-3 docs and run whole-feature QA. Produces the conformance report the human signs off on."
disable-model-invocation: true
---

# Closeout - Phase 6: Feature Verification

Run when every ticket of a feature is done and merged.
Input: the full `docs/features/<slug>/` set and the list of the feature's issues and merged PRs (`gh issue list`, `gh pr list`).

Per-PR review already happened; this phase checks the **feature as a whole** - the thing no single PR review could see.

## 1. Requirements coverage

For every functional requirement and every quantitative value in `requirements.md`: where it is met (screen, endpoint, or test), or **gap**.
A requirement met by no ticket is the classic hole here - tickets each passed, the union did not.

## 2. Contract conformance

- Every endpoint in `api-contract.md`: exists, matches the business-logic flow, returns every error in the error table.
- Every table and column in `db-design.md`: present in the migrations as designed.
- Every posting in the contract: fires on the designed transition, both legs, through `post_entries` - reconcile against the posting catalog.

List every deviation; a deviation someone chose deliberately gets its reason quoted from the PR, everything else is a finding.

## 3. Whole-feature QA

Drive the feature end to end in the browser with the discipline of `.claude/skills/implement/LIVE-QA.md`: preconditions first, then **cross-ticket flows** - the journeys that span several tickets, which per-issue QA never exercised.
Include the owning role, one scope-negative flow, and money rendering wherever money shows.

## 4. Report and sign-off

Write `docs/features/<slug>/closeout.md`:

- **Coverage table** - requirement, where met, verdict.
- **Contract deviations** - each with severity `[critical | warning | suggestion]` and whether it was deliberate.
- **QA verdicts** - per flow, pass or fail with evidence.
- **Gaps** - anything unmet; file each as a new issue.

Show the report and stop.
The human signs off; critical findings and gaps go back through `/implement` as new issues, and closeout runs again after they merge.
