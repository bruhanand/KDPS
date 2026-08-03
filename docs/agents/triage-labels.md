# Triage labels

Mapping from triage state to the GitHub label applied on `bruhanand/KDPS`:

| Triage state | GitHub label |
|---|---|
| needs-triage | `needs-triage` |
| needs-info | `needs-info` |
| ready-for-agent | `ready-for-agent` |
| ready-for-human | `ready-for-human` |
| wontfix | `wontfix` |

The label names are the state names. There is no indirection to learn.

## `ready-for-agent` is tool-neutral

An issue carrying `ready-for-agent` is AFK-ready: fully specified, with an agent brief attached, and safe for **any** AI agent to pick up and work autonomously — Claude Code, Sandcastle, Codex, or whatever comes next.

Agents find their work with:

```
gh issue list --label ready-for-agent
```

**Changed 25 July 2026.** This used to map to a `Sandcastle` label, named after the one agent that consumed it. That tied the workflow to a single tool: an issue was "ready" only in the sense that Sandcastle could see it, and every other agent had to be told about the alias. All 27 issues carrying `Sandcastle` were migrated to `ready-for-agent` on that date; the state means the same thing, it is just no longer named after a vendor.

## The state machine

An untriaged issue starts at `needs-triage`. From there it moves to `needs-info`, `ready-for-agent`, `ready-for-human`, or `wontfix`. `needs-info` returns to `needs-triage` once the reporter replies.

Every triaged issue should carry **exactly one category** (`bug` or `enhancement`) and **exactly one state**. Two state labels on one issue is a bug in the triage, not a richer signal.

`ready-for-human` is the deliberate opposite of `ready-for-agent`: same standard of specification, but flagged as needing a person — judgement calls, external access, design decisions, or manual testing.
