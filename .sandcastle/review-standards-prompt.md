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
