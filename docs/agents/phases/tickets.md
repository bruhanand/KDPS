# Phase 3 - Tickets

Input: the approved `docs/features/<slug>/` documents.
Output: one GitHub issue per ticket, labelled `ready`, in dependency order.

Tracker commands: [../issue-tracker.md](../issue-tracker.md). Labels: [../labels.md](../labels.md).

## 1. Draft vertical slices

Each ticket is a **tracer bullet**: a narrow but complete path through every layer - schema, API, UI,
tests. Not a horizontal slice of one layer.

- A completed slice is demoable or verifiable on its own.
- Each slice fits in a single fresh context window.
- Any prefactoring goes first. Make the change easy, then make the easy change.

Give each ticket its **blocking edges** - the tickets that must complete before it can start. A ticket
with no blockers can start immediately.

Use the vocabulary of `CONTEXT.md` and the design glossary in every title and body, and respect the
ADRs for the area.

**Wide refactors are the exception.** A wide refactor is one mechanical change - rename a column,
retype a shared symbol - whose blast radius fans across the codebase, so a single edit breaks thousands
of call sites and no vertical slice can land green. Sequence it expand-migrate-contract instead: add
the new form beside the old so nothing breaks; migrate the call sites in batches sized by blast radius,
each batch its own ticket blocked by the expand, staying green because the old form still exists; then
delete the old form in a final ticket blocked by every batch.

## 2. Quiz Anand

Present the breakdown as a numbered list. Per ticket: title, blocked by, and what end-to-end behaviour
it delivers. Then ask:

- Is the granularity right - too coarse, too fine?
- Are the blocking edges correct, or does a ticket depend on something that does not actually gate it?
- Should any tickets be merged or split?

Iterate until approved.

## 3. Publish

One issue per ticket, in dependency order so each ticket's blockers already have real numbers.
Use GitHub's native blocking relationship where available, otherwise a `Blocked by: #n` line at the top
of the body.

Label each `ready`. Add `money` to every ticket whose slice touches ledgers, postings, GST, valuation
or the document FSM - the flag comes from the spec and must ride the ticket, because `implement` reads
it before it opens any document.

Do not close or modify the parent issue.

```markdown
## Spec source
docs/features/<slug>/

## What to build
The end-to-end behaviour this ticket makes work, from the user's point of view.
Not a layer-by-layer implementation list.

## Acceptance criteria
- [ ] ...
- [ ] ...

## Blocked by
- #n, or "None - can start immediately".
```

Avoid file paths and code snippets; they go stale while the ticket waits. The one exception is a
snippet that encodes a decision more precisely than prose can - a state machine, a schema, a type shape
- trimmed to the decision-rich part.
