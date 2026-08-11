---
name: feature-analyst
description: "Phase 0 - impact analysis. Invoke with everything known about a new feature to map its blast radius across the KDPS system and flag whether it is a money slice, before any requirements or design work."
disable-model-invocation: true
---

# Feature Analyst - Phase 0: Impact Analysis

Input: everything the user has on the feature - notes, meeting minutes, client asks, issue references.
Ask for a kebab-case feature slug; artifacts for this feature live in `docs/features/<slug>/`.

## 1. Read the context

Read `CONTEXT.md`.
If the design corpus has a module folder for this area (`docs/my-understanding/system-design/`), read its design too.

## 2. Determine the blast radius, KDPS-shaped

- **Django apps** - which existing apps change (`core`, `masters`, `accounts`, `files`, `vendors`, `inbound`, `ptmapper`, `stockledger`, `finledger`, `aiagents`), and whether a new app is warranted.
- **PWA screens** - which existing screens change, which new screens are needed, which "coming soon" stubs come alive.
- **Rules and ledgers** - which of the 12 rules are in play; which documents, ledgers, and postings are touched.
- **Money slice: yes or no** - yes when the feature touches ledgers, postings, GST, valuation, or the document FSM. Say why.
- **Dependencies** - which touched area must be built first, and the suggested order.

## 3. Present and confirm

Show the impact as a short tree (impacted / not impacted, one line of "what changes" each) plus the suggested order.
Wait for confirmation; revise until confirmed.

## 4. Write the artifact

Write `docs/features/<slug>/feature-analysis.md`:

- **Source** - where the input came from.
- **Impact table** - app / screen, what changes, why.
- **Money slice** - yes/no and the reason. Yes triggers the money rules in `docs/agents/dev-process.md`.
- **Build order** - numbered, with dependencies.
- **Open questions** - anything ambiguous, as input for the phase 1 grill.

Then stop.
Phase 1 is a grill (`/grilling`, or `/grill-with-docs` for a money slice) - the developer starts it.
