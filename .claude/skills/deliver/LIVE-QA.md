# Live QA

Prove the built thing works by using it, in a real browser, the way a store user would.

Tests are not evidence.
A green suite and a broken screen coexist happily: the API returns 200 and the button does nothing, the endpoint is never called, the table renders empty, the money renders as `285000` instead of `₹2,85,000`.
This gate exists to catch exactly that.

Use whichever browser tooling this session has. Both can do everything this gate needs - drive the page, screenshot it, read the network requests and read the console.

**In the Claude app - Claude in Chrome.** This is the normal case now: Anand develops there, so this is the tooling that will be present.

```
ToolSearch: select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__form_input,mcp__claude-in-chrome__read_network_requests,mcp__claude-in-chrome__read_console_messages
```

Call `tabs_context_mcp` first, then **open a new tab** with `tabs_create_mcp`. Never reuse a tab from another session, and never reuse a tab id from a previous run.

It drives Anand's own Chrome, which has two consequences you must respect:

- **He may already be logged in**, as himself, to the alpha or to a local stack. This gate logs in as a *specific role* and proves what that role can and cannot see. Log out first, or use a fresh profile. A QA pass that ran as whoever happened to be signed in proves nothing.
- **Do not trigger alerts, confirms or any modal dialog.** They block every subsequent command and the session goes dead until he dismisses it by hand. Avoid buttons that confirm before deleting; if one is unavoidable, say so before pressing it.

**In a terminal session - chrome-devtools MCP**, if `mcp__chrome-devtools__*` is what is available instead.

```
ToolSearch: select:mcp__chrome-devtools__new_page,mcp__chrome-devtools__navigate_page,mcp__chrome-devtools__take_snapshot,mcp__chrome-devtools__take_screenshot,mcp__chrome-devtools__click,mcp__chrome-devtools__fill,mcp__chrome-devtools__fill_form,mcp__chrome-devtools__list_network_requests,mcp__chrome-devtools__list_console_messages,mcp__chrome-devtools__wait_for
```

Load them in one `ToolSearch` call, never one per tool.

The rest of this file is written in terms of what to *do* - open the page, act on it, read the network, read the console. Neither toolset changes what has to be true.

---

## 1. Preconditions: is the thing under test the thing you built?

Skip this and you will debug a ghost.
A container on `:8001` once served months-old code against a migrated schema, and the failures made no sense to anybody (issue #93).

**a. Is a stack already up?**

```bash
lsof -ti:8001 -ti:3000
```

If the ports are free, bring the stack up in the background: `./scripts/dev.sh`.

If they are held, find out by what before doing anything:

```bash
ps -o command= -p $(lsof -ti:8001)
docker ps --filter publish=8001
```

If another `/deliver` session owns it, **wait** - say so plainly and queue.
If it is a stray container from an old checkout, stop and tell Anand; do not kill another session's stack, and never pass `--free-ports` blind.

**b. Does the server carry this branch's code?**

```bash
curl -s localhost:8001/api/health | python3 -m json.tool
```

Compare the `migrations` digest against this working tree.
`core/identity.py` computes it from the migration files the process carries.
If they differ, the server is not running your code: restart it, and do not trust a single thing the browser shows until they match.

**c. Does the database match the migrations?**

```bash
cd app/backend && uv run python manage.py check_db_drift
```

Drift means a shared local Postgres is carrying schema from another branch.
Fix it (`./scripts/dev.sh --reset` rebuilds from scratch and reseeds) before QA, not after.

**d. Is the data there?**

The suites and screens assume `seed_foundation`, `seed_ptmapper` and `seed_outbound_demo` have run.
An empty screen is usually missing seed, not a bug. Confirm before filing one.

State all four results in one line before you touch the browser.

---

## 2. Build the flow list

From the issue's acceptance criteria, write the flows you will exercise - one per criterion, in the user's words.

Add these three regardless of the issue:

- The **role** the feature belongs to, logged in as that user (see `memory/test_credentials.md`) - not as `superadmin`.
  `superadmin` bypasses the RBAC matrix, so QA'ing as it proves nothing about what a store user sees.
- One **scope-negative** flow: a user who should *not* see this data logs in and does not see it.
  Read-scope has failed open in this codebase before.
- One **refresh** on the changed screen, to catch state that only exists in memory.

---

## 3. Drive it

For each flow:

1. Open a **new tab** on `http://localhost:3000` and log in as the role.
2. Read the page structure first (`read_page`, or `take_snapshot`), and act on the element ids it gives you.
   Structure for finding things; screenshot for judging them.
3. Click the real buttons and fill the real forms. Do not shortcut through the API.
4. After each meaningful action, assert three things:

**Render** - screenshot it, and actually look at it.

- Does the data shown match what you just entered or what the DB holds?
- Money in Indian format with the rupee sign and lakh grouping (`₹2,85,000`), never raw paise, never `285000`.
- SKU shown at style x size x colour where the screen deals in stock.
- Empty, loading and error states: does the screen say something, or is it a blank rectangle?
- Alignment, truncation, overflow, a table that runs off the card. Anand's standard is pixel perfection, and "not related to my issue" is not a reason to leave something visibly broken - fix it or file it.

**Network** - read the network requests.

- Did the expected endpoint actually fire? A button that calls nothing is the most common silent failure.
- Status codes: any 4xx or 5xx that is not a deliberate part of the flow is a finding.
- No duplicate fire on one click, no request storm on render.
- The payload carries what the screen showed.

**Console** - read the console messages.

- Zero errors. Zero unhandled rejections.
- React key warnings, `act()` warnings and prop-type errors count as findings.

5. Screenshot the end state of each flow, save it to the scratchpad directory with a name that says which flow it is, and note the path for the PR body.

Look at each screenshot once, write down what you saw, and move on.
Do not carry snapshots, network dumps or console logs forward - they are the single biggest cost in this gate, and a sentence of judgement replaces a page of tree.

---

## 4. Verdict

Report per flow: **pass**, or **fail** with what you clicked, what you expected, what happened, and the network or console line that proves it.

Any fail means Gate 6 fails.
Fix it, re-run `npm run ci`, and drive the flow again.

If you find a defect that is real but outside this issue's scope, file it:

```bash
gh issue create -R bruhanand/KDPS --label needs-triage --title "..." --body "..."
```

Describe it in the user's words, not in file paths.
Then note it in the PR under "Not covered".

Leave the stack running only if you started it and nobody is queued behind you.
Say which, so the next session knows.
