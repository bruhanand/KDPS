# ISSUES

Here are the open issues in the repo:

<issues-json>

!`gh issue list -R bruhanand/KDPS --state open --label ready-for-agent --json number,title,body,labels,comments,assignees --jq '[.[] | {number, title, body, labels: [.labels[].name], assignees: [.assignees[].login], comments: [.comments[].body]}]'`

</issues-json>

The list above is filtered to `ready-for-agent` — the label any AI agent picks work up from.

# DROP THESE BEFORE YOU PLAN ANYTHING

An issue can carry the label and still not be workable. Drop it from the plan, and say in one line why:

1. **The body disagrees with the comments.** A ruling or decision left in a comment while the body still holds the old spec means the issue carries two specs, and an agent will faithfully build the wrong one. This has already happened once. Do not plan it — say which two disagree so a human can rewrite the body.
2. **It already has an assignee.** Somebody, or some other session, is on it.
3. **It is a PRD.** A `PRD` label means it is a parent holding a discussion, not a slice to build. Its children are the work.
4. **A named blocker is still open.** The issues-json above is filtered to
   `ready-for-agent` only — a blocker missing from that list is not evidence of
   anything; it could be closed, or open under a different label. Never infer
   status from absence. For every named blocker, check its real state with
   `gh issue view <N> -R bruhanand/KDPS --json state,stateReason`, and only
   drop the issue if that call says the blocker is still open.

# TASK

Analyze the open issues and build a dependency graph. For each issue, determine whether it **blocks** or **is blocked by** any other open issue.

An issue B is **blocked by** issue A if:

- B requires code or infrastructure that A introduces
- B and A modify overlapping files or modules, making concurrent work likely to produce merge conflicts
- B's requirements depend on a decision or API shape that A will establish

# OUTPUT

Group the workable issues into **waves**:

- **Wave 1** — issues with no blocking edges among themselves. They can all be built in parallel from today's `main`, each on its own branch in its own sandbox.
- **Wave 2 and later** — issues blocked by an earlier wave. Nothing merges during this run, so these cannot be built now; they are reported and picked up by a later run, after wave 1's PRs have merged.

Assign every issue a branch name in the format `sandcastle/issue-{id}-{slug}`.

Output the plan as a JSON object wrapped in `<plan>` tags — an array of waves, each wave an array of issues:

<plan>
{"waves": [[{"id": "42", "title": "Fix auth bug", "branch": "sandcastle/issue-42-fix-auth-bug"}], [{"id": "57", "title": "Build on 42", "branch": "sandcastle/issue-57-build-on-42"}]]}
</plan>

Include only workable issues. If every issue is blocked by another open issue, put the single best candidate (fewest or weakest dependencies) alone in wave 1.
