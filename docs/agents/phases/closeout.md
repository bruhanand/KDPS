# Phase 5 - Closeout

Run when every ticket of a feature is merged. Input: the full `docs/features/<slug>/` set and the
feature's issues and merged PRs (`gh issue list`, `gh pr list`).

**Only for features with three or more tickets, or that touched money.** A two-ticket feature does not
need a conformance report; per-PR review already covered it.

This phase checks the **feature as a whole** - the thing no single PR review could see. Tickets each
passed; the question is whether their union did.

## 1. Requirement coverage

For every functional requirement and every quantitative value in `spec.md`: where it is met - screen,
endpoint, or test - or **gap**. A requirement met by no ticket is the classic hole here.

## 2. Design conformance

- Every endpoint in `design.md`: exists, matches its step flow, returns every error in its error table.
- Every table and column: present in the migrations as designed.
- Every posting: fires on the designed transition, both legs, through `post_entries`, as the
  feature's `design.md` specifies.

List every deviation. A deviation someone chose deliberately gets its reason quoted from the PR;
everything else is a finding.

## 3. Whole-feature QA

Run every spec the feature's tickets left behind (`npm run e2e`), then write one more:
`app/frontend/e2e/<slug>-journey.spec.ts`, covering the **cross-ticket journeys** - the flows that span
several tickets, which per-issue QA never exercised. Method and toolkit in [live-qa.md](live-qa.md).
Include the owning role, one scope-negative flow, and money rendering wherever money shows.

## 4. Report

Write `docs/features/<slug>/closeout.md`:

- **Coverage table** - requirement, where met, verdict.
- **Deviations** - each with severity `[critical | warning | suggestion]`, and whether it was deliberate.
- **QA verdicts** - per flow, pass or fail with evidence.
- **Gaps** - anything unmet. File each as a new issue.

Show the report and stop. Anand signs off. Critical findings and gaps go back through `implement` as
new issues, and closeout runs again after they merge.
