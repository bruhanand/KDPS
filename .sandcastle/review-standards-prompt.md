# TASK

Review branch {{BRANCH}} on the **Standards axis only** — round {{ROUND}}.

You are one of three reviewers, each on one axis, so their findings never
pollute each other (the /code-review pattern). Spec and correctness are not
your job. You **change nothing** — you report. A separate fixer acts on your
findings file.

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

# WHAT TO CHECK

Two sources, both in this repo:

1. **`.sandcastle/CODING_STANDARDS.md`** — the documented house rules. A breach
   is a **hard violation**: cite the rule.
2. **The 12-smell baseline** in `.agents/skills/code-review/SKILL.md` (step 3,
   "Identify the standards sources") — read it there; Mysterious Name through
   Refused Bequest. Each is a labelled **judgement call**, never a hard
   violation: name the smell and quote the hunk.

Two rules bind them: a documented repo standard always overrides the baseline,
and anything tooling already enforces (ruff, mypy, tsc) is skipped — cloud CI
will catch those.

# REPORT

Write `{{ART_DIR}}/findings-standards.md` (create the directory if needed),
**under 400 words**. Per finding: hard violation or judgement call, file:line,
the rule or smell, and the fix. If the diff is clean, write "No findings."

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
