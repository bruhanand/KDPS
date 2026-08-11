# Issue labels

A label answers one question: **may an agent start on this right now?**
That is two states plus one orthogonal tag.

| Label | Meaning | Who acts next |
|---|---|---|
| *(none)* | Nobody has looked at it. No agent may start. | an agent, via `triage` |
| `ready` | The body is a complete spec. Any agent can start. | an agent, via `implement` |
| `blocked` | Needs Anand. The last comment says what is needed. | Anand |
| `money` | Orthogonal tag. Ledgers, postings, GST, valuation, the document FSM. | - |

No label is the default, so an unreviewed issue fails closed.

`money` is a label rather than something derived from the spec because `implement` needs to know before
it opens any document: it changes the review shape and the escalation rule.

Category (`bug` / `enhancement`) is optional and carries no process meaning. Use it if it helps you
scan the list; nothing branches on it.

There is no `wontfix` label. A rejected issue is closed as not planned, with the reason in the closing
comment.

## The state machine

```
(no label) ──triage──→ ready ──implement──→ PR opened, issue stays open until merged
     │                   ↑
     └──triage──→ blocked┘
                    ↑
        implement ──┘   (escalation: a finding an agent must not decide)
```

`blocked` → `ready` requires the issue **body** to be rewritten to carry the ruling. A ruling that
lives only in a comment leaves two specs on the issue.

## Finding work

```
gh issue list -R bruhanand/KDPS --label ready
gh issue list -R bruhanand/KDPS --label blocked        # Anand's queue
gh issue list -R bruhanand/KDPS --search 'no:label'    # untriaged
```

`ready` is deliberately tool-neutral - Claude Code, Codex, or whatever comes next reads the same label.

## Migration status

**Not yet migrated.** The tracker still carries the older five-state scheme
(`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`).
Until the migration runs, read `ready-for-agent` wherever this document says `ready`, and
`needs-info` or `ready-for-human` wherever it says `blocked`.

The mapping when it runs:

| Old | New |
|---|---|
| `needs-triage` | *(no label)* |
| `needs-info` | `blocked` |
| `ready-for-human` | `blocked` |
| `ready-for-agent` | `ready` |
| `wontfix` | close as not planned |

(`ready-for-agent` itself replaced a tool-specific `Sandcastle` label on 25 Jul 2026, for the same
reason: a label named after one agent makes the workflow mean nothing to the others.)
