---
name: system-designer
description: "Phase 3 - technical design. Invoke after the contract is approved to produce the component-level design for a feature."
disable-model-invocation: true
---

# System Designer - Phase 3: Technical Design

Input: approved `docs/features/<slug>/requirements.md`, `api-contract.md`, and `db-design.md`.

Optional for small features - say so and let the developer skip it.
Never skipped on a money slice.

## 1. Explore what exists

Read the current structure of the touched Django apps and PWA screens, and trace one existing similar flow end to end, so the design extends established patterns instead of inventing new ones.

## 2. Ask targeted questions

Only what the contract does not settle:

- How the new views/services/screens should be structured, and what is shared versus new.
- Interactions with existing documents, ledgers, and the review-queue/maker-checker patterns.
- Error handling or logging beyond repo conventions.
- Performance or security considerations.

Wait for answers; follow up until nothing is ambiguous.

## 3. Write `design.md`

- **Summary** - the design in a paragraph.
- **Component breakdown** - models, serializers, views, urls, services, frontend screens and components; new versus changed.
- **Request flow** - from click to response to posting, for the main flows.
- **Error handling approach.**
- **Assumptions made.**

## 4. Approve

Show the file, wait for explicit approval, revise until approved.
Then stop; phase 4 is `/to-tickets` over the approved docs.
