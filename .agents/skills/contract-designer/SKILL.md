---
name: contract-designer
description: "Phase 2 - contract. Invoke after requirements are approved to design the API surface, DB schema deltas, and posting entries for a feature."
disable-model-invocation: true
---

# Contract Designer - Phase 2: API, DB & Postings

Input: approved `docs/features/<slug>/feature-analysis.md` and `requirements.md`.

## 1. Explore what exists

Before designing, read the touched apps' current models, serializers, views, and urls so the new contract matches existing patterns.
For anything that posts, read the posting catalog (`docs/my-understanding/system-design/consolidation/posting-catalog.html`).

## 2. `api-contract.md`

For each new or changed endpoint:

- Method, path, auth and role scope.
- Path/query params and request body, with types and required/optional.
- Success response shape and status code.
- **Error table** - every error the endpoint can return: `errorCode` / HTTP status / trigger condition.
- **Business logic** - a numbered step flow of exactly what the endpoint does, with inline error branches under the step that produces them:

  ```
  1. <step>
  2. <step>
     -> <failure condition> -> <errorCode>
  3. <step>
  ```

  Every validation, lookup, state mutation, and posting is its own step.
  Every `-> errorCode` in the flow has a row in the error table, and vice versa.

An endpoint that already exists is updated in place, never duplicated.

## 3. `db-design.md`

For each new or changed table: columns, types, constraints (PK, FK, unique, not null, default), and indexes with reasons.
Mark clearly what is new versus existing.
Note any backfill or data migration.

## 4. Postings

A section in `api-contract.md` when the feature writes any ledger.
For each document the feature writes: which entries fire, on which docstatus transition, both legs, balanced, through `post_entries` - branching per commercial model where ownership changes the posting.
**Mandatory when phase 0 flagged money**; it extends the posting catalog, it never invents a parallel path.

## 5. Approve

Show both files, wait for explicit approval, revise until approved.
Then stop; phase 3 is `/system-designer`.
