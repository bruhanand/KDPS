# Domain docs

This repo uses a **single-context** domain layout:

- One **`CONTEXT.md`** at the repo root — the domain language and project context.
- Architecture decisions in **`docs/my-understanding/system-design/adr/`** — one ADR per decision, numbered (`0001-stack.md` … `0007-entity-gstin-scoping.md`). This is the ratified ADR chain; it sits with the rest of the design corpus, not at the repo root.

There are no per-package or per-module context files. When recording domain language, update the single root `CONTEXT.md`; when recording a decision, add the next numbered ADR under `docs/my-understanding/system-design/adr/`.

Note: `docs/adr/` at the repo root is **not** the ADR home — do not write there.
