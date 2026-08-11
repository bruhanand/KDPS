---
name: triage
description: Turn an unlabelled issue into either a ready issue an agent can build from, or a blocked issue with one plain question for Anand.
disable-model-invocation: true
---

# Triage

Read `docs/agents/phases/triage.md` and follow it.

Invoked in natural language - "show me anything that needs my attention", "let's look at #42",
"move #42 to ready". A direct instruction to set a label is trusted: confirm what you are about to do,
then do it, and skip the grilling.
