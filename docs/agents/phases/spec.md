# Phase 1 - Spec

Input: everything Anand has on the feature - notes, meeting minutes, client asks, issue references.
Output: `docs/features/<slug>/spec.md`. Ask for a kebab-case slug if one was not given.

This phase is the blast radius **and** the grill. The impact analysis is the opening move, not a
separate document: it exists to aim the questions, and once the questions are answered it is a section
of the spec.

## 1. Read the context

Read `CONTEXT.md` and the ADRs that touch the area. If the design corpus
(`docs/my-understanding/system-design/`) has a module folder for this area, read it as background -
it may be stale. Then read the code the feature touches: the code is the truth for what exists and
how it behaves today. A corpus claim goes into the spec only once the code confirms it, or with an
explicit flag that it describes a change.

Facts you can look up in the repo are never questions for Anand. Decisions always are.

## 2. State the blast radius and confirm it

Show it as a short tree - impacted and not impacted, one line of "what changes" each - and wait for
confirmation before grilling. Revise until confirmed.

- **Django apps** - which of `core`, `masters`, `accounts`, `files`, `vendors`, `inbound`, `ptmapper`,
  `stockledger`, `finledger`, `aiagents` change, and whether a new app is warranted.
- **PWA screens** - which existing screens change, which are new, which "coming soon" stubs come alive.
- **Rules and ledgers** - which of the 12 rules are in play; which documents, ledgers and postings are
  touched.
- **Money slice: yes or no**, and why. Yes when it touches ledgers, postings, GST, valuation, or the
  document FSM. A yes turns on the money rules in [../dev-process.md](../dev-process.md) and makes
  phase 2 mandatory.
- **Build order** - which touched area must exist first.

## 3. Grill

Interview Anand relentlessly until you reach a shared understanding. Walk each branch of the decision
tree, resolving dependencies between decisions one at a time.

- **One question at a time.** Several at once is bewildering.
- **Always give your recommended answer** with the question.
- **Force a concrete number** for every quantitative value: expiry, retries, limits, thresholds,
  lengths, timeouts, retention. "Reasonable" and "fast" are not values.
- **Money slices grill against the corpus** (`grill-with-docs`), so the design is locked against the
  design of record before any code exists, and new domain language lands in `CONTEXT.md` or an ADR as
  you go.

Do not write the spec until Anand confirms you have reached a shared understanding.

## 4. Write `spec.md`

- **Source** - where the input came from.
- **Problem** - from the user's point of view, in the project's own vocabulary.
- **Blast radius** - the confirmed table from step 2: app or screen, what changes, why.
- **Money slice** - yes or no, and the reason.
- **Functional requirements** - numbered, each independently checkable.
- **Non-functional requirements** - with their numbers.
- **Edge cases.**
- **Out of scope.**
- **Build order** - numbered, with dependencies.
- **Open questions** - anything a CA or a store must rule on before build.

Then stop. Phase 2 is `design`, and Anand starts it.
