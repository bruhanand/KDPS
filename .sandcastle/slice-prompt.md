# TASK

Gate issue {{TASK_ID}} ({{ISSUE_TITLE}}), then write the slice plan the builder
will work from.

You are the **only agent in this pipeline that reads the design corpus**. The
builder sees your plan and nothing else, so every rule that binds this slice
must be *in* the plan — quoted, with its source path. A rule you leave out is a
rule the builder will break.

The branch is {{BRANCH}} (already checked out). Change no code. Your one
artifact is `{{ART_DIR}}/slice-plan.md` — `mkdir -p {{ART_DIR}}` first.

# GATE — three checks before anything else

Pull the issue: `gh issue view {{TASK_ID}} -R bruhanand/KDPS --comments`.
If it names a parent PRD or a feature folder (`docs/features/<slug>/`), read
those too — the whole thing, not just the section that names this slice.

1. **The body matches the comments.** A ruling left in a comment while the body
   holds the old spec is two specs, and the wrong one gets built. This has
   happened before.
2. **Declared blockers are closed.**
3. **No open PR already touches the same files for the same reason**
   (`gh pr list -R bruhanand/KDPS --state open`).

Any check fails → comment on the issue saying which check and why, then output
`<gate>STOP: <one-line reason></gate>` and finish. Write no plan.

# READ THE CORPUS

In this order:

1. **`CONTEXT.md`** (repo root) — the domain language, the 12 rules, the kernel
   contracts, and the locked money decisions.
2. **`docs/my-understanding/system-design/adr/`** — the ratified ADRs touching
   the area this slice changes.
3. The module's design folder under `docs/my-understanding/system-design/`.

Two hard rules:

- A design that breaks one of the 12 rules must change the rule consciously
  first, on `00-system-architecture.html`. You are not authorised to do that.
  If the slice appears to require it, that is a STOP, not a workaround:
  comment on the issue naming the rule, output `<gate>STOP: …</gate>`.
- The same for a contradiction with a ratified ADR, or a money slice (ledgers,
  postings, GST, valuation, document FSM) whose postings design is not written
  and locked. Money without a locked design is always a STOP.

# THE PLAN

Write `{{ART_DIR}}/slice-plan.md`, under two pages, in this shape:

- **What to build** — the slice in plain words, then the issue's acceptance
  criteria verbatim (the QA phase drives exactly these later).
- **Seams and tests** — the seams the spec names; prefer an existing seam,
  fewest seams wins. Which test files to extend.
- **Files likely touched.**
- **Binding rules** — every rule, ADR, or locked decision that constrains this
  slice, QUOTED: the sentence itself plus its file path. A paraphrase is not a
  quote. Use the glossary's vocabulary — a concept with no term usually means
  invented language.
- **Postings** (money slices only) — every ledger entry the slice writes, both
  legs, through `post_entries`.
- **Out of scope** — what the issue does not ask for.

Then output `<gate>GO</gate>`.
