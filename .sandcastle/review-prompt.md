# TASK

Review the code changes on branch `{{BRANCH}}`.

This is a money system for a real retailer, so the review has an order of
priority. **Conformance to the ratified design comes first**, correctness second,
clarity third. A change that is elegant and well-tested but quietly breaks a
kernel contract is a worse outcome than an ugly one that holds the line.

# CONTEXT

## Branch diff

!`git diff {{SOURCE_BRANCH}}...{{BRANCH}}`

## Commits on this branch

!`git log {{SOURCE_BRANCH}}..{{BRANCH}} --oneline`

# REVIEW PROCESS

1. **Understand the change**: read the diff and commits above, then read the
   issue it claims to close and its parent PRD (`gh issue view <n> -R
   bruhanand/KDPS --comments`).

2. **Check conformance to the design** — the primary axis. Read `CONTEXT.md` and
   the ADRs under `docs/my-understanding/system-design/adr/` that touch this
   area, then ask:
   - Does it go **through** the kernel, or around it? Documents write ledgers.
     A ledger row without a `core.Document` behind it is a defect.
   - Are financial postings balanced and through `post_entries`, or a
     single-entry running balance bolted on?
   - Is money integer paise end to end — no floats, no rupee `Decimal`s?
   - Are posted rows treated as append-only? Corrections must be reversing
     entries, never edits or deletes.
   - Is `docstatus` moved through the FSM rather than assigned? Is anything the
     kernel says is derived being stored instead?
   - Does SKU stay Style × Size × Color the whole way through?
   - Are ownership and return-terms still two axes, with labels derived?
   - Is GST treated as date-effective data, and is cost taken from P RATE
     directly rather than back-derived?
   - Does it **flag** anomalies rather than block trading?
   - Is new variation expressed as data (a row) rather than a new code branch?
   - Does anything here break one of the 12 rules in
     `00-system-architecture.html`, or contradict a ratified ADR? If so, say so
     explicitly — `Contradicts ADR-000N` — rather than letting it through.

3. **Check correctness**:
   - Does the implementation match the issue's intent? Are edge cases handled?
   - Are new/changed behaviours covered by tests that would fail without the change?
   - Has any existing assertion been weakened, deleted or skipped to get green?
     Treat that as a finding, always.
   - Do model changes ship their migration?
   - Are there unsafe casts, `any` types, or unchecked assumptions?
   - Does the change introduce injection vulnerabilities, credential leaks,
     scope/permission holes that fail open, or other security issues?

4. **Improve clarity, consistency and maintainability** — without changing what
   the code does. Look for:
   - Unnecessary complexity and nesting
   - Redundant code and abstractions
   - Unclear variable and function names
   - Related logic that belongs together
   - Comments that restate obvious code
   - Nested ternaries — prefer switch statements or if/else chains
   - Over-compact code where explicit would read better

5. **Maintain balance**: avoid over-simplification that could:
   - Reduce code clarity or maintainability
   - Create overly clever solutions that are hard to understand
   - Combine too many concerns into single functions or components
   - Remove helpful abstractions that improve code organization
   - Make the code harder to debug or extend

6. **Apply project standards**: follow the coding standards defined in @.sandcastle/CODING_STANDARDS.md

# EXECUTION

Verify with the real gate — `npm run ci` — before and after anything you change.
PostgreSQL is already running in this sandbox; the live-API suites under
`app/backend/tests/` reporting as *skipped* is expected, not a failure.

For clarity and consistency findings (step 4): fix them directly on this branch,
run `npm run ci`, and commit describing the refinements. Never change what the
code does — only how it does it.

For conformance and correctness findings (steps 2 and 3): fix them if the fix is
clear and contained, and say so in the commit body. If the finding is a design
conflict — a broken rule, a contradicted ADR, a kernel contract worked around —
do **not** paper over it. Leave it in place and comment on the issue with the
specific rule or ADR it breaks, so a human rules on it:
`gh issue comment <n> -R bruhanand/KDPS --body "..."`

If the code is already clean, conformant and well-structured, do nothing.

Once complete, output <promise>COMPLETE</promise>.
