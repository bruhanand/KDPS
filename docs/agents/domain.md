# Domain docs

This repo uses a **single-context** domain layout:

- One **`CONTEXT.md`** at the repo root — the domain language and project context.
- Architecture decisions in **`docs/adr/`** at the repo root — one ADR per decision.

There are no per-package or per-module context files. When recording domain language, update the single root `CONTEXT.md`; when recording a decision, add an ADR under `docs/adr/`.
