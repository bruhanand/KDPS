# Phase 2 - Design

Input: an approved `docs/features/<slug>/spec.md`.
Output: `docs/features/<slug>/design.md` - one document covering the API contract, the schema delta,
the postings, and the component breakdown.

**Skippable** when the feature is not a money slice and fits in one or two tickets. Say so and let
Anand decide. **Never skippable on a money slice.**

This document is what the implementer builds from. It is written on the assumption that a mid-tier
model will implement it with no further design thinking, so anything left implicit here gets guessed
there. The completeness gate at the bottom is not a formality: `implement` checks it and refuses.

## 1. Explore what exists first

Read the current models, serializers, views and urls of the touched apps, and the touched screens, so
the design extends the established patterns instead of inventing new ones. Trace one existing similar
flow end to end. For anything that posts, read the posting catalog
(`docs/my-understanding/system-design/consolidation/posting-catalog.html`) as background, then read
what the code actually posts - where they disagree, the code is the reference and the design extends
the code's real behaviour.

## 2. Ask only what the spec does not settle

How the views, services and screens should be structured, and what is shared versus new; interactions
with existing documents, ledgers and the review-queue or maker-checker patterns; error handling or
logging beyond repo convention; performance or security considerations.

Wait for answers, follow up until nothing is ambiguous, then write.

## 3. Write `design.md`

### Summary
The design in a paragraph.

### Endpoints
One block per new or changed endpoint. An endpoint that already exists is updated in place, never
duplicated.

- Method, path, auth and role scope.
- Path and query params, and the request body, with types and required or optional.
- Success response shape and status code.
- **Error table** - every error the endpoint can return: `errorCode`, HTTP status, trigger condition.
- **Business logic** - a numbered step flow of exactly what the endpoint does, with the error branches
  inline under the step that produces them:

  ```
  1. <step>
  2. <step>
     -> <failure condition> -> <errorCode>
  3. <step>
  ```

  Every validation, lookup, state mutation and posting is its own step. Every `-> errorCode` in the
  flow has a row in the error table, and every row appears in a flow.

### Schema
Per new or changed table: columns, types, constraints (PK, FK, unique, not null, default), and indexes
with the reason for each. Mark clearly what is new versus existing. Note any backfill or data migration.

### Postings
**Mandatory when the spec flagged money.** Per document the feature writes: which entries fire, on
which docstatus transition, both legs, balanced, through `post_entries` - branching per commercial
model wherever ownership changes the posting. This extends the posting catalog; it never invents a
parallel path.

### Components
Models, serializers, views, urls, services, screens and components - new versus changed. The request
flow from click to response to posting, for each main flow. The error-handling approach. Assumptions
made.

## 4. The completeness gate

Before showing the document, check it yourself and state the result. `implement` runs the same check
and stops if it fails.

- [ ] Every endpoint has a role scope, an error table, and a numbered step flow.
- [ ] Every `-> errorCode` in a flow has a row in its error table, and the reverse.
- [ ] Every new column has a type and its constraints.
- [ ] Every screen names what it renders and which endpoint it calls.
- [ ] **Money only:** every ledger entry is listed with both legs and the transition that fires it.
- [ ] No requirement in `spec.md` is unaccounted for.
- [ ] Nothing here needs a CA ruling that has not been given.

A gap here is a design failure, not a reason to implement more carefully. Fill it now.

## 5. Approve

Show the file, wait for explicit approval, revise until approved.
Then stop; phase 3 is `to-tickets`.
