# Escalation

Read this when a review or QA finding looks like more than a bug.

## The test

Not how serious the finding is - a kernel breach is serious and has one known correct answer, so fixing it is exactly what an agent is for.
The test is: **is the answer already written down?**

- **Written down** - the 12 rules, a locked decision, an ADR, the spec's own acceptance criteria - then **fix it**. You are applying a rule, not making one.
- **Not written down** - then **stop**. Fixing it would mean inventing policy.

Before fixing, quote the rule or decision you are applying - the sentence, and where it lives.
A passage that nearly fits is not a quote; no quote means it is not written down, which means stop.

## Fix it

- A kernel or rule breach: a ledger written from something other than a document, a posting avoiding `post_entries` or unbalanced, a derived figure hand-entered, stock below style x size x colour, a variation hard-coded that Rule 12 says is data.
- Access control failing open.
- The Spec axis says you solved a different problem, and the spec is clear about which problem it wanted. Redo the work.

## Stop and ask

- **Anything about money** - absolute. Wrong valuation, liability, tax, a posting that would need reversing, money rendered wrong. Fix it if you can, but never open a real PR on it - a confident wrong fix reaches the alpha and corrupts a ledger that has to be unwound by hand. This holds even when the corpus answers the question.
- The design corpus is silent, or two fair readings exist.
- A CA ruling is pending, including the five gated money items.
- The blast radius has grown into a feature rather than an issue.
- A finding survived two honest fix attempts.

## What stopping looks like

Preserve the work: push the branch, open a **draft** PR saying what was attempted, where it stopped, and the finding; relabel the issue `ready-for-human`, comment the question, and stop - no real PR.

Write the question for a human in simple, everyday English, the way you would say it to a shop owner in Patna: shirts, brands, stores and bills - never models or endpoints; rupees the Indian way (`₹2,85,000`), dates in words; one question at a time, the choices given, and which you would pick, in one line.
File paths and findings tables live in the draft PR - the question must be answerable without reading code.

A stopped issue with an honest question is a good outcome.
A merged PR built on a finding you talked yourself out of is what this exists to prevent.
