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

Then output exactly one of:

<findings>FOUND</findings>
<findings>NONE</findings>
