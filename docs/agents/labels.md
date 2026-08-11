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
comment. There is no `needs-triage` label either - no label *is* the untriaged state.

Three tags exist for reasons outside the phase chain and are the only other labels an agent will meet:

| Tag | What it means |
|---|---|
| `PRD` | A legacy umbrella issue: design of record, its buildable work already split into child issues. **Triage and implement both skip these** - act on the children. New features write their spec to `docs/features/<slug>/` instead, so no new issue gets this tag. |
| `ci-red` | Raised automatically by `.github/workflows/ci.yml` when `main` goes red, and closed by hand once it is green. Never applied by a person. |
| `duplicate` | Applied at close time, with the surviving issue named in the closing comment. |

`kernel` and `deferred-access` survive on closed issues as history. Do not apply them to anything new.

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

The three milestones (`Phase 0 - the pause`, `Phase 1 - pilot readiness`, `Phase 2 - live money / go-live`)
carry priority, which no label does. A `ready` label says an agent *may* start; the milestone says
whether it *should* be next. Both queries belong in a work-picking command:

```
gh issue list -R bruhanand/KDPS --label ready --milestone "Phase 0 - the pause (correctness + hygiene)"
```

## Migration status

**Migrated 11 August 2026.** Every open issue now carries this scheme, and the old labels are gone
from the tracker.

`ready-for-agent` was *renamed* to `ready` and `ready-for-human` to `blocked`, so closed issues keep
their history under the new names. `needs-triage`, `needs-info`, `wontfix`, `Sandcastle`, `question`
and the unused GitHub defaults were deleted.

| Old | New |
|---|---|
| `needs-triage` | *(no label)* |
| `needs-info` | `blocked` |
| `ready-for-human` | `blocked` (renamed) |
| `ready-for-agent` | `ready` (renamed) |
| `wontfix` | close as not planned |

Two cautions the migration itself taught, both worth re-reading before relabelling anything:

- **`ready-for-human` did not mean `blocked`.** It was used for two different things: work only a
  person can do (#190 needs hands on a printer) and work an agent can do that a person reviews before
  merge (#73's grid design). The second is not blocked - `implement` never merges anyway. Read the
  body before mapping; the mechanical translation gets it wrong about half the time.
- **A label can outlive the comment that changed it.** #79 was moved back to agent-eligible by a
  triage comment whose ruling never reached the body, and it sat with a stale question in the body and
  no state label for two weeks. Rewrite the body, then set the label.
