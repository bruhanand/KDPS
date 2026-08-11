# The dev process

Feature work moves through a phase chain.
Each phase is a skill invoked by hand, writes one artifact, shows it, and stops for approval.
Nothing auto-advances: the developer drives every transition, and feedback on a phase stays in that phase until it is approved.

Phase artifacts live in one folder per feature: `docs/features/<slug>/` (kebab-case slug, e.g. `docs/features/pos/`).

## The chain

| Phase | Skill | Artifact |
|---|---|---|
| 0 - Impact analysis | `/feature-analyst` | `feature-analysis.md` |
| 1 - Requirements | `/grilling` (money slice: `/grill-with-docs`) | `requirements.md` |
| 2 - Contract | `/contract-designer` | `api-contract.md` + `db-design.md` |
| 3 - Technical design | `/system-designer` | `design.md` |
| 4 - Tickets | `/to-tickets` | GitHub issues, `ready-for-agent` |
| 5 - Per issue | `/implement` | one PR per issue; a human merges |
| 6 - Closeout | `/closeout` | `closeout.md` |

`/code-review` runs inside phase 5 before every PR, and stays available standalone.

## Phase 1 in this repo

We grill instead of interviewing by template.
Grill over `feature-analysis.md` plus everything the user provided, then write the outcome to `docs/features/<slug>/requirements.md`: functional requirements, non-functional requirements, edge cases, out of scope.
Force a concrete number for every quantitative value (expiry, retries, limits, thresholds, lengths, timeouts, retention); "reasonable" and "fast" are not values.

## Phase 4 in this repo

Run `/to-tickets` over the approved phase 0-3 docs.
Tickets are vertical tracer-bullet slices with blocking edges, published as GitHub issues.
Each issue names `docs/features/<slug>/` as its spec source.

## Weight scales with the work

The chain is for features.
A bug fix or a small tweak gets an issue with a clear body, then `/implement` and `/code-review` directly - no phase docs, no closeout.

Existing issues that predate this process work the same way: the issue body is the spec.
If the comments disagree with the body, the body gets rewritten first; two specs on one issue is how work gets built wrong.

## Money slices

Phase 0 flags a feature as a money slice when it touches ledgers, postings, GST, valuation, or the document FSM.
A money flag means, on top of the chain:

- Phase 1 uses `/grill-with-docs` so the design is locked against the corpus before code.
- The postings section of the contract is mandatory: every ledger entry the feature writes, both legs, through `post_entries`.
- Review follows the cross-model review policy (Opus/Sonnet reviewers).
- Findings about money always go back to the human - see `.agents/skills/implement/ESCALATION.md`.
- The five CA-gated items stay gated until ruled.
