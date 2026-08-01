# TASK

Review branch {{BRANCH}} on the **Correctness & Safety axis only** — round
{{ROUND}}. This is a money system for a real retailer, so conformance to the
ratified design comes first, correctness second. A change that is elegant and
well-tested but quietly breaks a kernel contract is a worse outcome than an
ugly one that holds the line.

You are one of three reviewers, each on one axis, so their findings never
pollute each other (the /code-review pattern). Standards and spec-fidelity are
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

# CONFORMANCE — the primary axis

Read `CONTEXT.md` and the ADRs under `docs/my-understanding/system-design/adr/`
that touch this area, then ask:

- Does it go **through** the kernel, or around it? Documents write ledgers — a
  ledger row without a `core.Document` behind it is a defect.
- Are financial postings balanced and through `post_entries`, or a single-entry
  running balance bolted on?
- Is money integer paise end to end — no floats, no rupee `Decimal`s?
- Are posted rows append-only? Corrections must be reversing entries, never
  edits or deletes.
- Is `docstatus` moved through the FSM rather than assigned? Is anything the
  kernel says is derived being stored instead?
- Does SKU stay Style × Size × Color the whole way through?
- Are ownership and return-terms still two axes, with labels derived?
- Is GST date-effective data, and is cost taken from P RATE directly rather
  than back-derived?
- Does it **flag** anomalies rather than block trading?
- Is new variation expressed as data (a row) rather than a new code branch?
- Does anything break one of the 12 rules in `00-system-architecture.html`, or
  contradict a ratified ADR? Say so explicitly — `Contradicts ADR-000N` —
  rather than letting it through.

# CORRECTNESS & SAFETY

- The logic does what the issue intends; off-by-one, unhandled `None`, race
  conditions.
- Errors handled at every call site — no swallowed exceptions or ignored
  returns.
- New behaviour covered by tests that would fail without the change; any
  existing assertion weakened, deleted or skipped to get green is a finding,
  always.
- Model changes ship their migration.
- No hardcoded secrets or environment-specific values; no raw SQL string
  concatenation.
- **Access scope fails closed** — a scope check defaulting to "allow" or an
  unscoped queryset is critical (read scope has failed open here before).
- Money renders in Indian format (`₹2,85,000`), never raw paise.

# REPORT

Write `{{ART_DIR}}/findings-correctness.md` (create the directory if needed),
**under 400 words**. Per finding:
`[critical | warning | suggestion]` / `File: <path>:<line>` / `Issue:` /
`Fix:`. **Money and access findings are never below critical.** If the diff is
clean, write "No findings."

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
