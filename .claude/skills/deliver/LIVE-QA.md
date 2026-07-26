# Live QA

Prove the built thing works by using it, in a real browser, the way a store user would.
A green suite and a broken screen coexist happily: the button calls nothing, the table renders empty, the money renders as `285000` instead of `₹2,85,000`.
This gate catches exactly that.

Use whichever browser tooling the session has; either can drive the page, screenshot it, and read network and console.
Load the tools in one `ToolSearch` call, never one per tool.

**Claude app - Claude in Chrome** (the normal case):

```
ToolSearch: select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__form_input,mcp__claude-in-chrome__read_network_requests,mcp__claude-in-chrome__read_console_messages
```

Call `tabs_context_mcp` first, then **open a new tab** with `tabs_create_mcp` - never a tab or tab id from another session or run.

This drives the user's own Chrome, with two consequences:

- **Someone may already be logged in.** This gate logs in as a *specific role* and proves what that role can and cannot see, so log out first or use a fresh profile - a pass that ran as whoever happened to be signed in proves nothing.
- **Trigger no alerts, confirms or modal dialogs.** They block every subsequent command until dismissed by hand. If one is unavoidable, say so before pressing.

**Terminal - chrome-devtools MCP**, when `mcp__chrome-devtools__*` is what is available:

```
ToolSearch: select:mcp__chrome-devtools__new_page,mcp__chrome-devtools__navigate_page,mcp__chrome-devtools__take_snapshot,mcp__chrome-devtools__take_screenshot,mcp__chrome-devtools__click,mcp__chrome-devtools__fill,mcp__chrome-devtools__fill_form,mcp__chrome-devtools__list_network_requests,mcp__chrome-devtools__list_console_messages,mcp__chrome-devtools__wait_for
```

The rest of this file says what to *do*; neither toolset changes what has to be true.

## 1. Preconditions: is the thing under test the thing you built?

Skip this and you will debug a ghost - a container on `:8001` once served months-old code against a migrated schema (issue #93).

**a. Is a stack already up?**

```bash
lsof -ti:8001 -ti:3000
```

Ports free: bring the stack up in the background with `./scripts/dev.sh`.
Ports held: find out by what first:

```bash
ps -o command= -p $(lsof -ti:8001)
docker ps --filter publish=8001
```

Another `/deliver` session owns it: **wait** - say so plainly and queue.
A stray container from an old checkout: stop and report; killing another session's stack or passing `--free-ports` blind is off the table.

**b. Does the server carry this branch's code?**

```bash
curl -s localhost:8001/api/health | python3 -m json.tool
```

Compare the `migrations` digest against this working tree (`core/identity.py` computes it from the migration files the process carries).
If they differ the server is not running your code: restart it, and trust nothing the browser shows until they match.

**c. Does the database match the migrations?**

```bash
cd app/backend && uv run python manage.py check_db_drift
```

Drift means the shared local Postgres carries schema from another branch.
Fix it before QA: `./scripts/dev.sh --reset` rebuilds and reseeds.

**d. Is the data there?**

Screens assume `seed_foundation`, `seed_ptmapper` and `seed_outbound_demo` have run.
An empty screen is usually missing seed, not a bug - confirm before filing one.

State all four results in one line before touching the browser.

## 2. Build the flow list

From the issue's acceptance criteria, write the flows you will exercise - one per criterion, in the user's words.

Add three regardless of the issue:

- The **role** the feature belongs to, logged in as that user (`memory/test_credentials.md`) - `superadmin` bypasses the RBAC matrix, so it proves nothing about what a store user sees.
- One **scope-negative** flow: a user who should *not* see this data logs in and does not see it. Read-scope has failed open in this codebase before.
- One **refresh** on the changed screen, to catch state that only exists in memory.

## 3. Drive it

For each flow:

1. Open a **new tab** on `http://localhost:3000` and log in as the role.
2. Read the page structure first (`read_page` / `take_snapshot`) and act on the element ids it gives you: structure for finding, screenshot for judging.
3. Click the real buttons and fill the real forms - the flow goes through the UI, never straight to the API.
4. After each meaningful action, assert three things:

**Render** - screenshot it, and actually look at it.

- The data shown matches what you entered or what the DB holds.
- Money in Indian format (`₹2,85,000`), never raw paise, never `285000`.
- SKU at style x size x colour where the screen deals in stock.
- Empty, loading and error states say something, not a blank rectangle.
- Alignment, truncation, overflow. The standard is pixel perfection, and "not related to my issue" leaves nothing visibly broken - fix it or file it.

**Network** - read the requests.

- The expected endpoint actually fired - a button that calls nothing is the most common silent failure.
- Any 4xx/5xx that is not a deliberate part of the flow is a finding.
- One fire per click, no request storm on render.
- The payload carries what the screen showed.

**Console** - read the messages.

- Zero errors, zero unhandled rejections.
- React key warnings, `act()` warnings and prop-type errors count as findings.

5. Screenshot the end state of each flow to the scratchpad, named for the flow, and note the path for the PR body.

Look at each screenshot once, write down what you saw, move on.
A sentence of judgement replaces a page of tree: carry conclusions forward, never snapshots, network dumps or console logs.

## 4. Verdict

Report per flow: **pass**, or **fail** with what you clicked, what you expected, what happened, and the network or console line that proves it.

Any fail fails Gate 6: fix it, re-run `npm run ci`, drive the flow again.

A real defect outside this issue's scope gets filed, in the user's words, not file paths:

```bash
gh issue create -R bruhanand/KDPS --label needs-triage --title "..." --body "..."
```

Then note it in the PR under "Not covered".

Leave the stack running only if you started it and nobody is queued behind you - and say which, so the next session knows.
