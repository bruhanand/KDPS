# Issue tracker

Issues live in **GitHub Issues** for the `bruhanand/KDPS` repository, used via the `gh` CLI. This is the **single source of truth** for work.

## Commands

- Create: `gh issue create -R bruhanand/KDPS --title "..." --body "..."` (heredoc for multi-line bodies)
- List: `gh issue list -R bruhanand/KDPS --state open --json number,title,body,labels,comments`
- View: `gh issue view <number> -R bruhanand/KDPS --comments`
- Comment: `gh issue comment <number> -R bruhanand/KDPS --body "..."`
- Label: `gh issue edit <number> -R bruhanand/KDPS --add-label "..."` / `--remove-label "..."`
- Close: `gh issue close <number> -R bruhanand/KDPS --comment "..."`

Do not track work in scratch files, local TODO lists, or other systems — open a GitHub issue instead.

## When a skill says "publish to the issue tracker"

Create a GitHub issue on `bruhanand/KDPS`.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> -R bruhanand/KDPS --comments`.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo starts treating external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents (`gh pr view --comments`, `gh pr diff`, `gh pr comment`, `gh pr edit --add-label`, `gh pr close`), keeping only external authors (`authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, `NONE`). GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: one issue labelled `wayfinder:map`, holding the Destination / Notes / Decisions-so-far / Fog body. `gh issue create -R bruhanand/KDPS --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research` / `prototype` / `grilling` / `task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**. Add an edge with `gh api --method POST repos/bruhanand/KDPS/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/bruhanand/KDPS/issues/<n> --jq .id` — not the `#number` or `node_id`). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children, drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> -R bruhanand/KDPS --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n>`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
