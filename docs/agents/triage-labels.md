# Triage labels

Mapping from triage state to the GitHub label applied on `bruhanand/KDPS`:

| Triage state | GitHub label |
|---|---|
| needs-triage | `needs-triage` |
| needs-info | `needs-info` |
| ready-for-agent | `Sandcastle` |
| ready-for-human | `ready-for-human` |
| wontfix | `wontfix` |

## Why `ready-for-agent` → `Sandcastle`

The **Sandcastle** agent picks up issues via `gh issue list --label Sandcastle`. Any issue that is AFK-ready (ready for an agent to work autonomously) **must carry the `Sandcastle` label** so the agent can find it. There is no separate `ready-for-agent` label — `Sandcastle` is it.
