# The dev process

Every agent working in this repo follows this. It is tool-neutral: each phase's method is a plain
document under `docs/agents/phases/`, and each tool's skill file is a pointer at one of them.

Each phase is invoked by hand, writes one artifact, shows it, and stops for approval.
Nothing auto-advances: the developer drives every transition, and feedback on a phase stays in that
phase until it is approved.

Phase artifacts live in one folder per feature: `docs/features/<slug>/` (kebab-case slug).

## The code is the truth

The design corpus (`docs/my-understanding/system-design/`) is input, not the spec of record: much of
it predates the build, and requirements changed without every change being written back. What exists
and how it behaves is answered by reading the code and git history. Where a document and the code
disagree, the code wins - note the drift rather than building from the doc.

The exceptions, which bind regardless of the code, live in `CONTEXT.md`: the 12 rules, the kernel
contracts, the locked money decisions and the CA-gated list.

Every feature builds from its own fresh `docs/features/<slug>/` spec and design, written by the
phases below against the current code - never from an old corpus document.

## The chain

| Phase | Skill | Artifact | Method |
|---|---|---|---|
| Triage | `triage` | the issue body becomes the spec | [phases/triage.md](phases/triage.md) |
| 1 - Spec | `spec` | `docs/features/<slug>/spec.md` | [phases/spec.md](phases/spec.md) |
| 2 - Design | `design` | `docs/features/<slug>/design.md` | [phases/design.md](phases/design.md) |
| 3 - Tickets | `to-tickets` | GitHub issues labelled `ready` | [phases/tickets.md](phases/tickets.md) |
| 4 - Implement | `implement` | one PR per issue; a human merges | [phases/implement.md](phases/implement.md) |
| 5 - Closeout | `closeout` | `docs/features/<slug>/closeout.md` | [phases/closeout.md](phases/closeout.md) |

Those are skill names; invoke them however your tool does (Claude Code: `/spec`).

Three supporting documents are read from inside a phase, never invoked directly:
[phases/review.md](phases/review.md), [phases/live-qa.md](phases/live-qa.md),
[phases/escalation.md](phases/escalation.md). `code-review` also stays available standalone.

## Which phase for which issue

The label says whether an agent may start. **Size** says which phase it starts at.

```
issue has no label
   → triage. Read it, then either rewrite the body into a real spec and label it
     `ready`, or label it `blocked` and ask Anand one plain question.

issue is `ready`
   → does it fit one session?
        yes → implement            one PR, stops, never merges
        no  → it is a feature, not an issue.
              spec → design → to-tickets, which emits `ready` issues that do fit.

issue is `blocked`
   → nothing runs. Anand answers, the body is REWRITTEN to carry the ruling,
     then it is labelled `ready`.
```

A ruling left in a comment while the body still holds the old spec is two specs on one issue, and an
agent will faithfully build the wrong one. That is how #96 got built wrong. The body is the spec, and
this holds for issues that predate this process too.

Labels: [labels.md](labels.md). Tracker commands: [issue-tracker.md](issue-tracker.md).

## Weight scales with the work

The full chain is for features. A bug fix or a small tweak gets a `ready` issue with a clear body,
then `implement` directly - no phase documents, no closeout.

`design` is skippable when the work is not a money slice and fits in one or two tickets.
It is never skippable on a money slice.

`closeout` runs only when the feature had three or more tickets, or touched money.

## Money slices

A feature is a money slice when it touches ledgers, postings, GST, valuation, or the document FSM.
Phase 1 flags it; the `money` label carries the flag onto every ticket it produces.

On a money slice:

- Phase 1 grills with the design corpus as input (`grill-with-docs`) so the design is locked before
  code - but a corpus claim enters the spec only after the code confirms it still holds.
- `design` is mandatory, and its postings section is mandatory within it: every ledger entry the
  feature writes, both legs, on which docstatus transition, through `post_entries`.
- `implement` runs a second reviewer on the ledger axis.
- Findings about money always go back to Anand, even when the corpus answers the question.
  See [phases/escalation.md](phases/escalation.md).
- The five CA-gated items stay gated until ruled.

## Which model does what

The principle, which every agent follows with whatever models it has:

- **Implement with a mid-tier model.** Writing code against a complete design is typing, not thinking.
- **Review with the strongest model available.** A review reads a small diff and makes judgement calls.
  It is where the better model earns its price, and it is cheap in absolute terms.
- **Never let the model that wrote the code be the only one grading it.**

A thin design document is not a reason to reach for a stronger model. It is a design-phase failure:
`implement` sends it back to `design` rather than papering over it. The completeness gate is defined in
[phases/design.md](phases/design.md) and checked at the top of [phases/implement.md](phases/implement.md).

In Claude Code specifically: Sonnet implements, Opus reviews, Sonnet drives the browser.

## Parallelism

Run one issue per session. Sessions do not queue behind each other: every Conductor workspace has its
own Postgres, its own ports and its own database (`npm run dev:where`).

Because issues run in parallel, `main` moves while you work. Before pushing, rebase onto `origin/main`
and re-run the test suite after the rebase - especially the RBAC and nav contract tests - even if none
of your own files conflicted. Two individually green PRs have broken `main` at those tests before
(the #146 hotfix).
