# Review

Review the diff between `HEAD` and a fixed point. Used inside
[implement.md](implement.md) before every PR, and available standalone via the `code-review` skill.

## Shape

**One subagent**, on the strongest model available, covering Spec and Correctness and Safety together.
**A second subagent** on the ledger axis when the change touches money.

There is no standards subagent. Ruff, mypy, import-linter and tsc already enforce everything mechanical,
and the rest is taste, which `simplify` covers when it is asked for. A third agent re-reading the same
diff to report style opinions is the most expensive finding-per-token in this pipeline.

Never let the model that wrote the code be the only one grading it.

## 1. Pin the fixed point

Whatever the user supplied - a SHA, a branch, a tag, `main`, `HEAD~5`. If they did not supply one, ask.

Confirm it resolves (`git rev-parse`) and the diff is non-empty **before** spawning anything. A bad ref
should fail here, not inside a subagent.

Capture the diff command once: `git diff <fixed-point>...HEAD` - three dots, so the comparison is
against the merge base. Note the commits with `git log <fixed-point>..HEAD --oneline`.

## 2. Find the spec

In this order: an issue reference in the commit messages, fetched per
[../issue-tracker.md](../issue-tracker.md), including the `docs/features/<slug>/` documents if the
issue names a folder; a path passed as an argument; a spec file matching the branch name. If nothing is
found, ask. If there genuinely is no spec, the review runs without the Spec half and says so.

## 3. Spawn

Give the subagent the diff command, the commit list, the spec path or contents, and the checklist
below pasted in full - it has no other access to it. Brief:

> Report findings as `[critical | warning | suggestion]` / `File: <path>:<line>` / `Issue:` / `Fix:`.
> Money and access findings are never below critical. Under 400 words. Do not report style opinions,
> naming preferences, or anything a linter or type checker would catch.

<checklist>

**Spec**
- Requirements the spec asked for that are missing or partial.
- Behaviour in the diff nobody asked for - scope creep.
- Requirements that look implemented but where the implementation looks wrong.
- Quote the spec line for each finding.

**Correctness**
- The logic does what the spec intends. Watch for off-by-one, unhandled `None`, race conditions.
- Errors are handled at every call site. No silently swallowed exceptions, no ignored return values.

**Safety**
- No hardcoded secrets, URLs, or environment-specific values.
- No raw SQL string concatenation. Parameterised queries only.
- Access scope fails closed. A scope check defaulting to allow, or an unscoped queryset, is critical.
  Read scope has failed open in this codebase before.

</checklist>

On a money slice, the second subagent gets this instead:

<money-checklist>

- Amounts are integer paise end to end. A float anywhere near money is critical.
- Every posting goes through `post_entries` and balances. A ledger written any other way is critical.
- Ledgers are append-only and written only by documents. No update in place, no reposting.
- Docstatus transitions follow the FSM. No state jumps.
- A reversal must not re-derive editable master data - it posts to the wrong account while the trial
  balance still reads zero, and no detector in this codebase catches it. Snapshot on the money line.
- Money renders in Indian format (`₹2,85,000`), never raw paise.
- Reconcile every posting in the diff against the design's postings section. The posting catalog is
  background; where it disagrees with the code's established postings, the code is the reference.

</money-checklist>

## 4. Report

Present the findings as returned, under one heading per subagent. End with one line: the count and the
worst finding per axis. Do not merge or re-rank across axes - a change can pass one and fail another,
and re-ranking is how the failing one gets buried.

Inside `implement`, one fix round follows and then the phase moves on. A finding that survives it goes
in the PR body or through [escalation.md](escalation.md).
