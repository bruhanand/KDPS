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
4. **A named blocker is still open.**

# TASK

Analyze the open issues and build a dependency graph. For each issue, determine whether it **blocks** or **is blocked by** any other open issue.

An issue B is **blocked by** issue A if:

- B requires code or infrastructure that A introduces
- B and A modify overlapping files or modules, making concurrent work likely to produce merge conflicts
- B's requirements depend on a decision or API shape that A will establish

An issue is **unblocked** if it has zero blocking dependencies on other open issues.

For each unblocked issue, assign a branch name using the format `sandcastle/issue-{id}-{slug}`.

# OUTPUT

Output your plan as a JSON object wrapped in `<plan>` tags:

<plan>
{"issues": [{"id": "42", "title": "Fix auth bug", "branch": "sandcastle/issue-42-fix-auth-bug"}]}
</plan>

Include only unblocked issues. If every issue is blocked, include the single highest-priority candidate (the one with the fewest or weakest dependencies).
