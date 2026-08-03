# TASK

Review branch {{BRANCH}} on the **Spec axis only** — round {{ROUND}}: does the
diff faithfully implement what issue {{TASK_ID}} asked for?

You are one of three reviewers, each on one axis, so their findings never
pollute each other (the /code-review pattern). Standards and correctness are
not your job. You **change nothing** — you report. A separate fixer acts on
your findings file.

# THE DIFF

!`git diff {{SOURCE_BRANCH}}...{{BRANCH}}`

## Commits on this branch

!`git log {{SOURCE_BRANCH}}..{{BRANCH}} --oneline`

# WHAT ELSE TOUCHES THIS — ASK THE GRAPH

`app/` is indexed as a code graph — every file, class and function, and what
calls what, from the AST. Use it for blast radius: the diff shows what changed,
the graph shows who depended on it. **Run these from `app/`** (`cd app`):

```bash
graphify explain "sidebarRows()"            # a changed symbol, its callers and callees
graphify explain "navConfig.ts"             # a changed file's neighbours
graphify path "Sidebar()" "sidebarRows()"   # how two things connect
graphify query "what reads the RBAC matrix" # broad: where does this live
```

`explain` takes a **symbol or file name**, never a repo path; an ambiguous name
prints the matching node ids, so pass one of those back. The graph was built
when the sandbox came up, so it predates this branch's commits — if the diff
adds or renames a symbol you want to trace, run `graphify update .` first
(~10s, AST only). It indexes `app/` only, and it tells you *where to look*,
never *what the code says* — open the file and read the line before you raise a
finding on it.

# THE SPEC

The spec is the **source**, not the derivative:

1. `gh issue view {{TASK_ID}} -R bruhanand/KDPS --comments` — the issue body
   is the spec of record; a ruling in the comments that the body already
   reflects binds too.
2. Its parent PRD, if it names one.
3. The feature folder, if the issue names one: `docs/features/<slug>/`
   (requirements, api-contract, db-design, design).

`{{ART_DIR}}/slice-plan.md` exists but is a *derived* plan — if the diff
matches the plan and not the issue, that is a finding against the diff.

# REPORT

Report three things, quoting the spec line for each finding:

- **(a) Missing or partial** — requirements the spec asked for that the diff
  does not deliver.
- **(b) Scope creep** — behaviour in the diff the spec never asked for.
- **(c) Implemented but wrong** — requirements that look done but whose
  implementation contradicts the spec's words.

Write `{{ART_DIR}}/findings-spec.md` (create the directory if needed), **under
400 words**. If the diff is faithful, write "No findings."

# ALREADY-TRIAGED FINDINGS

Before you report, read `{{ART_DIR}}/deviations.md` if it exists. The fixer
writes it when it consciously leaves a finding alone, and the reasoning is
usually the issue's own "Out of scope" section.

A finding recorded there is **residual**, not actionable. Put it under a
`## Residual` heading so the round reads as deliberate rather than missed, and
do **not** let it decide your tag. The one exception: if you can show the
deviation's stated reasoning is *wrong*, raise it as a normal finding and say
why.

Then output exactly one of:

<findings>FOUND</findings>
<findings>NONE</findings>

Tag on what needs action **this round**, not on what the file mentions. If
everything outstanding is residual, or the diff is clean, the tag is NONE —
FOUND costs a whole extra fix round, and a fixer handed the same deferred
finding twice may break scope to satisfy it.
