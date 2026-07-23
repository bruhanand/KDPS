# Domain docs

This repo uses a **single-context** domain layout:

- One **`CONTEXT.md`** at the repo root — the domain language and project context.
- Architecture decisions in **`docs/my-understanding/system-design/adr/`** — one ADR per decision, numbered (`0001-stack.md` … `0007-entity-gstin-scoping.md`). This is the ratified ADR chain; it sits with the rest of the design corpus, not at the repo root.

There are no per-package or per-module context files. When recording domain language, update the single root `CONTEXT.md`; when recording a decision, add the next numbered ADR under `docs/my-understanding/system-design/adr/`.

Note: `docs/adr/` at the repo root is **not** the ADR home — do not write there.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root.
- The ADRs in **`docs/my-understanding/system-design/adr/`** that touch the area you're about to work in.

There is no `CONTEXT-MAP.md` here, and there never should be — this is a single-context repo.

## Use the glossary's vocabulary

When your output names a domain concept (an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md` and the design glossary. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider), or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts a ratified ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0003 — but worth reopening because…_

The same rule applies to the 12 rules in `docs/my-understanding/system-design/00-system-architecture.html`: a design that breaks a rule must change the rule consciously on that page first.
